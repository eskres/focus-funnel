import asyncio

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import get_current_user, get_jwks_cache, get_or_create_user
from app.db import create_engine
from app.errors import ApiError, register_error_handlers
from app.models import Conversation, User
from app.ownership import get_owned_or_404
from tests.conftest import TEST_ISSUER, count_users


@pytest.fixture
def client(test_database_url, jwks_cache):
    test_app = FastAPI()
    register_error_handlers(test_app)

    @test_app.get("/whoami")
    async def whoami(user: User = Depends(get_current_user)):
        return {"id": str(user.id), "issuer": user.issuer, "subject": user.subject}

    test_app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    with TestClient(test_app) as client:
        yield client


def whoami(client, token):
    return client.get("/whoami", headers={"Authorization": f"Bearer {token}"})


def test_first_request_creates_one_user(client, test_database_url, make_token):
    response = whoami(client, make_token(sub="user|new-user"))

    assert response.status_code == 200
    assert response.json()["subject"] == "user|new-user"
    assert count_users(test_database_url, "user|new-user") == 1


def test_repeat_requests_reuse_the_user(client, test_database_url, make_token):
    first = whoami(client, make_token(sub="user|returning"))
    second = whoami(client, make_token(sub="user|returning"))

    assert first.json()["id"] == second.json()["id"]
    assert count_users(test_database_url, "user|returning") == 1


def test_different_subjects_get_different_users(client, test_database_url, make_token):
    alice = whoami(client, make_token(sub="user|alice")).json()
    bob = whoami(client, make_token(sub="user|bob")).json()

    assert alice["id"] != bob["id"]
    assert count_users(test_database_url) == 2


def test_no_user_created_without_valid_token(client, test_database_url):
    response = client.get("/whoami")

    assert response.status_code == 401
    assert count_users(test_database_url) == 0


def test_concurrent_first_requests_leave_one_user(test_database_url):
    async def run_concurrently():
        engine = create_engine(test_database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def first_request():
            async with sessions() as session:
                return await get_or_create_user(session, TEST_ISSUER, "user|racer")

        users = await asyncio.gather(*(first_request() for _ in range(5)))
        await engine.dispose()
        return users

    users = asyncio.run(run_concurrently())

    assert len({user.id for user in users}) == 1
    assert count_users(test_database_url, "user|racer") == 1


def test_same_subject_from_two_issuers_is_two_users_who_cannot_see_each_other(
    test_database_url,
):
    async def run():
        engine = create_engine(test_database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            pocket = await get_or_create_user(session, "http://localhost:1411", "shared-sub")
            firebase = await get_or_create_user(
                session, "https://securetoken.google.com/focus-funnel", "shared-sub"
            )
            conversation = Conversation(user_id=pocket.id, title="private")
            session.add(conversation)
            await session.commit()

            own = await get_owned_or_404(session, Conversation, conversation.id, pocket)
            with pytest.raises(ApiError) as error:
                await get_owned_or_404(session, Conversation, conversation.id, firebase)
        await engine.dispose()
        return pocket, firebase, own, error.value

    pocket, firebase, own, error = asyncio.run(run())
    assert pocket.id != firebase.id
    assert own.title == "private"
    assert error.status_code == 404
    assert count_users(test_database_url, "shared-sub") == 2
