"""A stopped round's usage (stop-and-spend-cap task 3.3, design decision 4).

A round stopped in its stream has no usage report yet: it is recorded from
what the provider reported so far, else from estimates, with the cost from
the model's prices the route read. No step of a turn fetches the model list.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import select

from app.chat.model_info import clear_model_info_cache
from app.chat.prompt import estimate_text_tokens, estimate_tokens
from app.models import UsageEvent, UserSettings
from app.provider_config import get_providers_config
from tests.chat_helpers import (
    NANO,
    PROVIDERS_FIXTURE,
    Hold,
    _chunk,
    entry,
    finish_chunk,
    text_chunks,
    tool_call_chunks,
    turns_settled,
    usage_chunk,
)
from tests.sse_helpers import parse_events
from tests.stop_helpers import STOPPED, the_turn
from tests.test_background_turns import messages_of, tool_round, watch_chat
from tests import test_connector_background_turns as connector_turns
from tests.test_connector_background_turns import connector_on
from tests.test_connector_turns import FakeConnect

# MCP_ENABLED with user connectors.
mcp_env = connector_turns.mcp_env
NANO_PROMPT = Decimal("0.00000006")
NANO_COMPLETION = Decimal("0.00000024")
NOT_RUN = "Not run: the user stopped the answer before this tool finished."


def cost(prompt: int, completion: int) -> Decimal:
    return NANO_PROMPT * prompt + NANO_COMPLETION * completion


async def chat_rows(api) -> list[UsageEvent]:
    async def work(session):
        return list(
            (
                await session.execute(
                    select(UsageEvent)
                    .where(UsageEvent.kind == "chat")
                    .order_by(UsageEvent.created_at)
                )
            ).scalars()
        )

    return await api.db(work)


def sent_estimate(api, index: int = 0) -> int:
    """estimate_tokens of what the model call at `index` sent: its messages
    and the tools it offered."""
    request = api.fake.chat_requests[index]
    return estimate_tokens(request["messages"], request.get("tools"))


async def stopped_at_hold(api, *replies: list, message: str = "hello", conversation_id=None):
    """Send a message whose last reply waits at a Hold, stop it there, and
    return (turn, events, conversation id) once it has ended."""
    hold = next(item for item in replies[-1] if isinstance(item, Hold))
    api.fake.queue(*replies)
    watcher = await watch_chat(api, message, conversation_id)
    await asyncio.wait_for(hold.reached.wait(), 5)
    turn = the_turn()
    turn.stop()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()
    assert left.events[-1] == STOPPED
    return turn, left, str(turn.conversation_id)


def with_stream_usage(tmp_path: Path, settings_env, stream_usage: str) -> None:
    """The provider fixture with Nebius reporting usage as `stream_usage`."""
    raw = yaml.safe_load(PROVIDERS_FIXTURE.read_text())
    raw["providers"]["nebius"]["capabilities"]["stream_usage"] = stream_usage
    path = tmp_path / "providers.yaml"
    path.write_text(yaml.safe_dump(raw))
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(path))
    get_providers_config.cache_clear()


async def test_a_stop_mid_stream_records_estimated_tokens_and_their_cost(async_api):
    api = async_api
    await api.ready()
    reply = text_chunks("Here is a ", "long answer about sleep")
    reply.insert(3, Hold())

    turn, _, conversation_id = await stopped_at_hold(api, reply)

    [row] = await chat_rows(api)
    received = estimate_text_tokens("Here is a long answer about sleep")
    assert row.conversation_id == uuid.UUID(conversation_id)
    assert (row.prompt_tokens, row.completion_tokens) == (sent_estimate(api), received)
    assert row.cost_usd == cost(sent_estimate(api), received)
    assert (row.provider_id, row.model) == ("nebius", NANO)


async def test_a_stop_while_the_model_sends_a_calls_arguments_counts_them(async_api):
    api = async_api
    await api.ready()
    reply = text_chunks("Let me look. ")[:-1] + tool_call_chunks(
        "search_thoughts", '{"query": "oat milk and bread"}', "call_s"
    )
    # After the call's name and the first half of its arguments.
    reply.insert(len(reply) - 1, Hold())

    await stopped_at_hold(api, reply)

    [row] = await chat_rows(api)
    half = '{"query": "oat milk and bread"}'[: len('{"query": "oat milk and bread"}') // 2]
    assert row.completion_tokens == estimate_text_tokens("Let me look. " + half)
    assert row.completion_tokens > estimate_text_tokens("Let me look. ")


async def test_running_counts_reported_before_the_stop_are_kept(
    async_api, settings_env, tmp_path
):
    api = async_api
    with_stream_usage(tmp_path, settings_env, "incremental")
    await api.ready()
    text = "Counting " * 30
    # A provider that reports usage on every chunk: the last report was 900
    # prompt and 40 completion tokens, and more text came after it.
    reply = [
        _chunk({"role": "assistant", "content": ""}),
        _chunk({"content": "Counting "}, usage={"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940}),
        _chunk({"content": text}),
        Hold(),
        finish_chunk(),
    ]

    await stopped_at_hold(api, reply)

    [row] = await chat_rows(api)
    received = estimate_text_tokens("Counting " + text)
    assert received > 40
    assert (row.prompt_tokens, row.completion_tokens) == (900, max(40, received))
    assert row.cost_usd == cost(900, max(40, received))


async def test_a_short_answer_keeps_the_reported_completion_count(
    async_api, settings_env, tmp_path
):
    api = async_api
    with_stream_usage(tmp_path, settings_env, "incremental")
    await api.ready()
    reply = [
        _chunk({"content": "Hi"}, usage={"prompt_tokens": 900, "completion_tokens": 40, "total_tokens": 940}),
        Hold(),
        finish_chunk(),
    ]

    await stopped_at_hold(api, reply)

    [row] = await chat_rows(api)
    assert (row.prompt_tokens, row.completion_tokens) == (900, 40)


async def test_the_earlier_round_keeps_its_reported_tokens(async_api):
    api = async_api
    await api.ready()

    await stopped_at_hold(
        api,
        tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Let me look. "),
        text_chunks("Found ")[:-1] + [Hold()] + text_chunks("nothing."),
    )

    first, second = await chat_rows(api)
    assert (first.prompt_tokens, first.completion_tokens) == (100, 20)
    assert (second.prompt_tokens, second.completion_tokens) == (
        sent_estimate(api, 1),
        estimate_text_tokens("Found "),
    )
    assert sent_estimate(api, 1) > sent_estimate(api, 0)


async def test_a_provider_that_reports_no_usage_records_the_stop_as_unknown(
    async_api, settings_env, tmp_path
):
    api = async_api
    with_stream_usage(tmp_path, settings_env, "none")
    await api.ready()
    reply = text_chunks("Half ", "an answer")
    reply.insert(2, Hold())

    await stopped_at_hold(api, reply)

    [row] = await chat_rows(api)
    assert (row.prompt_tokens, row.completion_tokens, row.cost_usd) == (None, None, None)


async def test_a_stop_during_a_connector_call_adds_no_second_row(mcp_env, async_api):
    api = async_api
    await api.ready()
    fake = FakeConnect()
    conversation_id = await connector_on(api, fake, "list_events")
    rows_before = len(await chat_rows(api))
    entered, gate = asyncio.Event(), asyncio.Event()

    async def slow(name, arguments):
        entered.set()
        await asyncio.wait_for(gate.wait(), 5)

    fake.answer = slow
    api.fake.queue(
        tool_call_chunks("calendar__list_events", '{"text": "monday"}', "call_l")
        + [finish_chunk("tool_calls"), usage_chunk()]
    )
    watcher = await watch_chat(api, "what is on?", conversation_id)
    await asyncio.wait_for(entered.wait(), 5)
    turn = the_turn()
    turn.stop()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert left.events[-1] == STOPPED
    rows = (await chat_rows(api))[rows_before:]
    assert [(row.prompt_tokens, row.completion_tokens) for row in rows] == [(100, 20)]
    messages = await messages_of(api, conversation_id)
    assert messages[-2].content.startswith("Stopped while calendar__list_events was running.")


async def test_a_stop_reads_no_model_list(async_api):
    api = async_api
    await api.ready()
    reply = text_chunks("Half ", "an answer")
    hold = Hold()
    reply.insert(2, hold)
    api.fake.queue(reply)
    watcher = await watch_chat(api, "hello")
    await asyncio.wait_for(hold.reached.wait(), 5)
    turn = the_turn()
    # The route filled the cache for check_room; it is gone now, and the
    # model list would not answer.
    clear_model_info_cache()
    api.fake.models_gate = asyncio.Event()
    calls_before = api.fake.model_list_calls

    turn.stop()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert left.events[-1] == STOPPED
    assert not api.fake.models_gate.is_set()
    assert api.fake.model_list_calls == calls_before
    messages = await messages_of(api, str(turn.conversation_id))
    assert (messages[-1].status, messages[-1].content) == ("stopped", "Half ")
    [row] = await chat_rows(api)
    assert row.cost_usd == cost(row.prompt_tokens, row.completion_tokens)
    assert row.cost_usd is not None


async def set_warning(api, amount: int) -> None:
    response = await api.http.put(
        "/api/settings/models",
        headers=api.headers,
        json={
            "models": [entry(NANO, default=True)],
            "temperature": None,
            "warning": {"unit": "usd", "amount": amount},
        },
    )
    assert response.status_code == 200, response.text


async def add_cost(api, amount: str) -> None:
    user_id = await api.user_id()

    async def work(session):
        session.add(
            UsageEvent(
                user_id=user_id,
                kind="chat",
                provider_id="nebius",
                model=NANO,
                prompt_tokens=100,
                completion_tokens=10,
                cost_usd=Decimal(amount),
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    await api.db(work)


async def test_a_stop_while_the_warning_is_saved_still_sends_it_once(
    async_api, cancel_spy, block_commit
):
    api = async_api
    await api.ready()
    await set_warning(api, 3)
    # Round 1's usage (100 and 20 tokens of NANO) crosses $3.00.
    await add_cost(api, "2.99999")
    blocked = block_commit(
        lambda session: any(
            isinstance(row, UserSettings) and row.warning_notified_month is not None
            for row in session.dirty
        )
    )
    api.fake.queue(
        tool_round("search_thoughts", '{"query": "milk"}', "call_s", text="Let me look. ")
    )
    watcher = await watch_chat(api, "what milk?")
    await blocked.reached()
    turn = the_turn()
    conversation_id = str(turn.conversation_id)

    turn.stop()
    assert cancel_spy(turn) == 0
    blocked.release.set()
    left = await asyncio.wait_for(watcher, 5)
    await turns_settled()

    assert cancel_spy(turn) == 0
    names = [name for name, _ in left.events]
    assert names[-2:] == ["notice", "error"]
    assert left.events[-2][1]["kind"] == "usage_warning"
    assert left.events[-1] == STOPPED
    messages = await messages_of(api, conversation_id)
    assert [(m.role, m.content) for m in messages][-2:] == [("tool", NOT_RUN), ("assistant", None)]
    turn_rows = [row for row in await chat_rows(api) if row.conversation_id is not None]
    assert [(row.prompt_tokens, row.completion_tokens) for row in turn_rows] == [(100, 20)]

    user_id = await api.user_id()

    async def notified(session):
        return (await session.get(UserSettings, user_id)).warning_notified_month

    assert await api.db(notified) == datetime.now(UTC).strftime("%Y-%m")

    api.fake.queue(text_chunks("Sure.") + [usage_chunk()])
    response = await api.chat("and now?", conversation_id)
    events = parse_events(response.text)
    assert events[-1] == ("done", {})
    assert not [data for name, data in events if name == "notice" and data["kind"] == "usage_warning"]


async def test_no_usage_row_holds_message_text(async_api):
    api = async_api
    await api.ready()
    reply = text_chunks("A secret plan ", "about sleep")
    reply.insert(3, Hold())

    await stopped_at_hold(api, reply, message="my private question")

    rows = await chat_rows(api)
    assert rows
    for row in rows:
        stored = repr([getattr(row, column.key) for column in UsageEvent.__table__.columns])
        for text in ("secret", "sleep", "private question"):
            assert text not in stored
