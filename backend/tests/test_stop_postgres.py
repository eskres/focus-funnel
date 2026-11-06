"""Stop with real search and embeddings, and a proposal confirmed after a
stop (stop-and-spend-cap task 3.2, the Postgres part)."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models import Proposal, UsageEvent, User
from tests.chat_helpers import MODEL_LIST, Hold, text_chunks, turns_settled
from tests.stop_helpers import STOPPED, the_turn
from tests.test_background_turns import messages_of, tool_round, watch_chat
from tests.thought_helpers import EMBED_MODEL, models_with_embedding

pytestmark = pytest.mark.postgres

PROPOSAL = {"title": "Oat milk", "summary": "Buy oat milk tomorrow.", "tags": ["shopping"]}


@pytest.fixture
def embedding_env(settings_env):
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def ready_with_embeddings(api) -> None:
    api.fake.models = models_with_embedding(MODEL_LIST)
    await api.ready()


async def store_oat_milk(api) -> str:
    from app.thoughts.store import store_thought

    user_id = await api.user_id()

    async def work(session):
        user = await session.get(User, user_id)
        outcome = await store_thought(
            session,
            user,
            title="Oat milk",
            summary="Buy oat milk on the way home.",
            tags=["groceries"],
            settings=get_settings(),
            http_client=api.fake.http_client(),
        )
        await session.commit()
        return str(outcome.thought.id)

    return await api.db(work)


async def usage_of(api, conversation_id: str) -> list[UsageEvent]:
    async def work(session):
        return list(
            (
                await session.execute(
                    select(UsageEvent)
                    .where(UsageEvent.conversation_id == uuid.UUID(conversation_id))
                    .order_by(UsageEvent.created_at)
                )
            ).scalars()
        )

    return await api.db(work)


async def test_a_stop_while_the_search_embeds_lets_it_finish_and_keep_its_sources(
    embedding_env, async_api, cancel_spy
):
    api = async_api
    await ready_with_embeddings(api)
    thought_id = await store_oat_milk(api)
    entered, gate = asyncio.Event(), asyncio.Event()

    async def slow_embedding(request):
        entered.set()
        await asyncio.wait_for(gate.wait(), 5)
        return api.fake.embedding(request)

    api.fake.embed_replies.append(slow_embedding)
    api.fake.queue(
        tool_round("search_thoughts", '{"query": "oat milk"}', "call_s", text="Let me look. "),
        text_chunks("Never asked."),
    )
    watcher = await watch_chat(api, "what milk did I want?")
    await asyncio.wait_for(entered.wait(), 5)
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    await asyncio.sleep(0.05)
    assert cancel_spy(turn) == 0
    gate.set()
    left = await asyncio.wait_for(watcher, 10)
    await turns_settled()

    assert cancel_spy(turn) == 0
    names = [(name, data.get("phase")) for name, data in left.events]
    assert names[-2:] == [("tool", "end"), ("error", None)]
    assert left.events[-2][1]["name"] == "search_thoughts"
    assert left.events[-1] == STOPPED
    assert len(api.fake.chat_requests) == 1
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.status, m.content) for m in messages] == [
        ("user", "complete", "what milk did I want?"),
        ("assistant", "complete", "Let me look. "),
        ("tool", "complete", messages[2].content),
        ("assistant", "stopped", None),
    ]
    assert [source["id"] for source in messages[2].details["sources"]] == [thought_id]
    # The round's text is stored once, with its tool call.
    assert [m.content for m in messages].count("Let me look. ") == 1
    rows = await usage_of(api, conversation_id)
    assert sorted(row.kind for row in rows) == ["chat", "embed"]


async def test_a_proposal_shown_before_a_stop_can_be_confirmed(
    embedding_env, async_api, cancel_spy
):
    api = async_api
    await ready_with_embeddings(api)
    hold = Hold()
    api.fake.queue(
        tool_round("propose_thought", json.dumps(PROPOSAL), "call_p", text="Here it is. "),
        [hold] + text_chunks("Confirm it when you like."),
    )
    watcher = await watch_chat(api, "I need oat milk")
    await asyncio.wait_for(hold.reached.wait(), 5)
    turn = the_turn()
    conversation_id = str(turn.conversation_id)
    assert "proposal" in [name for name, _ in turn.events]

    turn.stop()
    left = await asyncio.wait_for(watcher, 10)
    await turns_settled()

    assert left.events[-1] == STOPPED

    async def proposals(session):
        return list(
            (
                await session.execute(
                    select(Proposal).where(Proposal.conversation_id == uuid.UUID(conversation_id))
                )
            ).scalars()
        )

    [proposal] = await api.db(proposals)
    response = await api.http.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal.id}/confirm",
        headers=api.headers,
        json={
            "parts": [0],
            "title": "Oat milk",
            "summary": "Buy oat milk tomorrow.",
            "tags": ["shopping"],
            "category": "task",
        },
    )
    assert response.status_code == 200, response.text
    thought = await api.http.get(
        f"/api/thoughts/{response.json()['thought_id']}", headers=api.headers
    )
    assert thought.status_code == 200
    assert thought.json()["title"] == "Oat milk"
