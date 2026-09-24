import sqlite3
import uuid

from tests.test_provider_key_migration import run_alembic

# The revision before auth-modes, where users still have auth0_sub.
BEFORE = "7c2e4f9a1d35"
REVISION = "a97e96671d5c"


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_single_head_is_this_revision():
    res = run_alembic("sqlite+aiosqlite:///:memory:", "heads")
    assert res.returncode == 0, res.stderr
    heads = [line for line in res.stdout.splitlines() if line.strip()]
    assert heads == [f"{REVISION} (head)"]


def test_upgrade_and_downgrade_on_an_empty_database(tmp_path):
    db_file = tmp_path / "empty.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr
    with sqlite3.connect(db_file) as conn:
        assert columns(conn, "users") == {
            "id", "issuer", "subject", "created_at", "expires_at", "demo_notice_accepted_at"
        }

    res = run_alembic(db_url, "downgrade", "-1")
    assert res.returncode == 0, res.stderr
    with sqlite3.connect(db_file) as conn:
        assert columns(conn, "users") == {"id", "auth0_sub", "created_at"}
        schema = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'users'").fetchone()[0]
        assert "uq_users_auth0_sub UNIQUE (auth0_sub)" in schema

    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr


def insert_user(conn, issuer: str, subject: str) -> bytes:
    user_id = uuid.uuid4().bytes
    conn.execute(
        "INSERT INTO users (id, issuer, subject, created_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
        (user_id, issuer, subject),
    )
    return user_id


def test_existing_row_survives_as_auth0_legacy_and_the_downgrade(tmp_path):
    db_file = tmp_path / "legacy.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    assert run_alembic(db_url, "upgrade", BEFORE).returncode == 0

    legacy_id = uuid.uuid4().bytes
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "INSERT INTO users (id, auth0_sub, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (legacy_id, "user|developer"),
        )
        conn.execute(
            "INSERT INTO provider_keys (id, user_id, provider_id, created_at, updated_at) "
            "VALUES (?, ?, 'nebius', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (uuid.uuid4().bytes, legacy_id),
        )

    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute("SELECT id, issuer, subject, expires_at FROM users").fetchall()
        assert rows == [(legacy_id, "auth0-legacy", "user|developer", None)]
        assert conn.execute("SELECT count(*) FROM provider_keys").fetchone() == (1,)

        # A user from a real login, with data, and the same subject elsewhere.
        new_id = insert_user(conn, "http://localhost:1411", "user|developer")
        conversation_id = uuid.uuid4().bytes
        conn.execute(
            "INSERT INTO conversations (id, user_id, title, last_activity_at, created_at, updated_at) "
            "VALUES (?, ?, 't', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (conversation_id, new_id),
        )
        conn.execute(
            "INSERT INTO provider_keys (id, user_id, provider_id, created_at, updated_at) "
            "VALUES (?, ?, 'nebius', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (uuid.uuid4().bytes, new_id),
        )

    res = run_alembic(db_url, "downgrade", "-1")
    assert res.returncode == 0, res.stderr
    with sqlite3.connect(db_file) as conn:
        assert conn.execute("SELECT id, auth0_sub FROM users").fetchall() == [
            (legacy_id, "user|developer")
        ]
        assert conn.execute("SELECT user_id FROM provider_keys").fetchall() == [(legacy_id,)]
        assert conn.execute("SELECT count(*) FROM conversations").fetchone() == (0,)
