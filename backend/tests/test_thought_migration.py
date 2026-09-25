"""The thought tables and their migration (thought-storage task 3.2)."""

import asyncio
import os
import sqlite3
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import get_or_create_user
from app.db import create_engine
from app.models import SearchIndex
from app.thoughts import VectorExtensionMissing, check_vector_extension
from tests.conftest import TEST_ISSUER
from tests.test_provider_key_migration import run_alembic

REVISION = "5e8b2c0d4a17"
PREVIOUS = "a97e96671d5c"
TABLES = {"thoughts", "search_indexes", "thought_embeddings"}


def sqlite_tables(db_file) -> set[str]:
    with sqlite3.connect(db_file) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def test_upgrade_and_downgrade_on_an_empty_sqlite_database(tmp_path):
    db_file = tmp_path / "empty.sqlite3"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    assert run_alembic(db_url, "upgrade", "head").returncode == 0
    assert TABLES <= sqlite_tables(db_file)

    res = run_alembic(db_url, "downgrade", PREVIOUS)
    assert res.returncode == 0, res.stderr
    assert not TABLES & sqlite_tables(db_file)

    assert run_alembic(db_url, "upgrade", "head").returncode == 0
    res = run_alembic(db_url, "check")
    assert res.returncode == 0, res.stdout + res.stderr


def add_index(user_id: uuid.UUID, version: int, status: str) -> SearchIndex:
    return SearchIndex(
        user_id=user_id,
        version=version,
        embedding_provider="nebius",
        embedding_model="m",
        dimension=2,
        status=status,
    )


@pytest.mark.parametrize("status", ["active", "building"])
def test_one_active_and_one_building_index_per_user(test_database_url, status):
    async def run():
        engine = create_engine(test_database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            alice = await get_or_create_user(session, TEST_ISSUER, "alice")
            bob = await get_or_create_user(session, TEST_ISSUER, "bob")
            session.add_all(
                [
                    add_index(alice.id, 1, "retired"),
                    add_index(alice.id, 2, "retired"),
                    add_index(alice.id, 3, status),
                    add_index(bob.id, 1, status),
                ]
            )
            await session.commit()
            session.add(add_index(alice.id, 4, status))
            with pytest.raises(IntegrityError):
                await session.commit()
        await engine.dispose()

    asyncio.run(run())


def admin_url() -> str:
    return os.environ["TEST_DATABASE_URL"]


def with_database(name: str):
    """Create an empty Postgres database next to the test one, and drop it after."""

    async def execute(statement: str):
        engine = create_engine(admin_url(), poolclass=NullPool, isolation_level="AUTOCOMMIT")
        async with engine.connect() as connection:
            await connection.execute(text(statement))
        await engine.dispose()

    asyncio.run(execute(f'DROP DATABASE IF EXISTS "{name}"'))
    asyncio.run(execute(f'CREATE DATABASE "{name}"'))
    base = admin_url().rsplit("/", 1)[0]
    return f"{base}/{name}", lambda: asyncio.run(execute(f'DROP DATABASE IF EXISTS "{name}"'))


@pytest.mark.postgres
def test_upgrade_and_downgrade_on_an_empty_postgres_database():
    db_url, drop = with_database("ff_thought_migration")
    try:
        res = run_alembic(db_url, "upgrade", "head")
        assert res.returncode == 0, res.stderr
        res = run_alembic(db_url, "check")
        assert res.returncode == 0, res.stdout + res.stderr
        assert embedding_storage(db_url) == "m"
        res = run_alembic(db_url, "downgrade", PREVIOUS)
        assert res.returncode == 0, res.stderr
        res = run_alembic(db_url, "upgrade", "head")
        assert res.returncode == 0, res.stderr
    finally:
        drop()


def embedding_storage(url: str) -> str:
    async def read():
        engine = create_engine(url, poolclass=NullPool)
        async with engine.connect() as connection:
            storage = (
                await connection.execute(
                    text(
                        "SELECT attstorage::text FROM pg_attribute "
                        "WHERE attrelid = 'thought_embeddings'::regclass AND attname = 'embedding'"
                    )
                )
            ).scalar_one()
        await engine.dispose()
        return storage

    return asyncio.run(read())


@pytest.mark.postgres
def test_vectors_are_kept_in_the_row(test_database_url):
    # Tables made by the test fixture (create_all) match the migration.
    assert embedding_storage(test_database_url) == "m"


class OldPgvector:
    """A connection that reports pgvector 0.6, which has no halfvec."""

    class dialect:
        name = "postgresql"

    async def execute(self, _statement):
        class Result:
            def scalar(self):
                return "0.6.0"

        return Result()


def test_startup_check_refuses_pgvector_before_0_7():
    with pytest.raises(VectorExtensionMissing, match="version 0.6.0; thought search needs 0.7"):
        asyncio.run(check_vector_extension(OldPgvector()))


@pytest.mark.postgres
def test_startup_check_refuses_postgres_without_pgvector(test_database_url):
    async def run():
        engine = create_engine(test_database_url, poolclass=NullPool)
        async with engine.connect() as connection:
            await check_vector_extension(connection)
            # DDL is transactional: drop it inside this transaction, then roll back.
            await connection.execute(text("DROP EXTENSION vector CASCADE"))
            with pytest.raises(VectorExtensionMissing, match="'vector'"):
                await check_vector_extension(connection)
            await connection.rollback()
        await engine.dispose()

    asyncio.run(run())


def test_startup_check_passes_on_sqlite(test_database_url):
    async def run():
        engine = create_engine(test_database_url, poolclass=NullPool)
        async with engine.connect() as connection:
            await check_vector_extension(connection)
        await engine.dispose()

    asyncio.run(run())
