import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import create_engine
from app.models import Base, User


@pytest.fixture
async def session():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def test_user_gets_id_and_created_at(session):
    session.add(User(issuer="test-issuer", subject="user|alice"))
    await session.commit()

    user = (await session.execute(select(User))).scalar_one()
    assert user.id is not None
    assert user.created_at is not None


async def test_duplicate_issuer_and_subject_is_rejected(session):
    session.add(User(issuer="test-issuer", subject="user|alice"))
    await session.commit()

    session.add(User(issuer="test-issuer", subject="user|alice"))
    with pytest.raises(IntegrityError):
        await session.commit()
