"""Demo mode on the backend: sessions, expiry, cleanup, held keys, isolation."""

import asyncio
import base64
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import get_jwks_cache, get_or_create_user
from app.db import create_engine
from app.demo import cleanup_loop, delete_expired_demo_users, hash_session_value
from app.main import app
from app.models import Conversation, ProviderKey, User, UserSettings
from app.providers import get_provider_http_client
from tests.chat_helpers import PROVIDERS_FIXTURE, run_db, seed_conversation
from tests.conftest import FakeProvider, TEST_ISSUER

VALID_KEY = "nb-demo-valid-key-1234"
MODELS_OK = {"object": "list", "data": [{"id": "vendor/nano-model", "object": "model"}]}


def accepting(*keys: str) -> FakeProvider:
    def respond(request: httpx2.Request) -> httpx2.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token in keys:
            return httpx2.Response(200, json=MODELS_OK)
        return httpx2.Response(401, json={"error": "invalid key"})

    return FakeProvider(respond)


@pytest.fixture
def demo_env(settings_env):
    settings_env.setenv("AUTH_MODE", "demo")
    settings_env.delenv("OIDC_ISSUER")
    settings_env.delenv("OIDC_CLIENT_ID")
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    return settings_env


@pytest.fixture
def fake(demo_env):
    provider = accepting(VALID_KEY)
    app.dependency_overrides[get_provider_http_client] = lambda: provider.http_client()
    return provider


@pytest.fixture
def client(demo_env, test_database_url, fake):
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def start(client) -> dict:
    response = client.post("/api/demo/sessions")
    assert response.status_code == 201, response.text
    return response.json()


def bearer(value: str) -> dict:
    return {"Authorization": f"Bearer {value}"}


def held(**keys: str) -> dict:
    expires = (datetime.now(UTC) + timedelta(minutes=30)).isoformat()
    payload = {provider: {"key": key, "expires_at": expires} for provider, key in keys.items()}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return {"X-Provider-Keys": encoded}


def all_users(url):
    async def work(session):
        return (await session.execute(select(User))).scalars().all()

    return run_db(url, work)


def expire(url, subject_hash: str):
    async def work(session):
        await session.execute(
            update(User)
            .where(User.subject == subject_hash)
            .values(expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await session.commit()

    run_db(url, work)


# --- 5.1 Session routes -------------------------------------------------------


def test_session_value_has_32_random_bytes_and_only_its_hash_is_stored(client, test_database_url):
    first = start(client)
    second = start(client)

    raw = base64.urlsafe_b64decode(first["session"] + "=" * (-len(first["session"]) % 4))
    assert len(raw) == 32
    assert first["session"] != second["session"]

    users = all_users(test_database_url)
    assert {u.subject for u in users} == {
        hashlib.sha256(first["session"].encode()).hexdigest(),
        hashlib.sha256(second["session"].encode()).hexdigest(),
    }
    for user in users:
        assert user.issuer == "demo"
        assert first["session"] not in (user.subject, str(user.id))
        assert second["session"] not in (user.subject, str(user.id))


def test_session_expires_after_the_configured_hours(demo_env, test_database_url, fake):
    demo_env.setenv("DEMO_SESSION_TTL_HOURS", "2")
    with TestClient(app) as client:
        body = start(client)
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert abs(expires_at - (datetime.now(UTC) + timedelta(hours=2))) < timedelta(minutes=1)
    app.dependency_overrides.clear()


def test_max_sessions_gives_demo_full(demo_env, test_database_url, fake):
    demo_env.setenv("DEMO_MAX_SESSIONS", "2")
    with TestClient(app) as client:
        first = start(client)
        start(client)
        response = client.post("/api/demo/sessions")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "demo_full"

        # An expired session no longer counts.
        expire(test_database_url, hash_session_value(first["session"]))
        assert client.post("/api/demo/sessions").status_code == 201
    app.dependency_overrides.clear()


def test_me_reports_mode_expiry_and_notice(client):
    value = start(client)["session"]

    me = client.get("/api/me", headers=bearer(value)).json()
    assert me["mode"] == "demo"
    assert me["demo_notice_accepted"] is False
    assert me["expires_at"]

    assert client.post("/api/demo/notice", headers=bearer(value)).status_code == 204
    assert client.get("/api/me", headers=bearer(value)).json()["demo_notice_accepted"] is True


def test_ending_a_session_deletes_the_user_and_their_data(client, test_database_url):
    value = start(client)["session"]
    other = start(client)["session"]
    seed_conversation(test_database_url, client, bearer(value))
    seed_conversation(test_database_url, client, bearer(other))

    assert client.delete("/api/demo/session", headers=bearer(value)).status_code == 204

    subjects = {u.subject for u in all_users(test_database_url)}
    assert subjects == {hash_session_value(other)}

    async def conversations(session):
        return (await session.execute(select(func.count()).select_from(Conversation))).scalar_one()

    assert run_db(test_database_url, conversations) == 1
    response = client.get("/api/me", headers=bearer(value))
    assert response.status_code == 401


@pytest.fixture
def oidc_client(test_database_url, jwks_cache):
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def test_demo_routes_are_404_in_other_modes(oidc_client, make_token):
    headers = bearer(make_token(sub="real-user"))
    for method, path in [
        ("post", "/api/demo/sessions"),
        ("delete", "/api/demo/session"),
        ("post", "/api/demo/notice"),
    ]:
        response = getattr(oidc_client, method)(path, headers=headers)
        assert response.status_code == 404, (method, path)
        assert response.json()["error"]["code"] == "not_found"
    assert set(oidc_client.get("/api/me", headers=headers).json()) == {"id", "created_at"}


# --- 5.2 DemoAuthenticator ------------------------------------------------------


def test_live_value_finds_its_user(client):
    value = start(client)["session"]
    first = client.get("/api/me", headers=bearer(value)).json()
    second = client.get("/api/me", headers=bearer(value)).json()
    assert first["id"] == second["id"]


def test_expired_value_is_refused_before_cleanup_runs(client, test_database_url):
    value = start(client)["session"]
    expire(test_database_url, hash_session_value(value))

    response = client.get("/api/me", headers=bearer(value))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "demo_session_expired"
    # The row is still there: cleanup has not run.
    assert len(all_users(test_database_url)) == 1


def test_unknown_value_or_missing_credential_is_unauthenticated(client, make_token):
    for headers in ({}, bearer("not-a-session"), bearer(make_token())):
        response = client.get("/api/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"


def test_demo_value_is_refused_in_oidc_mode(oidc_client):
    # The same value shape a demo session uses.
    value = base64.urlsafe_b64encode(b"x" * 32).rstrip(b"=").decode()
    response = oidc_client.get("/api/me", headers=bearer(value))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


# --- 5.3 Cleanup ------------------------------------------------------------------


def test_cleanup_deletes_expired_demo_users_and_their_data_only(test_database_url):
    now = datetime.now(UTC)

    async def work(session):
        expired = User(issuer="demo", subject="expired", expires_at=now - timedelta(seconds=1))
        live = User(issuer="demo", subject="live", expires_at=now + timedelta(hours=1))
        session.add_all([expired, live])
        await session.flush()
        real = await get_or_create_user(session, TEST_ISSUER, "real")
        for user in (expired, live, real):
            session.add(Conversation(user_id=user.id, title="t"))
            session.add(UserSettings(user_id=user.id))
        await session.commit()
        deleted = await delete_expired_demo_users(session)
        subjects = set((await session.execute(select(User.subject))).scalars())
        owners = set((await session.execute(select(Conversation.user_id))).scalars())
        settings_rows = (await session.execute(select(func.count()).select_from(UserSettings))).scalar_one()
        return deleted, subjects, owners, {live.id, real.id}, settings_rows

    deleted, subjects, owners, kept_ids, settings_rows = run_db(test_database_url, work)
    assert deleted == 1
    assert subjects == {"live", "real"}
    assert owners == kept_ids
    assert settings_rows == 2


async def test_cleanup_keeps_running_after_an_error(test_database_url):
    engine = create_engine(test_database_url, poolclass=NullPool)
    real_sessions = async_sessionmaker(engine, expire_on_commit=False)
    rounds = {"count": 0}

    def sessionmaker():
        rounds["count"] += 1
        if rounds["count"] == 1:
            raise RuntimeError("database hiccup")
        return real_sessions

    async with real_sessions() as session:
        session.add(
            User(issuer="demo", subject="gone", expires_at=datetime.now(UTC) - timedelta(hours=1))
        )
        await session.commit()

    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await cleanup_loop(sessionmaker, interval_seconds=300, sleep=fake_sleep)

    async with real_sessions() as session:
        remaining = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    await engine.dispose()
    assert rounds["count"] == 3
    assert sleeps == [300, 300, 300]
    assert remaining == 0


def test_cleanup_task_runs_every_five_minutes_in_demo_mode():
    from app.demo import CLEANUP_INTERVAL_SECONDS

    assert CLEANUP_INTERVAL_SECONDS == 300


# --- 5.4 Keys sent with the request ------------------------------------------------


def provider_key_rows(url) -> int:
    async def work(session):
        return (await session.execute(select(func.count()).select_from(ProviderKey))).scalar_one()

    return run_db(url, work)


def test_saving_a_key_checks_it_and_writes_no_row(client, fake, test_database_url):
    value = start(client)["session"]

    response = client.put("/api/providers/nebius/key", headers=bearer(value), json={"key": VALID_KEY})

    assert response.status_code == 200
    body = response.json()
    assert body["key_held"] is True
    assert body["key_last4"] == VALID_KEY[-4:]
    assert VALID_KEY not in response.text
    assert fake.requests[0].headers["Authorization"] == f"Bearer {VALID_KEY}"
    assert provider_key_rows(test_database_url) == 0


def test_a_rejected_key_is_refused_in_demo_mode(client, test_database_url):
    value = start(client)["session"]
    response = client.put("/api/providers/nebius/key", headers=bearer(value), json={"key": "wrong-key-0000"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "provider_key_invalid"
    assert provider_key_rows(test_database_url) == 0


def test_provider_list_reports_held_keys_with_last4_and_expiry(client):
    value = start(client)["session"]

    response = client.get("/api/providers", headers={**bearer(value), **held(nebius=VALID_KEY)})

    nebius = next(p for p in response.json()["providers"] if p["id"] == "nebius")
    assert nebius["key_saved"] is True
    assert nebius["key_held"] is True
    assert nebius["key_last4"] == VALID_KEY[-4:]
    assert nebius["key_expires_at"]
    assert VALID_KEY not in response.text
    assert response.json()["custom_provider_allowed"] is False
    assert all(not p["is_custom"] for p in response.json()["providers"])

    without = client.get("/api/providers", headers=bearer(value)).json()
    assert next(p for p in without["providers"] if p["id"] == "nebius")["key_saved"] is False


def test_provider_calls_use_the_held_key(client, fake):
    value = start(client)["session"]

    missing = client.get("/api/providers/nebius/models", headers=bearer(value))
    assert missing.status_code == 409
    assert missing.json()["error"]["code"] == "provider_key_missing"

    response = client.get(
        "/api/providers/nebius/models", headers={**bearer(value), **held(nebius=VALID_KEY)}
    )
    assert response.status_code == 200
    assert fake.requests[-1].headers["Authorization"] == f"Bearer {VALID_KEY}"


def test_custom_provider_is_refused_in_demo_mode(client, test_database_url):
    value = start(client)["session"]
    response = client.put(
        "/api/providers/custom/key",
        headers=bearer(value),
        json={"key": VALID_KEY, "base_url": "http://169.254.169.254/v1"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert provider_key_rows(test_database_url) == 0


def test_deleting_a_key_in_demo_mode_writes_nothing(client, test_database_url):
    value = start(client)["session"]
    assert client.delete("/api/providers/nebius/key", headers=bearer(value)).status_code == 204


def test_header_is_ignored_in_other_modes(oidc_client, make_token, settings_env, test_database_url):
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    fake = accepting(VALID_KEY)
    app.dependency_overrides[get_provider_http_client] = lambda: fake.http_client()
    headers = {**bearer(make_token(sub="real")), **held(nebius=VALID_KEY)}

    listed = oidc_client.get("/api/providers", headers=headers).json()
    nebius = next(p for p in listed["providers"] if p["id"] == "nebius")
    assert nebius["key_saved"] is False and nebius["key_held"] is False

    response = oidc_client.get("/api/providers/nebius/models", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "provider_key_missing"
    assert fake.requests == []


def test_no_log_entry_holds_a_held_key(client, caplog):
    value = start(client)["session"]
    headers = {**bearer(value), **held(nebius=VALID_KEY)}
    with caplog.at_level(logging.DEBUG):
        client.get("/api/providers/nebius/models", headers=headers)
        client.get("/api/providers", headers=headers)
        client.put("/api/providers/nebius/key", headers=bearer(value), json={"key": VALID_KEY})
    assert caplog.records
    assert VALID_KEY not in caplog.text
    for record in caplog.records:
        assert VALID_KEY not in record.getMessage()


# --- 5.5 Isolation between visitors -------------------------------------------------


def test_visitor_a_gets_404_for_visitor_b_records(client, test_database_url):
    a = bearer(start(client)["session"])
    b = bearer(start(client)["session"])
    b_conversation = seed_conversation(test_database_url, client, b, title="B's secret")

    for method, path in [
        ("get", f"/api/conversations/{b_conversation}"),
        ("patch", f"/api/conversations/{b_conversation}"),
        ("delete", f"/api/conversations/{b_conversation}"),
    ]:
        kwargs = {"json": {"title": "stolen"}} if method == "patch" else {}
        response = getattr(client, method)(path, headers=a, **kwargs)
        assert response.status_code == 404, (method, path, response.text)
        assert "B's secret" not in response.text

    # B's conversation is untouched and still B's.
    assert client.get(f"/api/conversations/{b_conversation}", headers=b).json()["title"] == "B's secret"
    listed = client.get("/api/conversations", headers=a).json()
    assert "B's secret" not in json.dumps(listed)


def test_visitor_a_sees_only_their_own_settings_and_usage(client, test_database_url):
    a = bearer(start(client)["session"])
    b = bearer(start(client)["session"])
    b_id = uuid.UUID(client.get("/api/me", headers=b).json()["id"])

    async def give_b_settings_and_usage(session):
        from app.models import UsageEvent

        session.add(UserSettings(user_id=b_id, temperature=1.3))
        session.add(
            UsageEvent(user_id=b_id, provider_id="nebius", model="vendor/nano-model", kind="chat",
                       prompt_tokens=500, completion_tokens=50)
        )
        await session.commit()

    run_db(test_database_url, give_b_settings_and_usage)

    a_settings = client.get("/api/settings/models", headers=a).json()
    b_settings = client.get("/api/settings/models", headers=b).json()
    assert b_settings["temperature"] == 1.3
    assert a_settings["temperature"] is None

    a_usage = client.get("/api/usage", headers=a).json()
    b_usage = client.get("/api/usage", headers=b).json()
    assert a_usage["by_model"] == [] and a_usage["month"]["calls"] == 0
    assert b_usage["month"]["calls"] == 1 and b_usage["month"]["tokens"] == 550
