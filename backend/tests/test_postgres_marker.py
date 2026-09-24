"""The `postgres` marker: left out by default, and failing without a database."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.pool import NullPool

from app.db import create_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]
POSTGRES_TEST = f"{__file__}::test_pgvector_is_available"


def run_pytest(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_postgres_tests_fail_without_a_database():
    env = {name: value for name, value in os.environ.items() if name != "TEST_DATABASE_URL"}
    res = run_pytest("-m", "postgres", "-p", "no:cacheprovider", POSTGRES_TEST, env=env)
    assert res.returncode != 0
    assert "TEST_DATABASE_URL must point at a Postgres with pgvector" in res.stdout


def test_default_run_leaves_postgres_tests_out():
    env = {name: value for name, value in os.environ.items() if name != "TEST_DATABASE_URL"}
    res = run_pytest("-p", "no:cacheprovider", POSTGRES_TEST, env=env)
    # Exit code 5: nothing ran, because the one test was deselected.
    assert res.returncode == 5, res.stdout
    assert "1 deselected" in res.stdout


@pytest.mark.postgres
def test_pgvector_is_available(test_database_url):
    async def check():
        engine = create_engine(test_database_url, poolclass=NullPool)
        async with engine.connect() as connection:
            distance = (
                await connection.execute(text("SELECT '[1,0]'::vector <=> '[0,1]'::vector"))
            ).scalar_one()
        await engine.dispose()
        return distance

    assert asyncio.run(check()) == pytest.approx(1.0)
