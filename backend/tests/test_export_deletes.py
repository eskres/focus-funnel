"""A delete of the user's content or account, or the end of a demo session,
ends a running export as failed (thought-export task 2.9, design decisions
15 and 16)."""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app import demo
from app.models import Conversation
from app.thoughts import export
from app.thoughts.export import LIVE, ExportAborted, stop_exports
from tests.export_helpers import (
    Download,
    assert_no_sentinel_logged,
    export_records,
    listen_after,
    make_user,
    seed_sentinel_thoughts,
    started,
    thoughts_queries,
)

pytestmark = pytest.mark.postgres

USER_DATA = Path(__file__).resolve().parent.parent / "app" / "user_data.py"


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.INFO, logger="app.thoughts.export")
    return caplog


def marker(format: str) -> str:
    return '"count"' if format == "json" else "End of export"


def assert_stopped(item: Download, format: str = "json") -> None:
    """Ended without its last body message, its count, or its end line."""
    assert item.status == 200
    assert item.error is None, item.error
    assert not item.ended
    assert not any(
        m["type"] == "http.response.body" and m.get("more_body", False) is False
        for m in item.messages
    )
    assert marker(format) not in item.text


def assert_logged_as_stopped(
    logs, user_id, format: str = "json", times: int = 1
) -> None:
    ended = [m for m in export_records(logs) if f"user={user_id} format={format}" in m]
    stopped = [m for m in ended if m.endswith("outcome=failed error=ExportAborted")]
    assert len(stopped) == times, ended
    assert not any(r.getMessage() == "Unhandled error" for r in logs.records)
    assert not any(
        r.exc_info and isinstance(r.exc_info[1], ExportAborted) for r in logs.records
    )
    assert_no_sentinel_logged(logs)


def test_user_data_imports_the_export_only_inside_its_functions():
    source = USER_DATA.read_text()
    top_level = [
        line for line in source.splitlines() if line.startswith(("import ", "from "))
    ]
    assert not any("app.thoughts.export" in line for line in top_level)
    assert source.count("from app.thoughts.export import stop_exports") == 2


@pytest.mark.parametrize("format", ["json", "markdown"])
async def test_deleting_content_stops_a_held_export(
    async_api, logs, batch_of_two, format
):
    api = async_api
    user_id = await api.user_id()
    await seed_sentinel_thoughts(api, user_id, 5)
    held = await started(api.app, api.headers, format)
    response = await api.http.delete("/api/me/content", headers=api.headers)
    assert response.status_code == 204
    await held.done()
    assert_stopped(held, format)
    assert_logged_as_stopped(logs, user_id, format)


async def test_a_stop_during_the_second_batchs_query(async_api, logs, batch_of_two):
    api = async_api
    user_id = await api.user_id()
    await seed_sentinel_thoughts(api, user_id, 5)
    seen = []

    def hook(statement):
        if thoughts_queries([statement]):
            seen.append(statement)
            if len(seen) == 2:
                stop_exports(user_id)

    remove = listen_after(hook)
    try:
        item = await Download(api.app, api.headers, hold=False).start().done()
    finally:
        remove()
    assert_stopped(item)
    assert item.text.count('"title"') == 2
    assert_logged_as_stopped(logs, user_id)


async def test_a_new_export_after_the_delete(async_api, logs, batch_of_two):
    api = async_api
    user_id = await api.user_id()
    await seed_sentinel_thoughts(api, user_id, 5)
    held = await started(api.app, api.headers)
    assert (
        await api.http.delete("/api/me/content", headers=api.headers)
    ).status_code == 204
    # The stopped lease no longer counts as running.
    newer = await started(api.app, api.headers)
    assert newer.status == 200
    await held.done()
    assert_stopped(held)
    [left] = LIVE[user_id]
    assert not left.aborted
    await newer.done()
    assert newer.ended and newer.json()["count"] == 0
    assert user_id not in LIVE


async def test_deleting_the_account_stops_a_held_export(async_api, logs, batch_of_two):
    api = async_api
    user_id = await api.user_id()
    await seed_sentinel_thoughts(api, user_id, 5)
    held = await started(api.app, api.headers)
    assert (await api.http.delete("/api/me", headers=api.headers)).status_code == 204
    await held.done()
    assert_stopped(held)
    assert_logged_as_stopped(logs, user_id)


async def test_ending_the_demo_stops_a_held_export(demo_visitor, logs, batch_of_two):
    visitor = demo_visitor
    user_id = await visitor.user_id()
    await seed_sentinel_thoughts(visitor, user_id, 5)
    held = await started(visitor.app, visitor.headers)
    response = await visitor.http.delete("/api/demo/session", headers=visitor.headers)
    assert response.status_code == 204
    await held.done()
    assert_stopped(held)
    assert_logged_as_stopped(logs, user_id)


async def test_the_demo_cleanup_stops_a_held_export(
    demo_visitor, logs, batch_of_two, monkeypatch
):
    visitor = demo_visitor
    user_id = await visitor.user_id()
    await seed_sentinel_thoughts(visitor, user_id, 5)
    held = await started(visitor.app, visitor.headers)
    real_now = demo.now
    later = datetime.now(UTC) + timedelta(days=2)
    monkeypatch.setattr(demo, "now", lambda: later)
    deleted = await visitor.db(demo.delete_expired_demo_users)
    assert deleted == 1
    # The clock goes back, so only the cleanup's stop can end the export.
    monkeypatch.setattr(demo, "now", real_now)
    assert not held.task.done()
    await held.done()
    assert_stopped(held)
    assert_logged_as_stopped(logs, user_id)


async def test_the_demo_session_end_alone_stops_a_held_export(
    demo_visitor, logs, batch_of_two, monkeypatch
):
    """No cleanup runs: the lease's own expiry check ends it (design decision 12)."""
    visitor = demo_visitor
    user_id = await visitor.user_id()
    await seed_sentinel_thoughts(visitor, user_id, 5)
    held = await started(visitor.app, visitor.headers)
    later = datetime.now(UTC) + timedelta(days=2)
    monkeypatch.setattr(demo, "now", lambda: later)
    await held.done()
    assert_stopped(held)
    assert_logged_as_stopped(logs, user_id)


@pytest.mark.parametrize("format", ["json", "markdown"])
async def test_a_delete_while_the_only_batch_is_sent(async_api, logs, format):
    api = async_api
    user_id = await api.user_id()
    await seed_sentinel_thoughts(api, user_id, 3)
    held = await started(api.app, api.headers, format)
    held.step()  # the opening part was held; now hold after the batch's part
    await held.held()
    assert held.text.count("QUOKKA-TITLE-SENTINEL") == 3
    assert (
        await api.http.delete("/api/me/content", headers=api.headers)
    ).status_code == 204
    await held.done()
    assert_stopped(held, format)
    assert_logged_as_stopped(logs, user_id, format)


async def test_a_delete_stops_a_stale_export_too(
    async_api, logs, batch_of_two, lease_clock
):
    api = async_api
    user_id = await api.user_id()
    await seed_sentinel_thoughts(api, user_id, 5)
    first = await started(api.app, api.headers)
    lease_clock.move(61)
    second = await started(api.app, api.headers)
    assert second.status == 200
    assert (
        await api.http.delete("/api/me/content", headers=api.headers)
    ).status_code == 204
    await first.done()
    await second.done()
    assert_stopped(first)
    assert_stopped(second)
    assert_logged_as_stopped(logs, user_id, times=2)


async def test_another_users_export_runs_on(async_api, bob, logs, batch_of_two):
    api = async_api
    alice_id = await api.user_id()
    bob_id = await make_user(api, bob)
    await seed_sentinel_thoughts(api, alice_id, 5)
    await seed_sentinel_thoughts(api, bob_id, 5)
    bobs = await started(api.app, bob)
    assert (
        await api.http.delete("/api/me/content", headers=api.headers)
    ).status_code == 204
    await bobs.done()
    assert bobs.ended and bobs.json()["count"] == 5
    assert (
        f"export ended user={bob_id} format=json thoughts=5 outcome=complete"
        in export_records(logs)
    )


async def test_a_refused_delete_stops_no_export(async_api, logs, batch_of_two):
    api = async_api
    user_id = await api.user_id()
    await seed_sentinel_thoughts(api, user_id, 5)

    async def claimed(session):
        session.add(
            Conversation(
                user_id=user_id,
                title="Still answering",
                turn_started_at=datetime.now(UTC),
            )
        )
        await session.commit()

    await api.db(claimed)
    held = await started(api.app, api.headers)
    response = await api.http.delete("/api/me/content", headers=api.headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conversation_busy"
    await held.done()
    assert held.ended and held.json()["count"] == 5
    assert export_records(logs) == [
        f"export ended user={user_id} format=json thoughts=5 outcome=complete"
    ]
    assert export.LIVE == {}
