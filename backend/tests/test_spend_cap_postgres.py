"""The spend cap with real search and embeddings (stop-and-spend-cap tasks
2.2 and 2.4): a turn that crosses the cap in a tool round, a cap set while a
turn runs, and everything the cap does not refuse."""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select

from app import reembed
from app.chat.usage import month_totals
from app.config import get_settings
from app.main import app
from app.models import Conversation, Message, Proposal, UsageEvent
from tests import test_thought_additions as additions
from tests.chat_helpers import (
    MODEL_LIST,
    NANO,
    chat,
    completion,
    entry,
    part,
    ready_user,
    run_db,
    seed_proposal,
    tool_call,
    tool_call_chunks,
    usage_chunk,
)
from tests.sse_helpers import parse_events
from tests.test_spend_cap import add_usage
from tests.test_thought_status_postgres import status_part
from tests.thought_helpers import EMBED_MODEL, entries, models_with_embedding

pytestmark = pytest.mark.postgres

# The thought-appending fixtures: a FakeLLM with an embedding model, and
# alice's `Buy new bike lock`, filed in a conversation that talked on.
fake = additions.fake
lock = additions.lock
FILED = additions.FILED

PROPOSAL = {"title": "Oat milk", "summary": "Buy oat milk tomorrow.", "tags": ["shopping"]}


def put_cap(http_client, headers, unit, amount):
    response = http_client.put(
        "/api/usage/cap", headers=headers, json={"cap": {"unit": unit, "amount": amount}}
    )
    assert response.status_code == 200, response.text


def month_tokens(url, user_id) -> int:
    async def work(session):
        return (await month_totals(session, uuid.UUID(str(user_id))))[1]

    return run_db(url, work)


def usage_kinds(url) -> list[str]:
    async def work(session):
        return list(
            (await session.execute(select(UsageEvent.kind).order_by(UsageEvent.created_at)))
            .scalars()
            .all()
        )

    return run_db(url, work)


def messages_of(client, headers, conversation_id) -> list[dict]:
    return client.get(f"/api/conversations/{conversation_id}", headers=headers).json()["messages"]


def claim_of(url, conversation_id):
    async def work(session):
        return (await session.get(Conversation, uuid.UUID(conversation_id))).turn_started_at

    return run_db(url, work)


def events(response) -> list[tuple[str, dict]]:
    return list(parse_events(response.text))


def events_of(response, name) -> list[dict]:
    return [data for event, data in events(response) if event == name]


def just_below_the_cap(client, headers, url, user_id):
    """A token cap 50 tokens above the month so far: a round of 120 tokens reaches it."""
    put_cap(client, headers, "tokens", month_tokens(url, user_id) + 50)


def user_id_of(client, headers) -> str:
    return client.get("/api/me", headers=headers).json()["id"]


# --- 2.2 a turn that crosses the cap between rounds ---


def test_a_search_round_that_reaches_the_cap_runs_the_search_and_ends_the_turn(
    client, alice, lock, fake, test_database_url
):
    user_id = user_id_of(client, alice)
    just_below_the_cap(client, alice, test_database_url, user_id)
    fake.queue(
        tool_call_chunks("search_thoughts", '{"query": "bike lock"}') + [usage_chunk(100, 20)]
    )

    response = chat(client, alice, "what about my bike lock?")

    assert len(fake.chat_requests) == 1
    assert events(response)[-1] == (
        "error",
        {"error": {"code": "spend_cap_reached", "message": events(response)[-1][1]["error"]["message"]}},
    )
    assert "Raise or remove it in Settings" in events(response)[-1][1]["error"]["message"]
    [end] = [e for e in events_of(response, "tool") if e["phase"] == "end"]
    assert [source["id"] for source in end["sources"]] == [lock["id"]]
    conversation_id = events_of(response, "conversation")[0]["id"]
    stored = messages_of(client, alice, conversation_id)
    assert [m["role"] for m in stored] == ["user", "assistant", "tool"]
    assert stored[1]["error_code"] == "spend_cap_reached"
    assert stored[1]["status"] == "complete"
    assert stored[2]["details"]["sources"] == end["sources"]
    assert claim_of(test_database_url, conversation_id) is None
    # The search's embedding call is recorded and counts too.
    assert usage_kinds(test_database_url)[-2:] == ["chat", "embed"]


def test_a_proposal_round_that_reaches_the_cap_keeps_the_card_and_it_can_be_confirmed(
    client, alice, fake, test_database_url
):
    # No thoughts yet, so the similar-thought check finds no candidate.
    ready_user(client, alice)
    user_id = user_id_of(client, alice)
    just_below_the_cap(client, alice, test_database_url, user_id)
    fake.queue(tool_call_chunks("propose_thought", json.dumps(PROPOSAL)) + [usage_chunk(100, 20)])

    response = chat(client, alice, "I need oat milk tomorrow")

    assert len(fake.chat_requests) == 1
    assert events(response)[-1][1]["error"]["code"] == "spend_cap_reached"
    [proposal] = events_of(response, "proposal")
    conversation_id = events_of(response, "conversation")[0]["id"]
    stored = messages_of(client, alice, conversation_id)
    assert [m["role"] for m in stored] == ["user", "assistant", "tool"]
    assert stored[1]["error_code"] == "spend_cap_reached"
    assert stored[2]["details"]["proposal_id"] == proposal["id"]
    assert claim_of(test_database_url, conversation_id) is None

    confirmed = client.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal['id']}/confirm",
        headers=alice,
        json={"parts": [0], **PROPOSAL, "category": "task"},
    )

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["saved"] is True
    thought = client.get(f"/api/thoughts/{confirmed.json()['thought_id']}", headers=alice).json()
    assert thought["title"] == "Oat milk"


@pytest.fixture
def embedding_env(settings_env):
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)


async def test_a_cap_set_while_a_turn_runs_ends_it_before_the_next_call(
    embedding_env, async_api, test_database_url
):
    api = async_api
    api.fake.models = models_with_embedding(MODEL_LIST)
    response = await api.http.put(
        "/api/providers/nebius/key", headers=api.headers, json={"key": "nb-valid-key-aaaa1111"}
    )
    assert response.status_code == 200, response.text
    # A settings row with a temperature and no cap: the turn's session loads
    # it (temperature_for) before the cap is saved elsewhere.
    response = await api.http.put(
        "/api/settings/models",
        headers=api.headers,
        json={"models": [entry(NANO, default=True)], "temperature": 0.5},
    )
    assert response.status_code == 200, response.text
    user_id = await api.user_id()

    async def seed(session):
        conversation = Conversation(
            user_id=user_id,
            title="Bike",
            provider_id="nebius",
            model=NANO,
            last_activity_at=datetime.now(UTC),
        )
        session.add(conversation)
        await session.flush()
        session.add(
            Message(conversation_id=conversation.id, position=0, role="user", content="bike lock")
        )
        proposal = Proposal(
            conversation_id=conversation.id,
            user_id=user_id,
            position=1,
            from_position=0,
            to_position=0,
            raw_text="buy new bike lock",
            parts=[part(title=FILED["title"])],
        )
        session.add(proposal)
        await session.commit()
        return str(conversation.id), str(proposal.id)

    conversation_id, proposal_id = await api.db(seed)
    response = await api.http.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal_id}/confirm",
        headers=api.headers,
        json={"parts": [0], **FILED},
    )
    assert response.status_code == 200, response.text
    assert response.json()["saved"] is True

    reached, gate = asyncio.Event(), asyncio.Event()

    async def blocked(request):
        reached.set()
        await gate.wait()
        return api.fake._embed(request)

    api.fake.embed_replies.append(blocked)
    api.fake.queue(
        tool_call_chunks("search_thoughts", '{"query": "bike lock"}') + [usage_chunk(100, 20)]
    )

    answer = asyncio.create_task(api.chat("what about my bike lock?"))
    await asyncio.wait_for(reached.wait(), 5)
    # The month so far is well above one token.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as other:
        response = await other.put(
            "/api/usage/cap", headers=api.headers, json={"cap": {"unit": "tokens", "amount": 1}}
        )
        assert response.status_code == 200, response.text
        assert response.json()["cap"]["reached"] is True
    gate.set()
    response = await asyncio.wait_for(answer, 5)

    assert len(api.fake.chat_requests) == 1
    last = list(parse_events(response.text))[-1]
    assert last[0] == "error"
    assert last[1]["error"]["code"] == "spend_cap_reached"
    assert "1 tokens" not in last[1]["error"]["message"]
    assert "Your monthly spend cap of 1 token" in last[1]["error"]["message"]


# --- 2.4 what the cap does not refuse ---


@pytest.fixture
def capped(client, alice, lock, fake, test_database_url) -> dict:
    """alice, with `Buy new bike lock` filed, at a $5.00 cap."""
    user_id = user_id_of(client, alice)
    put_cap(client, alice, "usd", 5)
    add_usage(test_database_url, user_id, ("chat", 100, 10, "5.12"))
    assert client.get("/api/usage", headers=alice).json()["cap"]["reached"] is True
    fake.embed_requests.clear()
    return {**lock, "user_id": user_id}


def test_confirming_a_proposal_at_the_cap_saves_and_embeds_it(
    client, alice, capped, fake, test_database_url
):
    conversation_id = capped["conversation_id"]
    proposal_id = seed_proposal(
        test_database_url,
        conversation_id,
        [part(title="Buy oat milk")],
        position=6,
        from_position=2,
        to_position=4,
    )
    kinds = usage_kinds(test_database_url)

    response = client.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal_id}/confirm",
        headers=alice,
        json={"parts": [0], **FILED, "title": "Buy oat milk"},
    )

    assert response.status_code == 200, response.text
    thought_id = response.json()["thought_id"]
    assert entries(test_database_url, thought_id) != {}
    assert usage_kinds(test_database_url) == [*kinds, "embed"]


def test_editing_a_thought_at_the_cap_embeds_it_again(client, alice, capped, fake, test_database_url):
    kinds = usage_kinds(test_database_url)

    response = client.patch(
        f"/api/thoughts/{capped['id']}", headers=alice, json={"summary": "A black D-lock."}
    )

    assert response.status_code == 200, response.text
    assert len(fake.embed_requests) == 1
    assert usage_kinds(test_database_url) == [*kinds, "embed"]


def test_confirming_an_addition_at_the_cap_updates_and_embeds_the_thought(
    client, alice, capped, fake, test_database_url
):
    proposal_id = additions.seed_addition(test_database_url, capped["conversation_id"], capped)
    kinds = usage_kinds(test_database_url)

    response = additions.add(client, alice, capped["conversation_id"], proposal_id)

    assert response.status_code == 200, response.text
    after = client.get(f"/api/thoughts/{capped['id']}", headers=alice).json()
    assert after["summary"] == additions.ADDED["summary"]
    assert len(fake.embed_requests) == 1
    assert usage_kinds(test_database_url) == [*kinds, "embed"]


def test_rebuilding_an_index_at_the_cap_records_its_embedding_calls(
    client, alice, capped, fake, settings_env, test_database_url
):
    settings_env.setenv("EMBEDDING_MODEL", "vendor/embed-model-2")
    get_settings.cache_clear()
    fake.models = {
        **fake.models,
        "data": [
            *fake.models["data"],
            {"id": "vendor/embed-model-2", "pricing": {"prompt": "0.00000002", "completion": "0"}},
        ],
    }
    kinds = usage_kinds(test_database_url)

    code = asyncio.run(
        reembed.main(["--user", capped["user_id"]], http_client=fake.http_client())
    )

    assert code == 0
    assert len(fake.embed_requests) >= 1
    added = usage_kinds(test_database_url)[len(kinds):]
    assert added == ["embed"] * len(fake.embed_requests)


def test_confirming_a_status_card_at_the_cap_marks_the_thought_done(
    client, alice, capped, test_database_url
):
    conversation_id = capped["conversation_id"]
    proposal_id = seed_proposal(
        test_database_url,
        conversation_id,
        [status_part(capped["id"], capped["title"])],
        position=6,
        from_position=2,
        to_position=4,
    )

    response = client.post(
        f"/api/conversations/{conversation_id}/proposals/{proposal_id}/confirm",
        headers=alice,
        json={"parts": [0]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["message"] == "Marked done."
    assert client.get(f"/api/thoughts/{capped['id']}", headers=alice).json()["status"] == "done"


def test_the_model_test_at_the_cap_runs_and_records_two_calls(
    client, alice, capped, fake, test_database_url
):
    fake.queue(completion("Ready."), completion(None, tool_calls=[tool_call("ping", {})]))
    kinds = usage_kinds(test_database_url)

    response = client.post(
        "/api/settings/models/test", headers=alice, json={"provider_id": "nebius", "model": NANO}
    )

    assert response.status_code == 200, response.text
    assert usage_kinds(test_database_url) == [*kinds, "test", "test"]
    assert len(fake.chat_requests) == 2
