"""The export lease: check(), take_lease() and release(), and the imports
that must not form a cycle (thought-export task 2.1, default run)."""

import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app import demo
from app.models import User
from app.thoughts import export
from app.thoughts.export import LIVE, ExportAborted, Lease, release, take_lease
from tests.chat_helpers import run_db

BACKEND = Path(__file__).resolve().parent.parent
END = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)


def lease(expires_at=None) -> Lease:
    return Lease(
        user_id=uuid.uuid4(), format="json", written_at=0.0, expires_at=expires_at
    )


def test_check_raises_once_aborted():
    item = lease()
    item.check()
    item.aborted = True
    with pytest.raises(ExportAborted):
        item.check()


def test_check_raises_once_the_demo_session_has_ended(monkeypatch):
    item = lease(END)
    monkeypatch.setattr(demo, "now", lambda: END - timedelta(seconds=1))
    item.check()
    monkeypatch.setattr(demo, "now", lambda: END)
    with pytest.raises(ExportAborted):
        item.check()
    monkeypatch.setattr(demo, "now", lambda: END + timedelta(hours=1))
    with pytest.raises(ExportAborted):
        item.check()


def test_check_passes_without_an_end(monkeypatch):
    monkeypatch.setattr(demo, "now", lambda: END + timedelta(days=365))
    lease(None).check()


def test_a_naive_expiry_from_sqlite_is_compared_without_error(
    test_database_url, monkeypatch
):
    """The route stores demo.as_utc() of the expiry the database hands back
    (design decision 12); SQLite hands it back naive."""

    async def work(session):
        session.add(User(issuer="demo", subject="a" * 64, expires_at=END))
        await session.commit()
        return (await session.execute(select(User.expires_at))).scalar_one()

    stored = run_db(test_database_url, work)
    assert stored.tzinfo is None
    item = lease(demo.as_utc(stored))
    monkeypatch.setattr(demo, "now", lambda: END - timedelta(minutes=1))
    item.check()
    monkeypatch.setattr(demo, "now", lambda: END + timedelta(seconds=1))
    with pytest.raises(ExportAborted):
        item.check()


def test_take_lease_adds_it_to_the_users_set():
    user_id = uuid.uuid4()
    taken = take_lease(user_id, "json", None)
    assert LIVE[user_id] == {taken}
    assert (
        taken.format == "json" and taken.aborted is False and taken.expires_at is None
    )


def test_release_removes_only_that_lease(monkeypatch):
    user_id = uuid.uuid4()
    first = take_lease(user_id, "json", None)
    # The first is stale, so a second of the same format may start.
    monkeypatch.setattr(export, "monotonic", lambda: first.written_at + 61)
    second = take_lease(user_id, "json", None)
    assert first is not second and first.format == second.format
    release(first)
    assert LIVE[user_id] == {second}
    release(second)
    assert user_id not in LIVE
    # A second release of the same lease changes nothing.
    release(second)
    assert user_id not in LIVE


@pytest.mark.parametrize("module", ["app.thoughts.export", "app.user_data", "app.main"])
def test_each_module_imports_in_a_fresh_interpreter(module):
    """`python -I` keeps the working folder off sys.path, and `app` is not an
    installed package, so the backend folder is put back by hand (design
    decision 19)."""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            f"import sys; sys.path.insert(0, '.'); import {module}",
        ],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
