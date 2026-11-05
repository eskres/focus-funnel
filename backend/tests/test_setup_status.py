"""GET /api/setup/status and POST /api/setup/complete (self-hosting-setup tasks 3.2 and 3.3)."""

import asyncio
import base64
import os
import uuid
from contextlib import asynccontextmanager

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import get_jwks_cache
from app.config import get_settings
from app.db import create_engine
from app.errors import ApiError
from app.main import app
from app.models import ChatModel, ProviderKey, SetupState, User
from app.provider_config import get_providers_config
from app.setup.state import open_setup
from app.setup.status import complete_setup
from tests.chat_helpers import (
    NANO,
    PROVIDERS_FIXTURE,
    FakeLLM,
    entry,
    error_code,
    ready_user,
    save_key,
    save_models,
)
from tests.conftest import CACHED
from tests.test_setup_token import printed_token, run, sessionmaker_for

NEBIUS_KEY = "nb-valid-key-aaaa1111"
LOCAL_ONLY = """\
providers:
  local:
    label: Local Test Server
    base_url: http://localhost:11434/v1/
    key_url: https://example.test/keys
    notice: Runs on your own machine; nothing leaves it.
    key_required: false
    capabilities:
      model_list: { prices: false, context_length: false, features: false }
      stream_usage: none
"""


@pytest.fixture
def local_only_file(tmp_path):
    path = tmp_path / "local-only.yaml"
    path.write_text(LOCAL_ONLY)
    return path


@pytest.fixture
def setup_env(test_database_url, settings_env):
    """Setup open: the row as the migration leaves it, the wizard on, and the providers fixture."""
    run(test_database_url, insert(SetupState).values(id=1))
    settings_env.setenv("SETUP_WIZARD", "true")
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    settings_env.delenv("APP_BASE_URL", raising=False)
    return settings_env


def start(jwks_cache):
    for cached in CACHED:
        cached.cache_clear()
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    FakeLLM().install()
    return TestClient(app)


@pytest.fixture
def setup(setup_env, test_database_url, jwks_cache, capsys):
    """A started app with setup open, and the token its lifespan printed."""
    try:
        with start(jwks_cache) as client:
            token = printed_token(capsys.readouterr().err)
            yield client, token
    finally:
        app.dependency_overrides.clear()


def get_status(client, headers, token):
    return client.get("/api/setup/status", headers={**headers, "X-Setup-Token": token})


def finish(client, headers, token):
    return client.post("/api/setup/complete", headers={**headers, "X-Setup-Token": token})


def items_of(response) -> dict[str, dict]:
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()["items"]}


def reload_settings():
    get_settings.cache_clear()
    get_providers_config.cache_clear()


# 3.2: GET /api/setup/status


def test_a_new_user_gets_the_instance_items_ok_and_the_user_items_missing(setup, alice):
    client, token = setup
    response = get_status(client, alice, token)
    items = items_of(response)
    assert response.json()["auth_mode"] == "oidc"
    assert response.json()["ready"] is False
    assert list(items) == [
        "database",
        "encryption_key",
        "login",
        "allow_list",
        "search_key",
        "chat_model",
        "custom_provider",
        "connectors",
    ]
    for item_id in ("database", "encryption_key", "login"):
        assert (items[item_id]["state"], items[item_id]["required"]) == ("ok", True)
    for item_id in ("search_key", "chat_model"):
        assert (items[item_id]["state"], items[item_id]["required"]) == ("missing", True)
    assert {item_id for item_id, item in items.items() if item["required"]} == {
        "database",
        "encryption_key",
        "login",
        "search_key",
        "chat_model",
    }
    assert "Nebius Token Factory" in items["search_key"]["message"]
    assert "default model" in items["chat_model"]["message"]
    assert items["allow_list"]["state"] == "warning"


def test_a_key_for_another_provider_leaves_search_key_missing(setup, alice):
    client, token = setup
    save_key(client, alice, "local", "local-key-1234")
    items = items_of(get_status(client, alice, token))
    assert items["search_key"]["state"] == "missing"
    assert "Search uses Nebius Token Factory" in items["search_key"]["message"]
    assert items["search_key"]["settings"] == ["EMBEDDING_PROVIDER", "EMBEDDING_MODEL"]


def test_a_keyless_embedding_preset_is_ok_with_no_row(setup_env, test_database_url, jwks_cache,
                                                      capsys, alice):
    setup_env.setenv("EMBEDDING_PROVIDER", "local")
    try:
        with start(jwks_cache) as client:
            token = printed_token(capsys.readouterr().err)
            items = items_of(get_status(client, alice, token))
    finally:
        app.dependency_overrides.clear()
    assert items["search_key"]["state"] == "ok"
    assert "needs no key" in items["search_key"]["message"]
    assert run(test_database_url, select(func.count()).select_from(ProviderKey)) == [(0,)]


def test_a_key_saved_under_another_encryption_key_is_failed(setup, alice, settings_env):
    client, token = setup
    ready_user(client, alice)
    assert items_of(get_status(client, alice, token))["search_key"]["state"] == "ok"
    settings_env.setenv("KEY_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    reload_settings()
    response = get_status(client, alice, token)
    items = items_of(response)
    for item_id in ("search_key", "chat_model"):
        assert items[item_id]["state"] == "failed"
        assert "cannot be read with the current KEY_ENCRYPTION_KEY" in items[item_id]["message"]
    assert response.json()["ready"] is False


def test_a_default_whose_preset_was_removed_is_missing(setup, alice, settings_env, local_only_file):
    client, token = setup
    ready_user(client, alice)
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(local_only_file))
    settings_env.setenv("EMBEDDING_PROVIDER", "local")
    reload_settings()
    response = get_status(client, alice, token)
    assert response.status_code == 200
    item = items_of(response)["chat_model"]
    assert item["state"] == "missing"
    assert "'nebius'" in item["message"]
    assert "no longer offers" in item["message"]


def test_a_custom_default_with_custom_turned_off_is_missing(setup, alice, settings_env):
    client, token = setup
    response = client.put(
        "/api/providers/custom/key",
        headers=alice,
        json={"key": "custom-key-9876", "base_url": "https://custom.test/v1/"},
    )
    assert response.status_code == 200, response.text
    response = save_models(client, alice, entry(NANO, provider_id="custom", default=True))
    assert response.status_code == 200, response.text
    assert items_of(get_status(client, alice, token))["chat_model"]["state"] == "ok"
    settings_env.setenv("ALLOW_CUSTOM_PROVIDER", "false")
    reload_settings()
    response = get_status(client, alice, token)
    assert response.status_code == 200
    item = items_of(response)["chat_model"]
    assert item["state"] == "missing"
    assert "custom" in item["message"]
    assert "turned off" in item["message"]


def test_a_default_model_with_a_usable_key_is_ready(setup, alice):
    client, token = setup
    ready_user(client, alice)
    response = get_status(client, alice, token)
    items = items_of(response)
    assert items["search_key"]["state"] == "ok"
    assert items["chat_model"]["state"] == "ok"
    assert NANO in items["chat_model"]["message"]
    assert response.json()["ready"] is True


def test_the_status_holds_no_secret(setup, alice, settings_env):
    client, token = setup
    ready_user(client, alice)
    response = get_status(client, alice, token)
    assert response.status_code == 200
    body = response.text
    key = os.environ["KEY_ENCRYPTION_KEY"]
    for secret in (NEBIUS_KEY, token, key, base64.b64decode(key).hex()):
        assert secret not in body
    assert "https://login.focus-funnel.test" in body
    assert "focus-funnel-test-client" in body


def test_the_status_makes_no_outbound_call(setup, alice, monkeypatch):
    client, token = setup
    ready_user(client, alice)

    async def refuse(*_args, **_kwargs):
        raise AssertionError("the status made an outbound call")

    monkeypatch.setattr(httpx.AsyncClient, "send", refuse)
    monkeypatch.setattr(httpx2.AsyncClient, "send", refuse)
    response = get_status(client, alice, token)
    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_with_the_wizard_off_the_status_is_404(setup_env, jwks_cache, capsys, alice):
    setup_env.setenv("SETUP_WIZARD", "false")
    try:
        with start(jwks_cache) as client:
            assert "Setup token" not in capsys.readouterr().err
            response = get_status(client, alice, "any-token")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
    assert error_code(response) == "not_found"


def test_with_the_wizard_off_and_a_keyless_file_a_user_saves_a_model_without_a_key(
    setup_env, test_database_url, jwks_cache, capsys, alice, local_only_file
):
    setup_env.setenv("SETUP_WIZARD", "false")
    setup_env.setenv("PROVIDERS_CONFIG_PATH", str(local_only_file))
    setup_env.setenv("EMBEDDING_PROVIDER", "local")
    try:
        with start(jwks_cache) as client:
            assert "Setup token" not in capsys.readouterr().err
            response = save_models(client, alice, entry(NANO, provider_id="local", default=True))
            assert response.status_code == 200, response.text
            loadout = client.get("/api/settings/models", headers=alice).json()
    finally:
        app.dependency_overrides.clear()
    assert [(m["provider_id"], m["model"], m["is_default"]) for m in loadout["models"]] == [
        ("local", NANO, True)
    ]
    assert run(test_database_url, select(func.count()).select_from(ProviderKey)) == [(0,)]


# 3.3: POST /api/setup/complete


def test_finishing_too_early_is_409_naming_the_default_model(setup, alice, test_database_url):
    client, token = setup
    save_key(client, alice)
    response = finish(client, alice, token)
    assert response.status_code == 409
    assert error_code(response) == "setup_incomplete"
    assert "default model" in response.json()["error"]["message"]
    # Setup stays open.
    assert get_status(client, alice, token).status_code == 200
    [(completed_at, token_hash)] = run(
        test_database_url, select(SetupState.completed_at, SetupState.token_hash)
    )
    assert completed_at is None
    assert token_hash is not None


def test_finishing_when_ready_closes_setup_for_good(setup, alice, test_database_url, capsys):
    client, token = setup
    ready_user(client, alice)
    response = finish(client, alice, token)
    assert response.status_code == 204, response.text
    assert response.content == b""
    assert "Setup is complete." in capsys.readouterr().err
    [(completed_at, token_hash)] = run(
        test_database_url, select(SetupState.completed_at, SetupState.token_hash)
    )
    assert completed_at is not None
    assert token_hash is None

    response = get_status(client, alice, token)
    assert response.status_code == 404
    assert error_code(response) == "not_found"
    assert finish(client, alice, token).status_code == 404

    # The next start prints no token.
    get_settings.cache_clear()
    asyncio.run(open_setup(get_settings(), sessionmaker_for(test_database_url)))
    assert capsys.readouterr().err == ""


@pytest.mark.postgres
def test_two_concurrent_finishes_give_one_204_and_one_404(
    test_database_url, settings_env, local_only_file
):
    """complete_setup holds the row lock; the second request waits, then finds setup closed."""
    settings_env.setenv("SETUP_WIZARD", "true")
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(local_only_file))
    settings_env.setenv("EMBEDDING_PROVIDER", "local")
    user_id = uuid.uuid4()
    run(test_database_url, insert(SetupState).values(id=1, token_hash="0" * 64))
    run(test_database_url, insert(User).values(id=user_id, issuer="https://i.test", subject="op"))
    run(
        test_database_url,
        insert(ChatModel).values(
            id=uuid.uuid4(), user_id=user_id, provider_id="local", model=NANO, is_default=True,
            position=0,
        ),
    )
    settings = get_settings()

    async def main():
        engine = create_engine(test_database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        locked = asyncio.Event()

        @asynccontextmanager
        async def slow_connect():
            # Called by the first request while it holds the row lock: keep
            # holding it while the second request asks for the row.
            locked.set()
            await asyncio.sleep(0.5)
            async with engine.connect() as connection:
                yield connection

        async def attempt(first: bool):
            async with sessions() as session:
                user = await session.get(User, user_id)
                if not first:
                    await locked.wait()
                try:
                    await complete_setup(
                        session, user, settings, slow_connect if first else engine.connect
                    )
                except ApiError as exc:
                    return exc.status_code
                return 204

        try:
            return await asyncio.gather(attempt(True), attempt(False))
        finally:
            await engine.dispose()

    results = asyncio.run(main())
    assert results == [204, 404]
    [(completed_at, token_hash)] = run(
        test_database_url, select(SetupState.completed_at, SetupState.token_hash)
    )
    assert completed_at is not None
    assert token_hash is None


def test_finish_needs_the_token(setup, alice):
    client, _token = setup
    ready_user(client, alice)
    for token in ("", "wrong"):
        response = finish(client, alice, token)
        assert response.status_code == 403
        assert error_code(response) == "setup_token_invalid"
    response = client.post("/api/setup/complete", headers=alice)
    assert response.status_code == 403


def test_status_route_order(setup, alice):
    """No login is 401 before the token is looked at."""
    client, token = setup
    response = client.get("/api/setup/status", headers={"X-Setup-Token": token})
    assert response.status_code == 401
    assert error_code(response) == "unauthenticated"
