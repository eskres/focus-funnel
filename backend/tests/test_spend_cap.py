"""The monthly spend cap: its state and its API (stop-and-spend-cap tasks 1.2 and 1.3)."""

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.chat import usage
from app.chat.config import load_chat_config
from app.chat.loadout import temperature_for
from app.chat.usage import cap_state, month_start
from app.db import create_engine
from app.main import app
from app.models import UsageEvent, User, UserSettings
from app.routers import usage as usage_router
from app.user_data import delete_user_data
from tests.chat_helpers import (
    chat,
    entry,
    error_code,
    ready_user,
    run_db,
    text_chunks,
    usage_chunk,
    user_id_for,
)
from tests.sse_helpers import parse_events
from tests.test_demo import bearer, demo_env, fake, start  # noqa: F401 (fixtures)


def add_usage(url: str, user_id: str, *rows, conversation_id: str | None = None):
    """rows: (kind, prompt, completion, cost or None) or with a created_at fifth."""

    async def work(session):
        now = datetime.now(UTC)
        for row in rows:
            kind, prompt, completion, cost = row[:4]
            created_at = row[4] if len(row) > 4 else now
            session.add(
                UsageEvent(
                    user_id=uuid.UUID(user_id),
                    conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
                    kind=kind,
                    provider_id="nebius",
                    model="vendor/nano-model",
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    cost_usd=None if cost is None else Decimal(cost),
                    created_at=created_at,
                )
            )
        await session.commit()

    run_db(url, work)


def store_cap(url: str, user_id: str, unit: str | None, amount):
    """Write the cap columns directly, creating the settings row when needed."""

    async def work(session):
        row = await session.get(UserSettings, uuid.UUID(user_id))
        if row is None:
            row = UserSettings(user_id=uuid.UUID(user_id))
            session.add(row)
        row.cap_unit = unit
        row.cap_amount = None if amount is None else Decimal(str(amount))
        await session.commit()

    run_db(url, work)


def state_of(url: str, user_id: str):
    async def work(session):
        return await cap_state(session, uuid.UUID(user_id))

    return run_db(url, work)


def settings_row(url: str, user_id: str) -> UserSettings | None:
    async def work(session):
        return await session.get(UserSettings, uuid.UUID(user_id))

    return run_db(url, work)


def settings_rows(url: str) -> int:
    async def work(session):
        return (await session.execute(select(func.count()).select_from(UserSettings))).scalar_one()

    return run_db(url, work)


# --- 1.2 cap_state ---


def test_no_cap_gives_none(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    add_usage(test_database_url, user_id, ("chat", 100, 10, "1"))

    assert state_of(test_database_url, user_id) is None
    store_cap(test_database_url, user_id, None, None)
    assert state_of(test_database_url, user_id) is None


def test_a_dollar_cap_sums_known_costs_only(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    store_cap(test_database_url, user_id, "usd", 5)
    add_usage(
        test_database_url,
        user_id,
        ("chat", 100, 10, "1.25"),
        ("chat", 100, 10, "0.5"),
        ("chat", None, None, None),
    )

    state = state_of(test_database_url, user_id)

    assert (state.unit, state.amount, state.used, state.reached) == ("usd", Decimal(5), Decimal("1.75"), False)


def test_a_token_cap_sums_known_tokens_only(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    store_cap(test_database_url, user_id, "tokens", 1000)
    add_usage(
        test_database_url,
        user_id,
        ("chat", 100, 10, "1.25"),
        ("chat", 200, 20, "0.5"),
        ("chat", None, None, None),
    )

    state = state_of(test_database_url, user_id)

    assert (state.unit, state.used, state.reached) == ("tokens", Decimal(330), False)


def test_known_tokens_with_unknown_cost_count_only_under_a_token_cap(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    add_usage(test_database_url, user_id, ("chat", 300, 30, None))

    store_cap(test_database_url, user_id, "tokens", 1000)
    assert state_of(test_database_url, user_id).used == Decimal(330)
    store_cap(test_database_url, user_id, "usd", 1)
    assert state_of(test_database_url, user_id).used == Decimal(0)


@pytest.mark.parametrize("kind", ["chat", "embed", "test", "compact", "proposal"])
def test_every_kind_counts(client, alice, test_database_url, kind):
    user_id = user_id_for(client, alice)
    add_usage(test_database_url, user_id, (kind, 40, 2, "0.75"))

    store_cap(test_database_url, user_id, "usd", 5)
    assert state_of(test_database_url, user_id).used == Decimal("0.75")
    store_cap(test_database_url, user_id, "tokens", 5)
    assert state_of(test_database_url, user_id).used == Decimal(42)


def test_last_month_and_other_users_do_not_count(client, alice, bob, test_database_url):
    user_id = user_id_for(client, alice)
    other = user_id_for(client, bob)
    last_month = month_start(datetime.now(UTC)) - timedelta(seconds=1)
    add_usage(test_database_url, user_id, ("chat", 100, 10, "3", last_month), ("chat", 1, 1, "0.25"))
    add_usage(test_database_url, other, ("chat", 100, 10, "3"))

    store_cap(test_database_url, user_id, "usd", 5)
    assert state_of(test_database_url, user_id).used == Decimal("0.25")
    store_cap(test_database_url, user_id, "tokens", 5)
    assert state_of(test_database_url, user_id).used == Decimal(2)


def test_a_deleted_conversations_usage_still_counts(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi") + [usage_chunk(1000, 200)])
    response = chat(client, alice, "hello")
    conversation_id = next(d for n, d in parse_events(response.text) if n == "conversation")["id"]
    user_id = user_id_for(client, alice)
    store_cap(test_database_url, user_id, "tokens", 1200)
    assert state_of(test_database_url, user_id).reached

    assert client.delete(f"/api/conversations/{conversation_id}", headers=alice).status_code == 204

    async def rows(session):
        return list((await session.execute(select(UsageEvent.conversation_id))).scalars())

    assert run_db(test_database_url, rows) == [None]
    state = state_of(test_database_url, user_id)
    assert (state.used, state.reached) == (Decimal(1200), True)


def test_deleting_the_usage_history_counts_from_zero(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    store_cap(test_database_url, user_id, "usd", 5)
    add_usage(test_database_url, user_id, ("chat", 100, 10, "6"))
    assert state_of(test_database_url, user_id).reached

    assert client.delete("/api/me/usage", headers=alice).status_code == 204

    state = state_of(test_database_url, user_id)
    assert (state.used, state.reached) == (Decimal(0), False)


@pytest.mark.parametrize(
    "unit, amount, used, reached",
    [
        ("usd", 5, "5.00", True),
        ("usd", 5, "4.99", False),
        ("tokens", 1000, 1000, True),
        ("tokens", 1000, 999, False),
    ],
)
def test_reached_at_exactly_the_cap(client, alice, test_database_url, unit, amount, used, reached):
    user_id = user_id_for(client, alice)
    store_cap(test_database_url, user_id, unit, amount)
    if unit == "usd":
        add_usage(test_database_url, user_id, ("chat", 1, 1, used))
    else:
        add_usage(test_database_url, user_id, ("chat", used - 1, 1, None))

    assert state_of(test_database_url, user_id).reached is reached


def test_the_cap_is_read_fresh_in_a_session_that_holds_the_row(client, alice, test_database_url):
    user_id = uuid.UUID(user_id_for(client, alice))
    store_cap(test_database_url, str(user_id), None, None)
    add_usage(test_database_url, str(user_id), ("chat", 100, 10, "3"))
    asyncio.run(read_fresh(test_database_url, user_id))


async def read_fresh(test_database_url: str, user_id: uuid.UUID):
    config = load_chat_config()
    engine = create_engine(test_database_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def save(unit, amount):
        async with sessions() as other:
            await other.execute(
                update(UserSettings)
                .where(UserSettings.user_id == user_id)
                .values(cap_unit=unit, cap_amount=amount)
            )
            await other.commit()

    try:
        async with sessions() as session:
            user = await session.get(User, user_id)
            await temperature_for(session, user, config)
            held = await session.get(UserSettings, user_id)
            assert held is not None and held.cap_unit is None
            assert await cap_state(session, user_id) is None

            await save("usd", Decimal(2))
            state = await cap_state(session, user_id)
            assert (state.unit, state.amount, state.reached) == ("usd", Decimal(2), True)

            await save("usd", Decimal("2.5"))
            state = await cap_state(session, user_id)
            assert (state.amount, state.reached) == (Decimal("2.5"), True)

            await save("usd", Decimal(10))
            assert (await cap_state(session, user_id)).reached is False

            await save(None, None)
            assert await cap_state(session, user_id) is None
    finally:
        await engine.dispose()


# --- 1.3 PUT /api/usage/cap and the report ---


def put_cap(client, headers, cap):
    return client.put("/api/usage/cap", headers=headers, json={"cap": cap})


def test_a_dollar_cap_is_saved_and_returned(client, alice):
    response = put_cap(client, alice, {"unit": "usd", "amount": 5})

    assert response.status_code == 200, response.text
    cap = response.json()["cap"]
    assert (cap["unit"], cap["amount"], cap["reached"]) == ("usd", 5.0, False)
    assert client.get("/api/usage", headers=alice).json()["cap"] == cap


def test_a_token_cap_is_saved_and_returned(client, alice):
    response = put_cap(client, alice, {"unit": "tokens", "amount": 2000000})

    cap = response.json()["cap"]
    assert (cap["unit"], cap["amount"], cap["reached"]) == ("tokens", 2000000, False)
    assert client.get("/api/usage", headers=alice).json()["cap"] == cap


def test_a_whole_token_cap_written_with_decimals_is_saved(client, alice):
    response = put_cap(client, alice, {"unit": "tokens", "amount": "1500.000"})

    assert response.status_code == 200, response.text
    assert response.json()["cap"]["amount"] == 1500


def test_a_null_cap_clears_it(client, alice, test_database_url):
    put_cap(client, alice, {"unit": "usd", "amount": 5})

    response = put_cap(client, alice, None)

    assert response.status_code == 200
    assert response.json() == {"cap": None}
    assert client.get("/api/usage", headers=alice).json()["cap"] is None
    row = settings_row(test_database_url, user_id_for(client, alice))
    assert (row.cap_unit, row.cap_amount) == (None, None)


@pytest.mark.parametrize(
    "cap",
    [
        {"unit": "usd", "amount": 0},
        {"unit": "usd", "amount": -1},
        {"unit": "usd", "amount": "1.1234567"},
        {"unit": "tokens", "amount": 0.0000001},
        # Tokens are whole (design decision 31).
        {"unit": "tokens", "amount": 0.5},
        {"unit": "tokens", "amount": "1500.5"},
        {"unit": "eur", "amount": 5},
    ],
)
def test_an_invalid_cap_is_refused_and_the_saved_cap_stays(client, alice, cap):
    put_cap(client, alice, {"unit": "usd", "amount": 5})

    response = put_cap(client, alice, cap)

    assert response.status_code == 422
    assert error_code(response) == "validation_error"
    saved = client.get("/api/usage", headers=alice).json()["cap"]
    assert (saved["unit"], saved["amount"]) == ("usd", 5.0)


def test_reached_follows_the_months_usage(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    put_cap(client, alice, {"unit": "usd", "amount": 5})
    add_usage(test_database_url, user_id, ("chat", 100, 10, "4.99"))
    assert client.get("/api/usage", headers=alice).json()["cap"]["reached"] is False

    add_usage(test_database_url, user_id, ("chat", 1, 1, "0.01"))
    assert client.get("/api/usage", headers=alice).json()["cap"]["reached"] is True
    assert put_cap(client, alice, {"unit": "usd", "amount": 6}).json()["cap"]["reached"] is False


@pytest.mark.parametrize(
    "now, resets_on",
    [
        (datetime(2026, 11, 30, 23, 59, tzinfo=UTC), "2026-12-01"),
        (datetime(2026, 12, 31, 23, 59, tzinfo=UTC), "2027-01-01"),
    ],
)
def test_the_cap_resets_on_the_first_of_next_month(client, alice, monkeypatch, now, resets_on):
    monkeypatch.setattr(usage, "utc_now", lambda: now)
    monkeypatch.setattr(usage_router, "utc_now", lambda: now)

    saved = put_cap(client, alice, {"unit": "usd", "amount": 5}).json()["cap"]
    reported = client.get("/api/usage", headers=alice).json()["cap"]

    assert saved["resets_on"] == resets_on
    assert reported["resets_on"] == resets_on
    assert date.fromisoformat(resets_on).day == 1


def test_a_first_cap_creates_the_settings_row_with_nothing_else(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    assert settings_row(test_database_url, user_id) is None

    response = put_cap(client, alice, {"unit": "usd", "amount": 5})

    assert response.status_code == 200
    assert response.json()["cap"]["amount"] == 5.0
    row = settings_row(test_database_url, user_id)
    assert (row.cap_unit, row.cap_amount) == ("usd", Decimal(5))
    assert (row.temperature, row.warning_unit, row.warning_amount, row.warning_notified_month) == (
        None,
        None,
        None,
        None,
    )
    cap = client.get("/api/usage", headers=alice).json()["cap"]
    assert (cap["unit"], cap["amount"]) == ("usd", 5.0)


def test_no_cap_without_a_row_creates_nothing(client, alice, test_database_url):
    user_id_for(client, alice)

    response = put_cap(client, alice, None)

    assert response.status_code == 200
    assert response.json() == {"cap": None}
    assert settings_rows(test_database_url) == 0


def test_another_users_cap_is_not_shown(client, alice, bob):
    put_cap(client, alice, {"unit": "usd", "amount": 5})

    assert client.get("/api/usage", headers=bob).json()["cap"] is None


def test_saving_model_settings_leaves_the_cap(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    put_cap(client, alice, {"unit": "usd", "amount": 5})

    response = client.put(
        "/api/settings/models",
        headers=alice,
        json={
            "models": [entry(default=True)],
            "temperature": 0.3,
            "warning": {"unit": "tokens", "amount": 1000},
        },
    )

    assert response.status_code == 200, response.text
    row = settings_row(test_database_url, user_id_for(client, alice))
    assert (row.temperature, row.warning_unit, row.warning_amount) == (0.3, "tokens", Decimal(1000))
    assert (row.cap_unit, row.cap_amount) == ("usd", Decimal(5))


def test_saving_the_cap_leaves_the_other_settings(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    response = client.put(
        "/api/settings/models",
        headers=alice,
        json={
            "models": [entry(default=True)],
            "temperature": 0.3,
            "warning": {"unit": "usd", "amount": 3},
        },
    )
    assert response.status_code == 200, response.text
    user_id = user_id_for(client, alice)

    async def notified(session):
        await session.execute(
            update(UserSettings)
            .where(UserSettings.user_id == uuid.UUID(user_id))
            .values(warning_notified_month="2026-11")
        )
        await session.commit()

    run_db(test_database_url, notified)

    put_cap(client, alice, {"unit": "usd", "amount": 5})
    put_cap(client, alice, None)
    put_cap(client, alice, {"unit": "tokens", "amount": 10})

    row = settings_row(test_database_url, user_id)
    assert (row.temperature, row.warning_unit, row.warning_amount, row.warning_notified_month) == (
        0.3,
        "usd",
        Decimal(3),
        "2026-11",
    )
    assert (row.cap_unit, row.cap_amount) == ("tokens", Decimal(10))


@pytest.fixture
def demo_client(demo_env, test_database_url, fake):  # noqa: F811 (fixtures)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_deleting_a_demo_users_data_leaves_no_settings_row(demo_client, test_database_url):
    visitor = bearer(start(demo_client)["session"])
    response = put_cap(demo_client, visitor, {"unit": "usd", "amount": 5})
    assert response.status_code == 200, response.text
    user_id = uuid.UUID(demo_client.get("/api/me", headers=visitor).json()["id"])
    assert settings_rows(test_database_url) == 1

    async def delete(session):
        user = await session.get(User, user_id)
        await delete_user_data(session, user)

    run_db(test_database_url, delete)

    assert settings_rows(test_database_url) == 0
