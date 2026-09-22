import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def run_alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": database_url}
    cmd = [sys.executable, "-m", "alembic", *args]
    return subprocess.run(
        cmd, cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60
    )


def test_single_alembic_head():
    res = run_alembic("sqlite+aiosqlite:///:memory:", "heads")
    assert res.returncode == 0, res.stderr
    heads = [line for line in res.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, res.stdout


def test_upgrade_downgrade_upgrade_cleanly_on_empty_database(tmp_path):
    db_file = tmp_path / "migration_test.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr

    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "provider_keys" in tables
        assert "nebius_api_keys" not in tables
        cursor.execute("PRAGMA table_info(provider_keys)")
        columns = {row[1]: row for row in cursor.fetchall()}
        assert "provider_id" in columns
        assert "base_url" in columns
        # notnull is index 3 in PRAGMA table_info rows; 0 means nullable.
        assert columns["ciphertext"][3] == 0
        assert columns["last4"][3] == 0

    res = run_alembic(db_url, "downgrade", "-1")
    assert res.returncode == 0, res.stderr

    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "nebius_api_keys" in tables
        assert "provider_keys" not in tables

    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr
    with sqlite3.connect(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "provider_keys" in tables


def test_nebius_row_survives_upgrade_as_nebius_provider(tmp_path):
    db_file = tmp_path / "migration_test.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    # Stop one migration short of the rename, so a nebius_api_keys row can be
    # inserted the way it looked before this change.
    res = run_alembic(db_url, "upgrade", "d06a9fe12cba")
    assert res.returncode == 0, res.stderr

    user_id = uuid.uuid4()
    key_id = uuid.uuid4()
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "INSERT INTO users (id, auth0_sub, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id.bytes, "auth0|legacy-user"),
        )
        conn.execute(
            "INSERT INTO nebius_api_keys "
            "(id, user_id, ciphertext, nonce, key_version, last4, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (key_id.bytes, user_id.bytes, b"ciphertext", b"nonce123456", 1, "1111"),
        )
        conn.commit()

    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr

    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            "SELECT provider_id, last4, base_url FROM provider_keys WHERE id = ?", (key_id.bytes,)
        ).fetchone()
    assert row == ("nebius", "1111", None)


def test_downgrade_drops_keys_for_other_providers(tmp_path):
    db_file = tmp_path / "migration_test.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"

    res = run_alembic(db_url, "upgrade", "head")
    assert res.returncode == 0, res.stderr

    user_id = uuid.uuid4()
    nebius_key_id = uuid.uuid4()
    nvidia_key_id = uuid.uuid4()
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "INSERT INTO users (id, auth0_sub, created_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            (user_id.bytes, "auth0|multi-provider-user"),
        )
        conn.execute(
            "INSERT INTO provider_keys "
            "(id, user_id, provider_id, base_url, ciphertext, nonce, key_version, last4, "
            "created_at, updated_at) "
            "VALUES (?, ?, 'nebius', NULL, ?, ?, 1, '1111', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (nebius_key_id.bytes, user_id.bytes, b"ciphertext", b"nonce123456"),
        )
        conn.execute(
            "INSERT INTO provider_keys "
            "(id, user_id, provider_id, base_url, ciphertext, nonce, key_version, last4, "
            "created_at, updated_at) "
            "VALUES (?, ?, 'nvidia', NULL, ?, ?, 1, '2222', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (nvidia_key_id.bytes, user_id.bytes, b"ciphertext2", b"nonce654321"),
        )
        conn.commit()

    res = run_alembic(db_url, "downgrade", "-1")
    assert res.returncode == 0, res.stderr

    with sqlite3.connect(db_file) as conn:
        rows = conn.execute("SELECT id FROM nebius_api_keys").fetchall()
    assert [row[0] for row in rows] == [nebius_key_id.bytes]
