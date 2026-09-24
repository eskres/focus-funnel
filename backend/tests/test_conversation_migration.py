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

    res = run_alembic(db_url, "downgrade", "bf3f5a046190")
    assert res.returncode == 0, res.stderr
    assert not NEW_TABLES & tables(db_file)
    assert "provider_keys" in tables(db_file)

    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr
    assert NEW_TABLES <= tables(db_file)


def test_the_new_revision_follows_the_provider_keys_rename():
    res = run_alembic("sqlite+aiosqlite:///:memory:", "history")
    assert res.returncode == 0, res.stderr
    assert "bf3f5a046190 -> bc1bdf980860" in res.stdout


def test_usage_tokens_may_be_unknown_after_upgrade_and_not_after_downgrade(tmp_path):
    db_file = tmp_path / "usage_tokens.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    def token_columns_nullable() -> dict[str, bool]:
        with sqlite3.connect(db_file) as conn:
            rows = conn.execute("PRAGMA table_info(usage_events)").fetchall()
        return {row[1]: not row[3] for row in rows if row[1].endswith("_tokens")}

    # Later revisions exist, so this stops at the usage change to test it alone.
    assert run_alembic(db_url, "upgrade", "7c2e4f9a1d35").returncode == 0
    assert token_columns_nullable() == {"prompt_tokens": True, "completion_tokens": True}

    res = run_alembic(db_url, "downgrade", "-1")
    assert res.returncode == 0, res.stderr
    assert token_columns_nullable() == {"prompt_tokens": False, "completion_tokens": False}

    res = run_alembic(db_url, "history")
    assert "bc1bdf980860 -> 7c2e4f9a1d35" in res.stdout
