"""One export per user and format at a time, at most four open, and the
one-minute heartbeat (thought-export task 2.5, design decisions 1 and 7)."""

import asyncio
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from app.db import create_engine, get_engine
from app.thoughts import export
from app.thoughts.export import LIVE, ExportResponse, take_lease
from tests.conftest import TEST_ISSUER
from tests.export_helpers import Download, error_of, seed_plain, started

ALREADY = "An export in this format is already running. Try again when it has finished."
TOO_MANY = "Too many of your exports are still open. Try again when one has finished."


def assert_refused(item: Download, message: str = ALREADY) -> None:
    assert item.status == 409, item.text
    assert error_of(item) == {"code": "export_running", "message": message}
    assert "content-disposition" not in item.response_headers


def assert_complete_json(item: Download, count: int | None = None) -> None:
    assert item.status == 200 and item.ended and item.error is None, item.text
    document = item.json()
    if count is not None:
        assert document["count"] == count


async def test_one_export_per_user_and_format(async_api, bob):
    api = async_api
    alice_id = await api.user_id()
    await seed_plain(api, alice_id, 3)
    held = await started(api.app, api.headers)
    assert held.status == 200

    again = await Download(api.app, api.headers, hold=False).start().done()
    assert_refused(again)

    markdown = (
        await Download(api.app, api.headers, "markdown", hold=False).start().done()
    )
    assert markdown.status == 200 and markdown.ended
    assert markdown.text.endswith("End of export: 3 thoughts.\n")

    bobs = await Download(api.app, bob, hold=False).start().done()
    assert_complete_json(bobs, 0)

    await held.done()
    assert_complete_json(held, 3)
    after = await Download(api.app, api.headers, hold=False).start().done()
    assert_complete_json(after, 3)
    assert alice_id not in LIVE


@pytest.mark.postgres
async def test_a_held_export_holds_no_connection(async_api, test_database_url):
    api = async_api
    alice_id = await api.user_id()
    await seed_plain(api, alice_id, 3)
    held = await started(api.app, api.headers)
    assert held.status == 200
    assert get_engine().pool.checkedout() == 0
    checker = create_engine(test_database_url, poolclass=NullPool)
    try:
        async with checker.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT pid FROM pg_stat_activity WHERE datname = current_database() "
                        "AND state = 'idle in transaction' AND pid <> pg_backend_pid()"
                    )
                )
            ).all()
    finally:
        await checker.dispose()
    assert rows == []
    await held.done()
    assert_complete_json(held, 3)
    after = await Download(api.app, api.headers, hold=False).start().done()
    assert_complete_json(after, 3)


async def test_a_stale_export_lets_a_new_one_start(async_api, lease_clock):
    api = async_api
    alice_id = await api.user_id()
    held = await started(api.app, api.headers)
    lease_clock.move(61)
    newer = await started(api.app, api.headers)
    assert newer.status == 200
    assert len(LIVE[alice_id]) == 2
    await held.done()
    assert_complete_json(held, 0)
    [left] = LIVE[alice_id]
    assert left.format == "json" and not left.aborted
    await newer.done()
    assert alice_id not in LIVE


async def test_each_chunk_sent_refreshes_the_lease(
    async_api, lease_clock, batch_of_two
):
    api = async_api
    alice_id = await api.user_id()
    await seed_plain(api, alice_id, 5)
    held = await started(api.app, api.headers)
    lease_clock.move(50)
    held.step()
    await held.held()
    lease_clock.move(50)
    refused = await Download(api.app, api.headers, hold=False).start().done()
    assert_refused(refused)
    lease_clock.move(11)
    newer = await started(api.app, api.headers)
    assert newer.status == 200
    await held.done()
    await newer.done()
    assert_complete_json(held, 5)
    assert_complete_json(newer, 5)


async def test_a_response_that_fails_before_its_generator_starts_frees_the_format():
    user_id = uuid.uuid4()
    lease = take_lease(user_id, "json", None)
    started_generator = []

    async def batches():
        started_generator.append(True)
        yield []

    response = ExportResponse(lease, batches(), export.utcnow())

    async def receive():
        await asyncio.Event().wait()

    async def send(message):
        raise RuntimeError("the connection broke")

    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}}
    with pytest.raises(RuntimeError):
        await response(scope, receive, send)
    assert started_generator == []
    assert user_id not in LIVE
    take_lease(user_id, "json", None)


async def test_a_failing_session_close_leaves_no_lease(async_api, monkeypatch):
    api = async_api
    alice_id = await api.user_id()
    real = AsyncSession.close
    calls = []

    async def failing_once(self):
        calls.append(self)
        if len(calls) == 1:
            raise RuntimeError("close failed")
        await real(self)

    monkeypatch.setattr(AsyncSession, "close", failing_once)
    failed = await Download(api.app, api.headers, hold=False).start().done()
    assert failed.status == 500
    assert error_of(failed)["code"] == "internal_error"
    assert alice_id not in LIVE
    monkeypatch.setattr(AsyncSession, "close", real)
    after = await Download(api.app, api.headers, hold=False).start().done()
    assert_complete_json(after, 0)


async def test_two_exports_started_together(async_api):
    api = async_api
    alice_id = await api.user_id()
    first = Download(api.app, api.headers)
    second = Download(api.app, api.headers)

    async def begin(item: Download):
        item.start()
        await item.settled()

    await asyncio.gather(begin(first), begin(second))
    statuses = sorted([first.status, second.status])
    assert statuses == [200, 409]
    refused = first if first.status == 409 else second
    assert_refused(refused)
    assert len(LIVE[alice_id]) == 1
    await first.done()
    await second.done()


async def test_at_most_four_open_exports(async_api, bob, lease_clock):
    api = async_api
    alice_id = await api.user_id()
    held = []
    for _ in range(4):
        item = await started(api.app, api.headers)
        assert item.status == 200
        held.append(item)
        lease_clock.move(61)
    for format in ("json", "markdown"):
        refused = (
            await Download(api.app, api.headers, format, hold=False).start().done()
        )
        assert_refused(refused, TOO_MANY)
    bobs = await Download(api.app, bob, hold=False).start().done()
    assert_complete_json(bobs, 0)
    await held[0].done()
    assert len(LIVE[alice_id]) == 3
    after = await Download(api.app, api.headers, "markdown", hold=False).start().done()
    assert after.status == 200 and after.text.endswith("End of export: 0 thoughts.\n")
    for item in held[1:]:
        await item.done()
        assert_complete_json(item, 0)
    assert alice_id not in LIVE


# Two tests in order: a lease the first leaves is gone in the second.
FIXED_USER = uuid.UUID("0f0f0f0f-0000-4000-8000-000000000001")


def test_a_lease_left_by_one_test():
    take_lease(FIXED_USER, "json", None)
    assert FIXED_USER in LIVE


async def test_is_gone_in_the_next(async_api):
    from app.models import User

    api = async_api
    assert FIXED_USER not in LIVE

    async def work(session):
        session.add(User(id=FIXED_USER, issuer=TEST_ISSUER, subject="user|alice"))
        await session.commit()

    await api.db(work)
    assert await api.user_id() == FIXED_USER
    item = await Download(api.app, api.headers, hold=False).start().done()
    assert_complete_json(item, 0)
