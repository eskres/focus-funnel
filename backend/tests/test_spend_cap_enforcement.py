"""The spend cap refuses new turns and ends a running one (stop-and-spend-cap
tasks 2.1 and 2.2, the SQLite part; tests/test_spend_cap_postgres.py has
the rounds that search, propose, and embed)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.chat import usage
from app.models import Conversation, Message, UsageEvent
from tests import test_thought_status_turn as status_turn
from tests.chat_helpers import (
    NANO,
    UNPRICED,
    chat,
    entry,
    error_code,
    part,
    ready_user,
    run_db,
    seed_conversation,
    seed_proposal,
    text_chunks,
    usage_chunk,
    user_id_for,
)
from tests.sse_helpers import parse_events
from tests.test_spend_cap import add_usage
from tests.test_thought_status_offer import EARLIER, confirmed_mark
from tests.test_thought_status_turn import plumber

TEN = tuple(f"message {n}" for n in range(10))


def put_cap(client, headers, unit="usd", amount=5):
    cap = None if unit is None else {"unit": unit, "amount": amount}
    response = client.put("/api/usage/cap", headers=headers, json={"cap": cap})
    assert response.status_code == 200, response.text
    return response.json()


def at_cap(client, headers, url, cost="5.12", unit="usd", amount=5, **row) -> str:
    """A ready user whose month reached the cap; returns the user id."""
    ready_user(client, headers)
    user_id = user_id_for(client, headers)
    put_cap(client, headers, unit, amount)
    add_usage(url, user_id, ("chat", row.get("prompt", 100), row.get("completion", 10), cost))
    return user_id


def seeded(url, client, headers, messages=TEN, model=NANO) -> str:
    return seed_conversation(
        url, client, headers, messages=messages, provider_id="nebius", model=model
    )


def usage_count(url) -> int:
    async def work(session):
        return (await session.execute(select(func.count()).select_from(UsageEvent))).scalar_one()

    return run_db(url, work)


def conversation_row(url, conversation_id) -> Conversation:
    return run_db(url, lambda session: session.get(Conversation, uuid.UUID(conversation_id)))


def messages_of(url, conversation_id) -> list[tuple]:
    async def work(session):
        rows = await session.execute(
            select(Message)
            .where(Message.conversation_id == uuid.UUID(conversation_id))
            .order_by(Message.position)
        )
        return [
            (m.position, m.role, m.content, m.status, m.error_code, m.compacted)
            for m in rows.scalars()
        ]

    return run_db(url, work)


def conversations_of(client, headers) -> list[dict]:
    return client.get("/api/conversations", headers=headers).json()["conversations"]


def names(response) -> list[str]:
    return [name for name, _ in parse_events(response.text)]


def events_of(response, name) -> list[dict]:
    return [data for event, data in parse_events(response.text) if event == name]


def assert_refused_at_cap(response, cap_text="$5.00"):
    assert response.status_code == 409, response.text
    assert error_code(response) == "spend_cap_reached"
    message = response.json()["error"]["message"]
    assert cap_text in message
    assert "Settings" in message
    return message


# --- 2.1 the check before a turn ---


@pytest.mark.parametrize("text", ["hello again", "/push oat milk", "/pull milk", "/explore maps"])
def test_a_message_at_the_cap_is_refused_and_kept(
    client, alice, fake_llm, test_database_url, text
):
    at_cap(client, alice, test_database_url)
    conversation_id = seeded(test_database_url, client, alice)
    rows_before = usage_count(test_database_url)

    response = chat(client, alice, text, conversation_id)

    message = assert_refused_at_cap(response)
    assert message == (
        "Your monthly spend cap of $5.00 is reached (this month so far: $5.12, estimated). "
        "Raise or remove it in Settings to keep chatting. It resets on "
        f"{usage.next_month_start(datetime.now(UTC)).day} "
        f"{usage.next_month_start(datetime.now(UTC)).strftime('%B')} (UTC)."
    )
    assert response.headers["X-Conversation-Id"] == conversation_id
    assert fake_llm.chat_requests == []
    assert usage_count(test_database_url) == rows_before
    assert conversation_row(test_database_url, conversation_id).turn_started_at is None
    stored = messages_of(test_database_url, conversation_id)
    assert len(stored) == len(TEN) + 1
    assert stored[-1][1:3] == ("user", text)


def test_compact_at_the_cap_is_refused_and_changes_nothing(
    client, alice, fake_llm, test_database_url
):
    at_cap(client, alice, test_database_url)
    conversation_id = seeded(test_database_url, client, alice)
    before = messages_of(test_database_url, conversation_id)
    rows_before = usage_count(test_database_url)

    response = chat(client, alice, "/compact", conversation_id)

    assert_refused_at_cap(response)
    assert "X-Conversation-Id" not in response.headers
    assert fake_llm.chat_requests == []
    assert usage_count(test_database_url) == rows_before
    # No message, no summary, nothing compacted.
    assert messages_of(test_database_url, conversation_id) == before
    assert conversation_row(test_database_url, conversation_id).turn_started_at is None


def test_the_first_message_of_a_new_conversation_is_kept_and_answered_there_later(
    client, alice, fake_llm, test_database_url
):
    at_cap(client, alice, test_database_url)

    response = chat(client, alice, "a new idea")

    assert_refused_at_cap(response)
    conversation_id = response.headers["X-Conversation-Id"]
    [listed] = conversations_of(client, alice)
    assert listed["id"] == conversation_id
    assert [m[1:3] for m in messages_of(test_database_url, conversation_id)] == [
        ("user", "a new idea")
    ]
    assert conversation_row(test_database_url, conversation_id).turn_started_at is None
    assert fake_llm.chat_requests == []

    put_cap(client, alice, "usd", 10)
    fake_llm.queue(text_chunks("Tell me more.") + [usage_chunk()])
    again = chat(client, alice, "a new idea", conversation_id)

    assert names(again)[-1] == "done"
    assert [m[1:3] for m in messages_of(test_database_url, conversation_id)] == [
        ("user", "a new idea"),
        ("assistant", "Tell me more."),
    ]
    assert [c["id"] for c in conversations_of(client, alice)] == [conversation_id]


def test_a_model_with_no_listed_price_is_refused_too(client, alice, fake_llm, test_database_url):
    at_cap(client, alice, test_database_url)
    conversation_id = seeded(test_database_url, client, alice, model=UNPRICED)

    response = chat(client, alice, "hello again", conversation_id)

    assert_refused_at_cap(response)
    assert fake_llm.chat_requests == []


def test_after_raising_the_cap_the_same_text_is_answered_once(
    client, alice, fake_llm, test_database_url
):
    at_cap(client, alice, test_database_url)
    conversation_id = seeded(test_database_url, client, alice)
    assert chat(client, alice, "hello again", conversation_id).status_code == 409

    put_cap(client, alice, "usd", "5.50")
    fake_llm.queue(text_chunks("Hi again.") + [usage_chunk()])
    response = chat(client, alice, "hello again", conversation_id)

    assert names(response)[-1] == "done"
    stored = messages_of(test_database_url, conversation_id)
    assert [m[1:3] for m in stored[len(TEN):]] == [("user", "hello again"), ("assistant", "Hi again.")]


def test_after_removing_the_cap_a_message_is_answered(client, alice, fake_llm, test_database_url):
    at_cap(client, alice, test_database_url)
    conversation_id = seeded(test_database_url, client, alice)

    assert put_cap(client, alice, None) == {"cap": None}
    fake_llm.queue(text_chunks("Hi again."))
    response = chat(client, alice, "hello again", conversation_id)

    assert names(response)[-1] == "done"


def test_a_new_month_answers_again(client, alice, fake_llm, test_database_url, monkeypatch):
    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    put_cap(client, alice, "usd", 5)
    november = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    add_usage(test_database_url, user_id, ("chat", 100, 10, "6", november))
    monkeypatch.setattr(usage, "utc_now", lambda: datetime(2026, 11, 30, 23, 59, tzinfo=UTC))
    conversation_id = seeded(test_database_url, client, alice)
    assert chat(client, alice, "hello again", conversation_id).status_code == 409

    monkeypatch.setattr(usage, "utc_now", lambda: datetime(2026, 12, 1, 0, 0, tzinfo=UTC))
    fake_llm.queue(text_chunks("Hi again."))
    response = chat(client, alice, "hello again", conversation_id)

    assert names(response)[-1] == "done"


def test_in_december_the_cap_resets_on_1_january(
    client, alice, fake_llm, test_database_url, monkeypatch
):
    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    put_cap(client, alice, "usd", 5)
    add_usage(test_database_url, user_id, ("chat", 100, 10, "6", datetime(2026, 12, 10, tzinfo=UTC)))
    monkeypatch.setattr(usage, "utc_now", lambda: datetime(2026, 12, 15, 12, 0, tzinfo=UTC))
    conversation_id = seeded(test_database_url, client, alice)

    response = chat(client, alice, "hello again", conversation_id)

    message = assert_refused_at_cap(response)
    assert message.endswith("It resets on 1 January (UTC).")
    assert "(this month so far: $6.00, estimated)" in message


def test_a_token_cap_compares_tokens_and_names_them(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    put_cap(client, alice, "tokens", 2_000_000)
    # A lot of dollars, few tokens: the token cap is not reached.
    add_usage(test_database_url, user_id, ("chat", 1_000, 500, "900"))
    conversation_id = seeded(test_database_url, client, alice)
    fake_llm.queue(text_chunks("Hi again."))
    assert names(chat(client, alice, "hello again", conversation_id))[-1] == "done"

    add_usage(test_database_url, user_id, ("chat", 1_900_000, 98_500, "0.01"))
    response = chat(client, alice, "one more", conversation_id)

    message = assert_refused_at_cap(response, "2,000,000 tokens")
    assert "$" not in message
    assert "(this month so far: 2,000,000 tokens)" in message
    assert len(fake_llm.chat_requests) == 1


def test_a_warning_below_the_cap_is_sent_once_and_the_message_answered(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    response = client.put(
        "/api/settings/models",
        headers=alice,
        json={
            "models": [entry(NANO, default=True)],
            "temperature": None,
            "warning": {"unit": "usd", "amount": 3},
        },
    )
    assert response.status_code == 200, response.text
    put_cap(client, alice, "usd", 5)
    add_usage(test_database_url, user_id, ("chat", 100, 10, "3.50"))
    conversation_id = seeded(test_database_url, client, alice)
    fake_llm.queue(text_chunks("Hi again.") + [usage_chunk()])

    response = chat(client, alice, "hello again", conversation_id)

    assert names(response)[-1] == "done"
    warnings = [e for e in events_of(response, "notice") if e["kind"] == "usage_warning"]
    assert len(warnings) == 1
    assert warnings[0]["amount"] == 3.0


# --- 2.2 the check between rounds: the final round ---


def test_a_final_round_that_reaches_the_cap_is_complete_and_the_next_message_refused(
    client, alice, fake_llm, test_database_url
):
    # 100 prompt and 20 completion tokens of NANO cost $0.0000108.
    at_cap(client, alice, test_database_url, cost="4.99999")
    conversation_id = seeded(test_database_url, client, alice)
    fake_llm.queue(text_chunks("Here you go.") + [usage_chunk(100, 20)])

    response = chat(client, alice, "hello again", conversation_id)

    assert names(response)[-1] == "done"
    stored = messages_of(test_database_url, conversation_id)
    assert stored[-1][1:5] == ("assistant", "Here you go.", "complete", None)

    refused = chat(client, alice, "and then?", conversation_id)
    assert_refused_at_cap(refused)
    assert len(fake_llm.chat_requests) == 1


# --- 2.3 the offer asks no model at the cap ---

# The thought-status fixtures: a FakeLLM with an embedding model, and a ready alice.
fake = status_turn.fake
alice_id = status_turn.alice_id


def offer(client, headers, conversation_id):
    return client.post(f"/api/conversations/{conversation_id}/proposal", headers=headers)


def archive(client, headers, conversation_id):
    return client.patch(
        f"/api/conversations/{conversation_id}", headers=headers, json={"archived": True}
    )


def cap_reached(client, headers, url, user_id):
    put_cap(client, headers, "usd", 5)
    add_usage(url, user_id, ("chat", 100, 10, "5.12"))


def test_the_offer_asks_no_model_at_the_cap_and_archive_goes_ahead(
    client, alice, test_database_url, fake, alice_id
):
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        messages=("I need oat milk", "Ready to confirm.", "and a podcast about maps?", "Nice."),
    )
    # The oat milk was filed; the podcast was said since.
    seed_proposal(
        test_database_url,
        conversation_id,
        [part(title="Buy oat milk", thought_id=str(uuid.uuid4()))],
        position=1,
        hold=False,
    )
    cap_reached(client, alice, test_database_url, alice_id)

    response = offer(client, alice, conversation_id)

    assert response.status_code == 200, response.text
    assert response.json() == {"proposal": None}
    assert fake.chat_requests == []
    assert archive(client, alice, conversation_id).status_code == 200
    assert conversation_row(test_database_url, conversation_id).archived_at is not None
    assert conversation_row(test_database_url, conversation_id).turn_started_at is None


def test_the_offer_after_only_a_status_card_asks_no_model_at_the_cap(
    client, alice, test_database_url, fake, alice_id
):
    task = plumber(test_database_url, alice_id)
    conversation_id = seed_conversation(
        test_database_url,
        client,
        alice,
        messages=(*EARLIER, "I called the plumber", "Ready to confirm."),
    )
    seed_proposal(
        test_database_url,
        conversation_id,
        [confirmed_mark(task)],
        position=7,
        from_position=6,
        to_position=6,
        hold=False,
    )
    cap_reached(client, alice, test_database_url, alice_id)

    assert offer(client, alice, conversation_id).json() == {"proposal": None}
    assert fake.chat_requests == []
    assert archive(client, alice, conversation_id).status_code == 200


def test_a_held_proposal_is_still_offered_at_the_cap(
    client, alice, test_database_url, fake, alice_id
):
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=("I need oat milk", "Want to keep it?")
    )
    proposal_id = seed_proposal(test_database_url, conversation_id, [part()], position=1)
    cap_reached(client, alice, test_database_url, alice_id)

    response = offer(client, alice, conversation_id)

    assert response.status_code == 200, response.text
    offered = response.json()["proposal"]
    assert offered["id"] == proposal_id
    assert offered["parts"][0]["title"] == "Oat milk"
    assert fake.chat_requests == []
    assert archive(client, alice, conversation_id).status_code == 200
