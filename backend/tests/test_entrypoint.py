"""The container entrypoint applies migrations before running the server.

These run the script directly against a temporary SQLite database, with a
harmless command standing in for uvicorn, so they need no Postgres and no
compose stack.
"""

import os
import sqlite3
import subprocess
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
ENTRYPOINT = BACKEND_DIR / "docker-entrypoint.sh"

# Stands in for uvicorn: it proves the entrypoint reached `exec "$@"`.
SERVER_COMMAND = ["python", "-c", "print('SERVER STARTED')"]
SERVER_MARKER = "SERVER STARTED"

MIGRATED_TABLES = {"users", "provider_keys", "alembic_version"}


def run_entrypoint(database_url: str) -> subprocess.CompletedProcess[str]:
    """Run the entrypoint with DATABASE_URL set, from the backend directory."""
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [str(ENTRYPOINT), *SERVER_COMMAND],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def table_names(database_file: Path) -> set[str]:
    with sqlite3.connect(database_file) as connection:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {name for (name,) in rows}


def test_entrypoint_is_executable():
    assert os.access(ENTRYPOINT, os.X_OK), f"{ENTRYPOINT} is not executable"


def test_migrates_a_fresh_database_then_runs_the_command(tmp_path):
    database_file = tmp_path / "fresh.sqlite3"

    result = run_entrypoint(f"sqlite+aiosqlite:///{database_file}")

    assert result.returncode == 0, result.stderr
    assert SERVER_MARKER in result.stdout
    assert MIGRATED_TABLES <= table_names(database_file)


def test_running_again_on_a_migrated_database_succeeds(tmp_path):
    database_file = tmp_path / "repeat.sqlite3"
    database_url = f"sqlite+aiosqlite:///{database_file}"

    first = run_entrypoint(database_url)
    second = run_entrypoint(database_url)

    assert first.returncode == 0, first.stderr
    # Already at head: the second run changes nothing and still starts the server.
    assert second.returncode == 0, second.stderr
    assert SERVER_MARKER in second.stdout
    assert MIGRATED_TABLES <= table_names(database_file)


def test_a_failed_migration_stops_before_the_command(tmp_path):
    # A directory that does not exist, so SQLite cannot open the database.
    unusable = tmp_path / "missing" / "db.sqlite3"

    result = run_entrypoint(f"sqlite+aiosqlite:///{unusable}")

    assert result.returncode != 0
    assert SERVER_MARKER not in result.stdout
