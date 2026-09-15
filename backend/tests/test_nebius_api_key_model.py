import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.crypto import encrypt_secret
from app.db import create_engine
from app.models import Base, NebiusApiKey, User

MASTER_KEY = os.urandom(32)


@pytest.fixture
async def session():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def key_row(user_id: uuid.UUID, api_key: str = "nb-test-0123456789abcdef") -> NebiusApiKey:
    secret = encrypt_secret(MASTER_KEY, user_id, api_key)
    return NebiusApiKey(
        user_id=user_id,
        ciphertext=secret.ciphertext,
        nonce=secret.nonce,
        key_version=secret.key_version,
        last4=api_key[-4:],
    )


async def make_user(session, sub: str) -> User:
    user = User(auth0_sub=sub)
    session.add(user)
    await session.commit()
    return user


async def test_key_row_stores_fields_and_timestamps(session):
    user = await make_user(session, "auth0|alice")
    session.add(key_row(user.id))
    await session.commit()

    row = (await session.execute(select(NebiusApiKey))).scalar_one()
    assert row.last4 == "cdef"
    assert row.key_version == 1
    assert row.created_at is not None
    assert row.updated_at is not None


async def test_second_key_for_same_user_is_rejected(session):
    user = await make_user(session, "auth0|alice")
    session.add(key_row(user.id))
    await session.commit()

    session.add(key_row(user.id, "nb-other-key-9999"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_key_requires_existing_user(session):
    session.add(key_row(uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await session.commit()
