"""Deletes stop the user's running answers first (stop-and-spend-cap task
3.5, design decision 13).

A delete stops the turns it would remove, waits for them within a bound,
and then claims the conversations in its own transaction. A turn still
running after the bound, or a message still being opened, makes the delete
answer 409 and delete nothing; the user tries again.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx2
from sqlalchemy import func, select

from app.chat import running
from app.chat.prompt import estimate_text_tokens
from app.chat.usage import cap_state
from app.demo import delete_expired_demo_users
from app.models import Conversation, Thought, UsageEvent, User
from tests.chat_helpers import Hold, _SseStream, text_chunks, turns_settled, usage_chunk
from tests.stop_helpers import STOPPED, adding, the_turn
from tests import test_background_turns as background_turns
from tests.test_background_turns import DEMO_KEY, every_stored_value, messages_of, watch_chat
from tests.test_user_data import counts

# A demo visitor whose key is only in X-Provider-Keys.
demo_api = background_turns.demo_api

DELETE_BUSY = "An answer in this conversation is still running. Try deleting again in a moment."
TURNS_BUSY = "An answer is still running. Try again in a moment."


async def held(api, message: str = "hello"):
    """A turn in a new conversation whose stream waits after "Hello "."""
    hold = Hold()
    api.fake.queue(text_chunks("Hello ")[:-1] + [hold] + text_chunks("there.") + [usage_chunk()])
    watcher = await watch_chat(api, message)
    await asyncio.wait_for(hold.reached.wait(), 5)
    turn = the_turn()
    return watcher, turn, str(turn.conversation_id)


async def usage_rows(api) -> list[UsageEvent]:
    async def work(session):
        return list((await session.execute(select(UsageEvent))).scalars())

    return await api.db(work)


async def owned_counts(api, user_id: uuid.UUID) -> dict[str, int]:
    async def work(session):
        return {
            **await counts(session, user_id),
            "users": (
                await session.execute(select(func.count()).select_from(User).where(User.id == user_id))
            ).scalar_one(),
        }

    return await api.db(work)


async def add_thought(api, user_id: uuid.UUID) -> None:
    async def work(session):
        session.add(Thought(user_id=user_id, title="Oat milk", summary="Buy oat milk.", tags=["food"]))
        await session.commit()

    await api.db(work)


async def answered(api) -> None:
    """One message answered, so the user has a usage row from before."""
    api.fake.queue(text_chunks("Hi!") + [usage_chunk()])
    response = await asyncio.create_task(api.chat("hi"))
    assert response.status_code == 200, response.text


async def put_token_cap(api) -> None:
    response = await api.http.put(
        "/api/usage/cap",
        headers=api.headers,
        json={"cap": {"unit": "tokens", "amount": 1_000_000}},
    )
    assert response.status_code == 200, response.text


def no_integrity_error(caplog) -> None:
    assert "IntegrityError" not in caplog.text
    assert "ForeignKeyViolation" not in caplog.text
    assert "FOREIGN KEY constraint failed" not in caplog.text


def assert_busy(response, message: str) -> None:
    assert response.status_code == 409, response.text
    assert response.json() == {"error": {"code": "conversation_busy", "message": message}}


# --- a delete stops the turn, then deletes ---


async def check_delete_keeps_the_rounds_usage(api, caplog, path) -> None:
    """`path(conversation_id)` is the delete sent while the turn runs."""
    await api.ready()
    await put_token_cap(api)
    user_id = await api.user_id()

    with caplog.at_level(logging.DEBUG):
        watcher, turn, conversation_id = await held(api)
        response = await api.http.delete(path(conversation_id), headers=api.headers)
        assert response.status_code == 204, response.text
        # Answered once the turn had ended.
        assert turn.ended
        left = await asyncio.wait_for(watcher, 5)
        await asyncio.sleep(0.05)

    assert left.events[-1] == STOPPED
    assert api.fake.streams[0].closed
    assert len(api.fake.chat_requests) == 1
    [row] = await usage_rows(api)
    assert (row.kind, row.conversation_id) == ("chat", None)
    assert row.completion_tokens == estimate_text_tokens("Hello ")
    state = await api.db(lambda session: cap_state(session, user_id))
    assert state.used == row.prompt_tokens + row.completion_tokens
    assert await messages_of(api, conversation_id) == []
    no_integrity_error(caplog)


async def test_deleting_the_conversation_while_its_turn_runs_keeps_the_rounds_usage(
    async_api, caplog
):
    await check_delete_keeps_the_rounds_usage(
        async_api, caplog, lambda conversation_id: f"/api/conversations/{conversation_id}"
    )


async def test_deleting_the_content_while_a_turn_runs_keeps_the_rounds_usage(async_api, caplog):
    await check_delete_keeps_the_rounds_usage(async_api, caplog, lambda _: "/api/me/content")


async def test_deleting_the_account_while_a_turn_runs_leaves_nothing(async_api, caplog):
    api = async_api
    await api.ready()
    user_id = await api.user_id()

    with caplog.at_level(logging.DEBUG):
        watcher, turn, _ = await held(api)
        response = await api.http.delete("/api/me", headers=api.headers)
        assert response.status_code == 204, response.text
        assert turn.ended
        left = await asyncio.wait_for(watcher, 5)
        await asyncio.sleep(0.05)

    assert left.events[-1] == STOPPED
    assert len(api.fake.chat_requests) == 1
    assert set((await owned_counts(api, user_id)).values()) == {0}
    no_integrity_error(caplog)


async def test_ending_the_demo_session_during_a_turn_stops_it_and_leaves_nothing(
    demo_api, caplog
):
    api = demo_api
    user_id = await asyncio.create_task(api.user_id())

    with caplog.at_level(logging.DEBUG):
        watcher, turn, _ = await held(api)
        with_key = len([r for r in api.fake.requests if DEMO_KEY in r.headers.get("Authorization", "")])
        response = await asyncio.create_task(
            api.http.delete("/api/demo/session", headers=api.headers)
        )
        assert response.status_code == 204, response.text
        assert turn.ended
        left = await asyncio.wait_for(watcher, 5)
        await asyncio.sleep(0.05)

    assert left.events[-1] == STOPPED
    after = [r for r in api.fake.requests if DEMO_KEY in r.headers.get("Authorization", "")]
    assert len(after) == with_key
    assert set((await owned_counts(api, user_id)).values()) == {0}
    stored = await every_stored_value(api)
    assert user_id.hex not in stored and str(user_id) not in stored
    no_integrity_error(caplog)


# --- a turn still running after the bound: nothing is deleted ---


async def test_the_demo_cleanup_skips_a_visitor_whose_turn_still_runs(
    demo_api, block_commit, monkeypatch
):
    api = demo_api
    monkeypatch.setattr(running, "STOP_WAIT_SECONDS", 0.2)
    user_id = await asyncio.create_task(api.user_id())
    blocked = block_commit(adding(role="assistant", status="stopped"))
    watcher, turn, _ = await held(api)

    async def expire(session):
        user = await session.get(User, user_id)
        user.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()

    await api.db(expire)

    assert await api.db(delete_expired_demo_users) == 0
    await blocked.reached()
    assert not turn.ended
    assert (await owned_counts(api, user_id))["users"] == 1

    blocked.release.set()
    await asyncio.wait_for(watcher, 5)
    await turns_settled()
    assert await api.db(delete_expired_demo_users) == 1
    assert set((await owned_counts(api, user_id)).values()) == {0}


async def test_a_conversation_delete_after_the_bound_is_refused_and_keeps_it(
    async_api, block_commit, monkeypatch
):
    api = async_api
    await api.ready()
    monkeypatch.setattr(running, "STOP_WAIT_SECONDS", 0.2)
    blocked = block_commit(adding(role="assistant", status="stopped"))
    watcher, turn, conversation_id = await held(api)

    response = await api.http.delete(f"/api/conversations/{conversation_id}", headers=api.headers)

    assert_busy(response, DELETE_BUSY)
    assert blocked.held == 1 and not turn.ended
    blocked.release.set()
    await asyncio.wait_for(watcher, 5)
    await turns_settled()
    detail = await api.http.get(f"/api/conversations/{conversation_id}", headers=api.headers)
    assert detail.status_code == 200
    assert [m["status"] for m in detail.json()["messages"]] == ["complete", "stopped"]


async def test_bulk_deletes_after_the_bound_are_refused_and_keep_everything(
    async_api, block_commit, monkeypatch
):
    api = async_api
    await api.ready()
    user_id = await api.user_id()
    await add_thought(api, user_id)
    await answered(api)
    monkeypatch.setattr(running, "STOP_WAIT_SECONDS", 0.2)
    blocked = block_commit(adding(role="assistant", status="stopped"))
    watcher, turn, _ = await held(api)
    before = await owned_counts(api, user_id)
    kept = ("thoughts", "conversations", "messages", "provider_keys", "user_settings", "usage_events")
    assert all(before[name] for name in kept)

    content = await api.http.delete("/api/me/content", headers=api.headers)
    account = await api.http.delete("/api/me", headers=api.headers)

    assert_busy(content, TURNS_BUSY)
    assert_busy(account, TURNS_BUSY)
    assert blocked.held == 1 and not turn.ended
    after = await owned_counts(api, user_id)
    # The stopped round's usage row was added meanwhile; nothing was deleted.
    assert all(after[name] >= before[name] for name in before)
    blocked.release.set()
    await asyncio.wait_for(watcher, 5)
    await turns_settled()


async def test_ending_a_demo_session_after_the_bound_is_refused_and_keeps_everything(
    demo_api, block_commit, monkeypatch
):
    api = demo_api
    user_id = await asyncio.create_task(api.user_id())
    await add_thought(api, user_id)
    await answered(api)
    monkeypatch.setattr(running, "STOP_WAIT_SECONDS", 0.2)
    blocked = block_commit(adding(role="assistant", status="stopped"))
    watcher, turn, _ = await held(api)
    before = await owned_counts(api, user_id)
    assert all(before[name] for name in ("thoughts", "conversations", "user_settings", "usage_events"))

    response = await asyncio.create_task(api.http.delete("/api/demo/session", headers=api.headers))

    assert_busy(response, TURNS_BUSY)
    assert blocked.held == 1 and not turn.ended
    after = await owned_counts(api, user_id)
    assert after["users"] == 1
    assert all(after[name] >= before[name] for name in before)
    blocked.release.set()
    await asyncio.wait_for(watcher, 5)
    await turns_settled()


# --- a message still being opened holds its claim ---


def slow_first_call(api, gate: asyncio.Event, entered: asyncio.Event):
    """A chat reply that sends its response headers only once `gate` is set."""

    async def reply(request):
        entered.set()
        await asyncio.wait_for(gate.wait(), 10)
        return httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_SseStream(text_chunks("Hello there.") + [usage_chunk()]),
        )

    return reply


async def check_delete_waits_for_a_message_being_opened(api, caplog, path: str, user_id) -> None:
    gate, entered = asyncio.Event(), asyncio.Event()
    api.fake.queue(slow_first_call(api, gate, entered))

    with caplog.at_level(logging.DEBUG):
        watcher = await watch_chat(api, "hello")
        await asyncio.wait_for(entered.wait(), 5)
        # turn.open() waits for the provider: the turn is not running yet.
        assert running.running_turns() == []
        before = await owned_counts(api, user_id)

        refused = await asyncio.create_task(api.http.delete(path, headers=api.headers))

        assert_busy(refused, TURNS_BUSY)
        assert await owned_counts(api, user_id) == before
        gate.set()
        left = await asyncio.wait_for(watcher, 5)
        await turns_settled()
        assert left.events[-1] == ("done", {})
        [row] = [r for r in await usage_rows(api) if r.kind == "chat"]
        conversation_id = row.conversation_id
        assert conversation_id is not None

        deleted = await asyncio.create_task(api.http.delete(path, headers=api.headers))
        assert deleted.status_code == 204, deleted.text
        await asyncio.sleep(0.05)

    no_integrity_error(caplog)
    return row


async def test_deleting_the_content_while_a_message_is_opened_is_refused_then_works(
    async_api, caplog
):
    api = async_api
    await api.ready()
    user_id = await api.user_id()

    row = await check_delete_waits_for_a_message_being_opened(api, caplog, "/api/me/content", user_id)

    [kept] = [r for r in await usage_rows(api) if r.kind == "chat"]
    assert kept.id == row.id
    assert kept.conversation_id is None

    async def conversations(session):
        return (
            await session.execute(select(func.count()).select_from(Conversation))
        ).scalar_one()

    assert await api.db(conversations) == 0


async def test_ending_a_demo_session_while_a_message_is_opened_is_refused_then_works(
    demo_api, caplog
):
    api = demo_api
    user_id = await asyncio.create_task(api.user_id())

    await check_delete_waits_for_a_message_being_opened(api, caplog, "/api/demo/session", user_id)

    assert set((await owned_counts(api, user_id)).values()) == {0}


async def test_a_message_refused_as_busy_keeps_its_own_text(async_api):
    api = async_api
    await api.ready()
    watcher, turn, conversation_id = await held(api)

    response = await api.chat("and another", conversation_id)

    assert_busy(
        response, "This conversation is still answering another message. Wait for it to finish."
    )
    turn.stop()
    await asyncio.wait_for(watcher, 5)
