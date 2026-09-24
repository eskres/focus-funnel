import asyncio
import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import String, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.pool import NullPool

from app.auth import get_current_user, get_jwks_cache, get_or_create_user
from app.db import create_engine, get_session
from app.errors import ApiError, ErrorCode, register_error_handlers
from app.models import Base, User
from app.ownership import get_owned_or_404, owned_by
from tests.conftest import TEST_ISSUER


class OwnershipTestBase(DeclarativeBase):
    pass


class Note(OwnershipTestBase):
    """Test-only user-owned model; kept out of the app's metadata."""

    __tablename__ = "test_notes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    text: Mapped[str] = mapped_column(String(100))


@pytest.fixture
async def sessions(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'own.sqlite3'}", poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(OwnershipTestBase.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def alice_bob_note(sessions):
    async with sessions() as session:
        alice = await get_or_create_user(session, TEST_ISSUER, "auth0|alice")
        bob = await get_or_create_user(session, TEST_ISSUER, "auth0|bob")
        note = Note(user_id=alice.id, text="alice's thought")
        session.add(note)
        await session.commit()
    return alice, bob, note


async def test_owner_gets_record(sessions, alice_bob_note):
    alice, _bob, note = alice_bob_note
    async with sessions() as session:
        found = await get_owned_or_404(session, Note, note.id, alice)
    assert found.text == "alice's thought"


async def test_other_user_gets_not_found(sessions, alice_bob_note):
    _alice, bob, note = alice_bob_note
    async with sessions() as session:
        with pytest.raises(ApiError) as error:
            await get_owned_or_404(session, Note, note.id, bob)
    assert error.value.status_code == 404
    assert error.value.code == ErrorCode.NOT_FOUND


async def test_other_users_record_looks_like_missing_record(sessions, alice_bob_note):
    _alice, bob, note = alice_bob_note
    async with sessions() as session:
        with pytest.raises(ApiError) as other_users:
            await get_owned_or_404(session, Note, note.id, bob)
        with pytest.raises(ApiError) as missing:
            await get_owned_or_404(session, Note, uuid.uuid4(), bob)

    assert (other_users.value.status_code, other_users.value.code, other_users.value.message) == (
        missing.value.status_code,
        missing.value.code,
        missing.value.message,
    )


async def test_owned_by_filters_list_queries(sessions, alice_bob_note):
    alice, bob, _note = alice_bob_note
    async with sessions() as session:
        alice_notes = (await session.execute(select(Note).where(owned_by(Note, alice)))).scalars().all()
        bob_notes = (await session.execute(select(Note).where(owned_by(Note, bob)))).scalars().all()
    assert len(alice_notes) == 1
    assert bob_notes == []


def test_http_response_is_identical_for_other_users_and_missing_records(
    tmp_path, settings_env, jwks_cache, make_token
):
    url = f"sqlite+aiosqlite:///{tmp_path / 'own-http.sqlite3'}"

    async def setup():
        engine = create_engine(url, poolclass=NullPool)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(OwnershipTestBase.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            alice = await get_or_create_user(session, TEST_ISSUER, "auth0|alice")
            note = Note(user_id=alice.id, text="private")
            session.add(note)
            await session.commit()
        await engine.dispose()
        return note.id

    note_id = asyncio.run(setup())
    settings_env.setenv("DATABASE_URL", url)

    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.get("/notes/{note_id}")
    async def read_note(
        note_id: uuid.UUID,
        user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ):
        note = await get_owned_or_404(session, Note, note_id, user)
        return {"text": note.text}

    test_app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    bob_headers = {"Authorization": f"Bearer {make_token(sub='auth0|bob')}"}
    alice_headers = {"Authorization": f"Bearer {make_token(sub='auth0|alice')}"}

    with TestClient(test_app) as client:
        owner = client.get(f"/notes/{note_id}", headers=alice_headers)
        other_user = client.get(f"/notes/{note_id}", headers=bob_headers)
        missing = client.get(f"/notes/{uuid.uuid4()}", headers=bob_headers)

    assert owner.status_code == 200
    assert other_user.status_code == 404
    assert other_user.json() == missing.json()
    assert other_user.json()["error"]["code"] == ErrorCode.NOT_FOUND
