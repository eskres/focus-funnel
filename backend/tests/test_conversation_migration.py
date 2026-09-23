import sqlite3

from tests.test_provider_key_migration import run_alembic

NEW_TABLES = {"conversations", "messages", "usage_events", "chat_models", "user_settings"}


def tables(db_file) -> set[str]:
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {row[0] for row in rows}


def test_upgrade_then_downgrade_runs_cleanly_on_an_empty_database(tmp_path):
    db_file = tmp_path / "migration_test.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr
    assert NEW_TABLES <= tables(db_file)

    res = run_alembic(db_url, "downgrade", "-1")
    assert res.returncode == 0, res.stderr
    assert not NEW_TABLES & tables(db_file)
    assert "provider_keys" in tables(db_file)

    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr
    assert NEW_TABLES <= tables(db_file)


def test_the_new_revision_follows_the_provider_keys_rename():
    res = run_alembic("sqlite+aiosqlite:///:memory:", "history")
    assert res.returncode == 0, res.stderr
    assert "bf3f5a046190 -> bc1bdf980860 (head)" in res.stdout
