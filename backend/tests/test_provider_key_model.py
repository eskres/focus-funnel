import os
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.crypto import DecryptionError, decrypt_secret, encrypt_secret
from app.db import create_engine
from app.models import Base, ProviderKey, User

MASTER_KEY = os.urandom(32)


@pytest.fixture
async def session():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


def key_row(
    user_id: uuid.UUID, provider_id: str = "nebius", api_key: str = "nb-test-0123456789abcdef"
) -> ProviderKey:
    secret = encrypt_secret(MASTER_KEY, user_id, provider_id, api_key)
    return ProviderKey(
        user_id=user_id,
        provider_id=provider_id,
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

    row = (await session.execute(select(ProviderKey))).scalar_one()
    assert row.provider_id == "nebius"
    assert row.last4 == "cdef"
    assert row.key_version == 1
    assert row.base_url is None
    assert row.created_at is not None
    assert row.updated_at is not None


async def test_second_key_for_same_provider_is_rejected(session):
    user = await make_user(session, "auth0|alice")
    session.add(key_row(user.id))
    await session.commit()

    session.add(key_row(user.id, api_key="nb-other-key-9999"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_same_user_two_different_providers_is_fine(session):
    user = await make_user(session, "auth0|alice")
    session.add(key_row(user.id, provider_id="nebius"))
    session.add(key_row(user.id, provider_id="nvidia", api_key="nvapi-other-key-9999"))
    await session.commit()

    rows = (await session.execute(select(ProviderKey))).scalars().all()
    assert {row.provider_id for row in rows} == {"nebius", "nvidia"}


async def test_key_requires_existing_user(session):
    session.add(key_row(uuid.uuid4()))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_keyless_local_provider_has_no_key_fields(session):
    user = await make_user(session, "auth0|alice")
    row = ProviderKey(
        user_id=user.id,
        provider_id="custom",
        base_url="http://localhost:11434/v1/",
    )
    session.add(row)
    await session.commit()

    saved = (await session.execute(select(ProviderKey))).scalar_one()
    assert saved.ciphertext is None
    assert saved.last4 is None
    assert saved.base_url == "http://localhost:11434/v1/"


async def test_record_copied_to_another_user_fails_to_decrypt(session):
    alice = await make_user(session, "auth0|alice")
    bob = await make_user(session, "auth0|bob")
    secret = encrypt_secret(MASTER_KEY, alice.id, "nebius", "nb-alices-key-0000")

    with pytest.raises(DecryptionError):
        decrypt_secret(MASTER_KEY, bob.id, "nebius", secret)


async def test_record_copied_to_another_provider_of_same_user_fails_to_decrypt(session):
    alice = await make_user(session, "auth0|alice")
    secret = encrypt_secret(MASTER_KEY, alice.id, "nebius", "nb-alices-key-0000")

    with pytest.raises(DecryptionError):
        decrypt_secret(MASTER_KEY, alice.id, "nvidia", secret)
