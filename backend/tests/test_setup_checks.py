"""The setup status's instance items and URL redaction (self-hosting-setup task 3.1)."""

import asyncio
import base64
import os
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.db import create_engine
from app.provider_config import get_providers_config
from app.setup.checks import (
    allow_list_item,
    connectors_item,
    custom_provider_item,
    database_item,
    encryption_key_item,
    login_item,
    origin_of,
    redact_url,
)
from tests.chat_helpers import PROVIDERS_FIXTURE

CLIENT_SECRET = "oidc-client-secret-do-not-show-0123456789"


@pytest.fixture
def env(settings_env):
    settings_env.setenv("OIDC_CLIENT_SECRET", CLIENT_SECRET)
    settings_env.setenv("SESSION_SECRET", "s" * 64)
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    return settings_env


def firebase(env):
    env.setenv("AUTH_MODE", "firebase")
    env.delenv("OIDC_ISSUER")
    env.delenv("OIDC_CLIENT_ID")
    env.setenv("FIREBASE_PROJECT_ID", "focus-funnel-test-project")
    env.setenv("FIREBASE_API_KEY", "AIza-firebase-web-key")
    env.setenv("FIREBASE_AUTH_DOMAIN", "focus-funnel-test-project.firebaseapp.com")


# login


def test_oidc_login_names_the_issuer_client_id_and_settings(env):
    env.setenv("OIDC_INTERNAL_URL", "http://pocket-id:1411")
    item = login_item(Settings())
    assert (item.id, item.state, item.required) == ("login", "ok", True)
    assert "https://login.focus-funnel.test" in item.message
    assert "focus-funnel-test-client" in item.message
    assert "http://pocket-id:1411" in item.message
    assert item.settings == [
        "AUTH_MODE",
        "OIDC_ISSUER",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET",
        "OIDC_INTERNAL_URL",
    ]
    assert CLIENT_SECRET not in item.model_dump_json()


def test_firebase_login_names_the_project_and_settings(env):
    firebase(env)
    item = login_item(Settings())
    assert item.state == "ok"
    assert "focus-funnel-test-project" in item.message
    assert item.settings == [
        "AUTH_MODE",
        "FIREBASE_PROJECT_ID",
        "FIREBASE_API_KEY",
        "FIREBASE_AUTH_DOMAIN",
    ]


def test_the_doctor_reports_login_as_info(env):
    assert login_item(Settings(), state="info").state == "info"


def test_login_issuer_is_shown_without_userinfo_or_query(env):
    env.setenv("OIDC_ISSUER", "https://admin:issuer-pass@login.test:8443/realm?token=issuer-tok")
    item = login_item(Settings())
    assert "https://login.test:8443/realm" in item.message
    for secret in ("admin", "issuer-pass", "issuer-tok", "token="):
        assert secret not in item.message


# allow_list


def test_allow_list_set_is_ok_with_its_entries(env):
    env.setenv("AUTH_ALLOWED_EMAILS", "Ops@Example.org, @team.example.org")
    item = allow_list_item(Settings())
    assert (item.state, item.required) == ("ok", False)
    assert "ops@example.org" in item.message
    assert "@team.example.org" in item.message
    assert item.settings == ["AUTH_ALLOWED_EMAILS"]


def test_allow_list_unset_warns_for_oidc(env):
    item = allow_list_item(Settings())
    assert (item.state, item.required) == ("warning", False)
    assert "none set" in item.message
    assert "Anyone your login provider lets in can use this instance" in item.message
    assert "AUTH_ALLOWED_EMAILS" in item.message
    assert item.settings == ["AUTH_ALLOWED_EMAILS"]


def test_allow_list_unset_warns_for_firebase(env):
    firebase(env)
    item = allow_list_item(Settings())
    assert item.state == "warning"
    assert "Anyone who can sign in to the Firebase project" in item.message
    assert item.settings == ["AUTH_ALLOWED_EMAILS"]


# database


class LeakyError(Exception):
    """A driver error whose text holds the connection URL and its password."""


def raising(exc: BaseException):
    @asynccontextmanager
    async def connect():
        raise exc
        yield  # pragma: no cover

    return connect


def test_database_failure_is_a_fixed_message_with_the_class_name():
    leaky = LeakyError('password authentication failed: postgresql://ff:hunter2-pw@db/ff')
    item = asyncio.run(database_item(raising(leaky)))
    assert (item.id, item.state, item.required) == ("database", "failed", True)
    assert "Could not connect to the database (LeakyError)" in item.message
    assert "hunter2-pw" not in item.model_dump_json()
    assert "postgresql://" not in item.message
    assert item.settings == ["DATABASE_URL"]


def test_database_that_never_answers_times_out():
    @asynccontextmanager
    async def connect():
        await asyncio.sleep(30)
        yield  # pragma: no cover

    item = asyncio.run(database_item(connect, timeout=0.2))
    assert item.state == "failed"
    assert "did not answer" in item.message
    assert "TimeoutError" in item.message


def test_sqlite_database_answers(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}", poolclass=NullPool)
    item = asyncio.run(database_item(engine.connect))
    assert (item.state, item.message) == ("ok", "The database answers.")


@pytest.mark.postgres
def test_postgres_database_names_its_pgvector_version(test_database_url):
    async def main():
        engine = create_engine(test_database_url, poolclass=NullPool)
        try:
            return await database_item(engine.connect)
        finally:
            await engine.dispose()

    item = asyncio.run(main())
    assert item.state == "ok"
    assert item.message.startswith("Postgres answers and has pgvector ")


# redaction


def test_redact_url_drops_userinfo_and_query():
    url = "postgresql+asyncpg://user:pass@db:5432/focus_funnel?password=x&token=y"
    assert redact_url(url) == "postgresql+asyncpg://db:5432/focus_funnel"
    masked = redact_url(url, mask_password=True)
    assert masked == "postgresql+asyncpg://user:***@db:5432/focus_funnel"


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("https://login.example.org", "https://login.example.org"),
        ("https://login.example.org/realms/x#frag", "https://login.example.org/realms/x"),
        ("http://[::1]:1411/path?q=1", "http://[::1]:1411/path"),
        ("sqlite+aiosqlite:///data/app.sqlite3", "sqlite+aiosqlite:///data/app.sqlite3"),
        # Unencoded "/" and "?" in a password do not leak any of it.
        ("postgresql://u:pa/ss@db/ff", "postgresql://db/ff"),
        ("postgresql://u:pa?ss@db/ff", "postgresql://db/ff"),
        ("not a url with secret", "(not a URL)"),
    ],
)
def test_redact_url_cases(url, shown):
    assert redact_url(url) == shown


def test_origin_keeps_only_scheme_host_and_port():
    assert origin_of("https://bot:tok@mcp.example.org:8443/mcp/v1?token=secret") == (
        "https://mcp.example.org:8443"
    )


# connectors


def test_connectors_report_off(env):
    item = connectors_item(Settings())
    assert (item.id, item.state, item.required) == ("connectors", "info", False)
    assert item.message == "Connectors are off."
    assert item.settings == ["MCP_ENABLED", "MCP_USER_CONNECTORS", "MCP_CONNECTORS_PATH"]


def write_connectors(tmp_path, names: list[str]):
    """A real connectors.yaml with an operator connector per name."""
    lines = ["connectors:"]
    for name in names:
        lines += [f"  - name: {name}", f"    url: http://{name}-mcp:8000/mcp"]
    if not names:
        lines[0] += " []"
    path = tmp_path / "connectors.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("user_connectors", "names", "wording"),
    [
        ("false", ["wiki", "tracker"], "2 operator connectors. Users may not add their own."),
        ("true", ["wiki"], "1 operator connector. Users may add their own."),
        ("", [], "0 operator connectors. Users may not add their own."),
    ],
)
def test_connectors_report_on_with_count_and_user_connectors(
    env, tmp_path, user_connectors, names, wording
):
    # The real MCP settings and connectors.yaml loader (mcp-connectors), read
    # through Settings() and MCP_CONNECTORS_PATH.
    env.setenv("MCP_ENABLED", "true")
    env.setenv("MCP_USER_CONNECTORS", user_connectors)
    env.setenv("MCP_CONNECTORS_PATH", str(write_connectors(tmp_path, names)))
    item = connectors_item(Settings())
    assert item.state == "info"
    assert item.message == f"Connectors are on: {wording}"
    assert item.settings == ["MCP_ENABLED", "MCP_USER_CONNECTORS", "MCP_CONNECTORS_PATH"]


def test_connectors_off_do_not_read_the_connectors_file(env, tmp_path):
    # With MCP_ENABLED unset, a broken connectors.yaml is not read (mcp-connectors
    # design decision 14), so the item still reports off.
    broken = tmp_path / "connectors.yaml"
    broken.write_text("connectors: [{name: Bad Name}]\n", encoding="utf-8")
    env.setenv("MCP_CONNECTORS_PATH", str(broken))
    assert connectors_item(Settings()).message == "Connectors are off."


# no secrets


def test_no_instance_item_holds_a_secret(env, tmp_path):
    key = base64.b64encode(os.urandom(32)).decode()
    env.setenv("KEY_ENCRYPTION_KEY", key)
    env.setenv("AUTH_ALLOWED_EMAILS", "ops@example.org")
    settings = Settings()
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite3'}", poolclass=NullPool)
    items = [
        asyncio.run(database_item(engine.connect)),
        encryption_key_item(),
        login_item(settings),
        allow_list_item(settings),
        custom_provider_item(settings, get_providers_config()),
        connectors_item(settings),
    ]
    text = "\n".join(item.model_dump_json() for item in items)
    for secret in (key, settings.key_encryption_key.hex(), CLIENT_SECRET, "s" * 64):
        assert secret not in text
    assert "KEY_ENCRYPTION_KEY" in text  # named, never shown


def test_custom_provider_item_names_the_presets(env):
    item = custom_provider_item(Settings(), get_providers_config())
    assert item.state == "info"
    assert "Nebius Token Factory" in item.message
    assert "custom provider" in item.message
    env.setenv("ALLOW_CUSTOM_PROVIDER", "false")
    assert "turned off" in custom_provider_item(Settings(), get_providers_config()).message
