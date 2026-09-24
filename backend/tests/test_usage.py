"""Usage records, the cost estimate, GET /api/usage, and the warning threshold."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from openai.types.chat import ChatCompletionChunk
from sqlalchemy import select, update

from app.chat.turn import RoundState, read_round
from app.chat.usage import estimate_cost
from app.models import UsageEvent, UserSettings
from app.provider_models import ModelPrices
from tests.chat_helpers import (
    BIG,
    NANO,
    NO_TOOLS,
    UNPRICED,
    _chunk,
    chat,
    completion,
    entry,
    finish_chunk,
    ready_user,
    run_db,
    save_key,
    save_models,
    seed_conversation,
    text_chunks,
    tool_call,
    tool_call_chunks,
    usage_chunk,
    user_id_for,
)
from tests.sse_helpers import parse_events

PROPOSAL = {"title": "Oat milk", "summary": "Buy oat milk tomorrow.", "tags": ["shopping"]}
NANO_PROMPT = Decimal("0.00000006")
NANO_COMPLETION = Decimal("0.00000024")


def usage_rows(url: str) -> list[UsageEvent]:
    async def work(session):
        return list(
            (await session.execute(select(UsageEvent).order_by(UsageEvent.created_at))).scalars()
        )

    return run_db(url, work)


def notices(response) -> list[dict]:
    """The usage warnings a chat response sent."""
    return [
        data
        for name, data in parse_events(response.text)
        if name == "notice" and data["kind"] == "usage_warning"
    ]


def set_warning(client, headers, unit, amount, *entries):
    response = client.put(
        "/api/settings/models",
        headers=headers,
        json={
            "models": list(entries or (entry(NANO, default=True),)),
            "temperature": None,
            "warning": {"unit": unit, "amount": amount},
        },
    )
    assert response.status_code == 200, response.text
    return response


# --- 9.1 every call is recorded ---


def test_a_chat_answer_records_its_tokens_and_model(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi there") + [usage_chunk(120, 30)])

    response = chat(client, alice, "hello")

    assert response.status_code == 200
    [row] = usage_rows(test_database_url)
    assert (row.kind, row.provider_id, row.model) == ("chat", "nebius", NANO)
    assert (row.prompt_tokens, row.completion_tokens) == (120, 30)
    assert str(row.user_id) == user_id_for(client, alice)
    assert row.conversation_id is not None


def test_each_round_of_a_tool_loop_is_recorded(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    fake_llm.queue(
        tool_call_chunks("search_thoughts", '{"query": "rent"}')
        + [finish_chunk("tool_calls"), usage_chunk(100, 10)],
        text_chunks("Nothing filed yet.") + [usage_chunk(140, 12)],
    )

    chat(client, alice, "what did I say about rent?")

    assert [(r.prompt_tokens, r.completion_tokens) for r in usage_rows(test_database_url)] == [
        (100, 10),
        (140, 12),
    ]


def test_a_forced_proposal_is_recorded_as_proposal(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice, messages=("oat milk", "Ok."))
    fake_llm.queue(
        completion(
            None,
            tool_calls=[tool_call("propose_thought", PROPOSAL)],
            usage={"prompt_tokens": 80, "completion_tokens": 25, "total_tokens": 105},
        )
    )

    client.post(f"/api/conversations/{conversation_id}/proposal", headers=alice)

    [row] = usage_rows(test_database_url)
    assert (row.kind, row.model, row.prompt_tokens, row.completion_tokens) == (
        "proposal",
        NANO,
        80,
        25,
    )
    assert str(row.conversation_id) == conversation_id


def test_a_model_test_records_both_calls_as_test(client, alice, fake_llm, test_database_url):
    save_key(client, alice)
    fake_llm.queue(completion("Ready."), completion(None, tool_calls=[tool_call("ping", {})]))

    response = client.post(
        "/api/settings/models/test",
        headers=alice,
        json={"provider_id": "nebius", "model": BIG},
    )

    assert response.status_code == 200, response.text
    rows = usage_rows(test_database_url)
    assert [(r.kind, r.model, r.conversation_id) for r in rows] == [("test", BIG, None)] * 2


def test_no_record_holds_message_text(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    secret = "my secret plan about the zebra"
    fake_llm.queue(text_chunks("The zebra plan sounds good") + [usage_chunk()])

    chat(client, alice, secret)

    columns = set(UsageEvent.__table__.columns.keys())
    assert columns == {
        "id",
        "user_id",
        "conversation_id",
        "kind",
        "provider_id",
        "model",
        "prompt_tokens",
        "completion_tokens",
        "cost_usd",
        "created_at",
    }
    [row] = usage_rows(test_database_url)
    values = " ".join(str(getattr(row, name)) for name in columns)
    assert "zebra" not in values


def test_two_models_in_one_conversation_are_recorded_against_each(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice, entry(NANO, default=True), entry(BIG))
    fake_llm.queue(text_chunks("One") + [usage_chunk()], text_chunks("Two") + [usage_chunk()])
    first = chat(client, alice, "hello")
    conversation_id = [d for n, d in parse_events(first.text) if n == "conversation"][0]["id"]

    chat(client, alice, "again", conversation_id, provider_id="nebius", model=BIG)

    assert [row.model for row in usage_rows(test_database_url)] == [NANO, BIG]


# --- 9.2 the estimated cost ---


def test_a_priced_model_records_its_estimated_cost(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi") + [usage_chunk(1000, 200)])

    chat(client, alice, "hello")

    [row] = usage_rows(test_database_url)
    assert row.cost_usd == 1000 * NANO_PROMPT + 200 * NANO_COMPLETION


def test_an_unpriced_model_records_its_tokens_and_an_unknown_cost(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice, entry(UNPRICED, default=True))
    fake_llm.queue(text_chunks("Hi") + [usage_chunk(50, 5)])

    chat(client, alice, "hello")

    [row] = usage_rows(test_database_url)
    assert (row.prompt_tokens, row.completion_tokens, row.cost_usd) == (50, 5, None)


def test_a_call_with_no_reported_tokens_records_nothing(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi"))

    response = chat(client, alice, "hello")

    assert response.status_code == 200
    assert usage_rows(test_database_url) == []


def test_the_cost_formula():
    prices = ModelPrices(prompt="0.000001", completion="0.000003")
    assert estimate_cost(prices, 1000, 100) == Decimal("0.0013")
    assert estimate_cost(None, 1000, 100) is None
    assert estimate_cost(prices, None, None) is None


# --- 9.3 GET /api/usage ---


def seed_usage(url, user_id, *rows):
    """rows: (days_ago, model, prompt, completion, cost or None)"""

    async def work(session):
        now = datetime.now(UTC)
        for days_ago, model, prompt, completion_tokens, cost in rows:
            session.add(
                UsageEvent(
                    user_id=uuid.UUID(user_id),
                    kind="chat",
                    provider_id="nebius",
                    model=model,
                    prompt_tokens=prompt,
                    completion_tokens=completion_tokens,
                    cost_usd=None if cost is None else Decimal(cost),
                    created_at=now - timedelta(days=days_ago),
                )
            )
        await session.commit()

    run_db(url, work)


def test_usage_lists_every_day_oldest_first(client, alice, test_database_url):
    seed_usage(
        test_database_url,
        user_id_for(client, alice),
        (0, NANO, 100, 10, "0.5"),
        (0, NANO, 100, 10, "0.25"),
        (2, BIG, 1000, 100, "2"),
    )

    body = client.get("/api/usage", headers=alice).json()

    days = body["days"]
    assert len(days) == 30
    assert [d["date"] for d in days] == sorted(d["date"] for d in days)
    assert days[-1]["date"] == datetime.now(UTC).date().isoformat()
    assert days[-1]["cost_usd"] == 0.75
    assert days[-1]["tokens"] == 220
    assert days[-3]["cost_usd"] == 2
    assert [(m["model"], m["cost_usd"], m["calls"]) for m in body["by_model"]] == [
        (BIG, 2.0, 1),
        (NANO, 0.75, 2),
    ]


def test_the_period_parameter_sets_the_days(client, alice, test_database_url):
    seed_usage(test_database_url, user_id_for(client, alice), (10, NANO, 100, 10, "1"))

    week = client.get("/api/usage?days=7", headers=alice).json()
    longer = client.get("/api/usage?days=90", headers=alice).json()

    assert len(week["days"]) == 7
    assert week["by_model"] == []
    assert len(longer["days"]) == 90
    assert longer["by_model"][0]["cost_usd"] == 1
    assert client.get("/api/usage?days=0", headers=alice).status_code == 422


def test_no_usage_gives_an_empty_report(client, alice):
    body = client.get("/api/usage", headers=alice).json()

    assert body["by_model"] == []
    assert all(d["calls"] == 0 for d in body["days"])
    assert body["month"]["calls"] == 0
    assert body["month"]["start"] == datetime.now(UTC).date().replace(day=1).isoformat()
    assert body["warning"] is None


def test_unknown_costs_are_counted_in_tokens_and_marked(client, alice, test_database_url):
    seed_usage(
        test_database_url,
        user_id_for(client, alice),
        (0, NO_TOOLS, 100, 10, None),
        (0, NANO, 100, 10, "0.1"),
    )

    body = client.get("/api/usage", headers=alice).json()

    assert body["days"][-1]["unknown_cost_calls"] == 1
    assert body["days"][-1]["tokens"] == 220
    assert body["month"]["unknown_cost_calls"] == 1


def test_another_users_usage_never_appears(client, alice, bob, test_database_url):
    seed_usage(test_database_url, user_id_for(client, alice), (0, NANO, 100, 10, "1"))

    body = client.get("/api/usage", headers=bob).json()

    assert body["by_model"] == []
    assert body["month"]["cost_usd"] == 0


def test_a_deleted_conversations_spend_stays(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi") + [usage_chunk(1000, 200)])
    response = chat(client, alice, "hello")
    conversation_id = [d for n, d in parse_events(response.text) if n == "conversation"][0]["id"]

    client.delete(f"/api/conversations/{conversation_id}", headers=alice)

    body = client.get("/api/usage", headers=alice).json()
    assert body["month"]["calls"] == 1
    assert body["by_model"][0]["model"] == NANO


def test_the_report_links_the_consoles_of_saved_providers_and_no_balance(client, alice, fake_llm):
    save_key(client, alice)

    body = client.get("/api/usage", headers=alice).json()

    assert body["consoles"] == [
        {
            "provider_id": "nebius",
            "label": "Nebius Token Factory",
            "url": "https://tokenfactory.nebius.com/",
        }
    ]
    assert "balance" not in body


# --- 9.4 the warning threshold ---


def test_the_threshold_is_saved_and_returned(client, alice, fake_llm):
    save_key(client, alice)
    set_warning(client, alice, "usd", 5)

    body = client.get("/api/settings/models", headers=alice).json()

    assert body["warning"] == {"unit": "usd", "amount": 5.0}


def test_a_save_without_a_threshold_clears_it(client, alice, fake_llm):
    save_key(client, alice)
    set_warning(client, alice, "tokens", 1000)

    save_models(client, alice, entry(NANO, default=True))

    assert client.get("/api/settings/models", headers=alice).json()["warning"] is None


@pytest.mark.parametrize(
    "warning", [{"unit": "euro", "amount": 5}, {"unit": "usd", "amount": 0}, {"unit": "usd"}]
)
def test_an_invalid_threshold_is_refused(client, alice, fake_llm, warning):
    save_key(client, alice)
    response = client.put(
        "/api/settings/models",
        headers=alice,
        json={"models": [], "temperature": None, "warning": warning},
    )
    assert response.status_code == 422


def test_a_dollar_threshold_sends_one_notice(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    set_warning(client, alice, "usd", "0.0001")
    fake_llm.queue(text_chunks("Hi") + [usage_chunk(1000, 200)])

    response = chat(client, alice, "hello")

    [notice] = notices(response)
    assert notice["kind"] == "usage_warning"
    assert (notice["unit"], notice["amount"]) == ("usd", 0.0001)
    assert parse_events(response.text)[-1][0] == "done"
    report = client.get("/api/usage", headers=alice).json()
    assert report["warning"] == {"unit": "usd", "amount": 0.0001, "reached": True}


def test_a_token_threshold_compares_tokens(client, alice, fake_llm):
    ready_user(client, alice, entry(UNPRICED, default=True))
    set_warning(client, alice, "tokens", 100, entry(UNPRICED, default=True))
    fake_llm.queue(text_chunks("Hi") + [usage_chunk(60, 30)], text_chunks("Hi") + [usage_chunk(60, 30)])

    first = chat(client, alice, "hello")
    conversation_id = [d for n, d in parse_events(first.text) if n == "conversation"][0]["id"]
    second = chat(client, alice, "again", conversation_id)

    assert notices(first) == []
    [notice] = notices(second)
    assert (notice["unit"], notice["amount"], notice["month_tokens"]) == ("tokens", 100, 180)


def test_the_notice_is_not_repeated_in_the_same_month(client, alice, fake_llm):
    ready_user(client, alice)
    set_warning(client, alice, "tokens", 10)
    fake_llm.queue(text_chunks("Hi") + [usage_chunk()], text_chunks("Hi") + [usage_chunk()])

    first = chat(client, alice, "hello")
    conversation_id = [d for n, d in parse_events(first.text) if n == "conversation"][0]["id"]
    second = chat(client, alice, "again", conversation_id)

    assert len(notices(first)) == 1
    assert notices(second) == []


def test_the_notice_comes_again_in_the_next_month(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    set_warning(client, alice, "tokens", 10)
    fake_llm.queue(text_chunks("Hi") + [usage_chunk()], text_chunks("Hi") + [usage_chunk()])
    first = chat(client, alice, "hello")
    conversation_id = [d for n, d in parse_events(first.text) if n == "conversation"][0]["id"]

    async def last_month(session):
        await session.execute(update(UserSettings).values(warning_notified_month="2000-01"))
        await session.commit()

    run_db(test_database_url, last_month)
    second = chat(client, alice, "again", conversation_id)

    assert len(notices(second)) == 1


def test_no_threshold_sends_no_notice(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi") + [usage_chunk(10**6, 10**6)])

    assert notices(chat(client, alice, "hello")) == []


# --- 9.5 streamed usage per provider ---


def chunks_of(*raw):
    async def gen():
        for item in raw:
            yield ChatCompletionChunk.model_validate(item)

    return gen()


async def drain(chunks, state, stream_usage):
    return [event async for event in read_round(chunks, state, stream_usage)]


def with_usage(chunk: dict, prompt: int, completion_tokens: int) -> dict:
    return {
        **chunk,
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt + completion_tokens,
        },
    }


@pytest.mark.asyncio
async def test_a_final_usage_chunk_is_read():
    state = RoundState()
    await drain(chunks_of(*text_chunks("Hi"), usage_chunk(40, 4)), state, "final_chunk")
    assert (state.prompt_tokens, state.completion_tokens) == (40, 4)


@pytest.mark.asyncio
async def test_incremental_usage_keeps_the_last_report():
    state = RoundState()
    await drain(
        chunks_of(
            with_usage(_chunk({"content": "Hel"}), 40, 1),
            with_usage(_chunk({"content": "lo"}), 40, 2),
            with_usage(_chunk({}, finish_reason="stop"), 40, 3),
        ),
        state,
        "incremental",
    )
    assert (state.prompt_tokens, state.completion_tokens) == (40, 3)
    assert state.answer == "Hello"


@pytest.mark.asyncio
async def test_a_provider_with_no_usage_is_not_read():
    state = RoundState()
    await drain(chunks_of(*text_chunks("Hi"), usage_chunk(40, 4)), state, "none")
    assert state.prompt_tokens is None


def test_a_provider_with_no_usage_records_the_cost_as_unknown(
    client, alice, fake_llm, test_database_url
):
    save_key(client, alice, provider="local", key="any-local-key")
    assert save_models(client, alice, entry(NANO, provider_id="local", default=True)).status_code == 200
    fake_llm.queue(text_chunks("Hi"))

    response = chat(client, alice, "hello")

    assert response.status_code == 200
    assert "stream_options" not in fake_llm.chat_requests[0]
    [row] = usage_rows(test_database_url)
    assert (row.provider_id, row.model) == ("local", NANO)
    assert (row.prompt_tokens, row.completion_tokens, row.cost_usd) == (None, None, None)
    report = client.get("/api/usage", headers=alice).json()
    assert report["month"]["unknown_cost_calls"] == 1
