"""The instance items of the setup status (openspec self-hosting-setup design decision 7).

Each item has an id, a state (ok, missing, failed, warning, or info), whether
it is required, a message in plain words, and the environment variables that
set it. The status endpoint and the doctor build these from the settings, a
database connection, and the loaded configuration files, and nothing else:
no outbound call, and no secret value in any message. A URL in a message goes
through redact_url, and a database failure is a fixed message plus the
exception's class name, never the driver's text (which can hold the URL and
its password).
"""

import asyncio
import re
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import Settings
from app.provider_config import ProvidersConfig
from app.thoughts import MIN_PGVECTOR, _version

State = Literal["ok", "missing", "failed", "warning", "info"]

DATABASE_TIMEOUT_SECONDS = 5.0

LOGIN_SETTINGS = {
    "oidc": [
        "AUTH_MODE",
        "OIDC_ISSUER",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET",
        "OIDC_INTERNAL_URL",
    ],
    "firebase": ["AUTH_MODE", "FIREBASE_PROJECT_ID", "FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN"],
    "demo": ["AUTH_MODE"],
}
CONNECTOR_SETTINGS = ["MCP_ENABLED", "MCP_USER_CONNECTORS", "MCP_CONNECTORS_PATH"]


_QUERY_START = re.compile(r"[?#]")


class SetupItem(BaseModel):
    id: str
    state: State
    required: bool
    message: str
    settings: list[str]


def redact_url(url: str, *, mask_password: bool = False) -> str:
    """The URL with only its scheme, host, port, and path.

    The userinfo (user:pass@), the query string, and the fragment are dropped,
    so neither a password nor a ?password= or ?token= value is shown. With
    mask_password, a user name is kept and its password shown as ***, as the
    doctor's database line does.

    Parsing is deliberately cautious: the userinfo is taken to end at the last
    "@" before the query, or, when the query holds the only "@", at the last
    "@" anywhere, so an unencoded "?" or "/" in a password cannot leak part
    of it as the host.
    """
    url = url.strip()
    scheme, separator, rest = url.partition("://")
    if not separator:
        # Not an absolute URL: show nothing that could be a secret.
        return "(not a URL)"
    before_query = _QUERY_START.split(rest, 1)[0]
    at = before_query.rfind("@")
    if at < 0:
        at = rest.rfind("@")
    userinfo, location = (rest[:at], rest[at + 1:]) if at >= 0 else ("", rest)
    location = _QUERY_START.split(location, 1)[0]
    shown_user = ""
    if mask_password and userinfo:
        user, has_password, _password = userinfo.partition(":")
        shown_user = f"{user}:***@" if has_password else f"{user}@"
    return f"{scheme}://{shown_user}{location}"


def origin_of(url: str) -> str:
    """Only the scheme, host, and port of a URL (for connector URLs)."""
    redacted = redact_url(url)
    scheme, separator, rest = redacted.partition("://")
    if not separator:
        return redacted
    return f"{scheme}://{rest.split('/', 1)[0]}"


# database


Connect = Callable[[], AbstractAsyncContextManager[AsyncConnection]]


async def _pgvector_version(connection: AsyncConnection) -> str | None:
    return (
        await connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
    ).scalar()


async def _probe_database(connect: Connect) -> tuple[str, str | None]:
    """The dialect name and, on Postgres, the pgvector version (None when missing)."""
    async with connect() as connection:
        await connection.execute(text("SELECT 1"))
        dialect = connection.dialect.name
        if dialect != "postgresql":
            return dialect, None
        return dialect, await _pgvector_version(connection)


def _database_item(state: State, message: str) -> SetupItem:
    return SetupItem(
        id="database", state=state, required=True, message=message, settings=["DATABASE_URL"]
    )


def database_timeout_item(timeout: float = DATABASE_TIMEOUT_SECONDS) -> SetupItem:
    return _database_item(
        "failed",
        f"The database did not answer within {timeout:g} seconds (TimeoutError). "
        "Check that Postgres is running and DATABASE_URL points at it.",
    )


def database_error_item(exc: BaseException) -> SetupItem:
    # The class name only: a driver's message can hold the URL and its password.
    return _database_item(
        "failed",
        f"Could not connect to the database ({type(exc).__name__}). "
        "Check that Postgres is running and DATABASE_URL is right.",
    )


def database_answer_item(dialect: str, version: str | None) -> SetupItem:
    """The item for a database that answered, given its pgvector version."""
    if dialect != "postgresql":
        return _database_item("ok", "The database answers.")
    minimum = ".".join(map(str, MIN_PGVECTOR))
    if version is None:
        return _database_item(
            "failed",
            "Postgres answers, but the pgvector extension ('vector') is not installed in this "
            "database. Use a Postgres with pgvector, such as the pgvector/pgvector image.",
        )
    if _version(version) < MIN_PGVECTOR:
        return _database_item(
            "failed",
            f"Postgres answers, but pgvector is version {version}; search needs {minimum} "
            "or later. Upgrade pgvector and run ALTER EXTENSION vector UPDATE.",
        )
    return _database_item("ok", f"Postgres answers and has pgvector {version}.")


def database_not_migrated_item(available: str | None) -> SetupItem:
    """The item for a Postgres not migrated yet, whose 'vector' extension is not created.

    The first migration creates the extension, so what matters before then is
    whether the server can install it (pg_available_extensions).
    """
    minimum = ".".join(map(str, MIN_PGVECTOR))
    if available is None:
        return _database_item(
            "failed",
            "Postgres answers, but the pgvector extension ('vector') is not available on "
            "this server. Use a Postgres with pgvector, such as the pgvector/pgvector image.",
        )
    if _version(available) < MIN_PGVECTOR:
        return _database_item(
            "failed",
            f"Postgres answers, but its pgvector is version {available}; search needs "
            f"{minimum} or later. Use a newer pgvector/pgvector image.",
        )
    return _database_item(
        "warning",
        f"Postgres answers and has pgvector {available} available. The database is not "
        "migrated yet; the backend creates the extension when it starts.",
    )


async def database_item(
    connect: Connect, *, timeout: float = DATABASE_TIMEOUT_SECONDS
) -> SetupItem:
    """Whether the database answers and, on Postgres, has a recent enough pgvector.

    SQLite (used by the tests only) is checked for an answer alone, as the
    startup pgvector check does.
    """
    try:
        dialect, version = await asyncio.wait_for(_probe_database(connect), timeout)
    except TimeoutError:
        return database_timeout_item(timeout)
    except Exception as exc:  # noqa: BLE001 - every cause is reported, by class only
        return database_error_item(exc)
    return database_answer_item(dialect, version)


# settings


def encryption_key_item() -> SetupItem:
    # The server does not start without a valid key, so while it answers the
    # key is set. Its value is never shown.
    return SetupItem(
        id="encryption_key",
        state="ok",
        required=True,
        message=(
            "The key encryption key is set. Keep a copy of KEY_ENCRYPTION_KEY somewhere safe: "
            "without it no saved provider key can be read."
        ),
        settings=["KEY_ENCRYPTION_KEY"],
    )


def login_item(settings: Settings, *, state: State = "ok") -> SetupItem:
    """The auth mode and its non-secret values. The status reports it ok (the
    caller logged in); the doctor, which has no caller, reports it as info."""
    mode = settings.auth_mode or ""
    if mode == "oidc":
        message = (
            f"OpenID Connect: issuer {redact_url(settings.oidc_issuer or '')}, "
            f"client id {settings.oidc_client_id}."
        )
        if settings.oidc_internal_url:
            message += (
                " The servers reach the issuer at "
                f"{redact_url(settings.oidc_internal_url)} (OIDC_INTERNAL_URL)."
            )
    elif mode == "firebase":
        message = f"Firebase: project {settings.firebase_project_id}."
    else:
        message = "Demo mode: no login provider; each visitor gets a temporary account."
    message += " Change these in .env and restart both servers."
    return SetupItem(
        id="login",
        state=state,
        required=True,
        message=message,
        settings=list(LOGIN_SETTINGS.get(mode, ["AUTH_MODE"])),
    )


def allow_list_item(settings: Settings) -> SetupItem:
    entries = settings.allowed_emails
    if settings.auth_mode == "demo":
        state: State = "info"
        message = "Demo mode does not use an allow-list."
    elif entries:
        state = "ok"
        message = f"Allow-list: {', '.join(sorted(entries))}."
    else:
        state = "warning"
        if settings.auth_mode == "firebase":
            message = (
                "Allow-list: none set. Anyone who can sign in to the Firebase project can use "
                "this instance."
            )
        else:
            message = (
                "Allow-list: none set. Anyone your login provider lets in can use this instance."
            )
        message += " Set AUTH_ALLOWED_EMAILS to limit it."
    return SetupItem(
        id="allow_list",
        state=state,
        required=False,
        message=message,
        settings=["AUTH_ALLOWED_EMAILS"],
    )


def custom_provider_item(settings: Settings, providers: ProvidersConfig) -> SetupItem:
    labels = ", ".join(preset.label for preset in providers.providers.values())
    custom = (
        "Users may also add a custom provider (any OpenAI-compatible address)."
        if settings.allow_custom_provider
        else "Custom providers are turned off."
    )
    return SetupItem(
        id="custom_provider",
        state="info",
        required=False,
        message=f"Provider presets: {labels}. {custom}",
        settings=["PROVIDERS_CONFIG_PATH", "ALLOW_CUSTOM_PROVIDER"],
    )


def load_connector_config() -> Any:
    # The connectors loader comes with the mcp-connectors change; it is read
    # only when connectors are on.
    from app.connector_config import (
        get_connector_config,  # type: ignore[import-not-found]
    )

    return get_connector_config()


def connectors_item(
    settings: Any, load_config: Callable[[], Any] = load_connector_config
) -> SetupItem:
    """Off, or on with the operator connector count and whether users may add their own.

    The MCP settings are read with getattr, so this works on a server built
    without them (connectors then read as off).
    """
    if not getattr(settings, "mcp_enabled", False):
        message = "Connectors are off."
    else:
        connectors: Sequence[Any] = load_config().connectors
        count = len(connectors)
        noun = "connector" if count == 1 else "connectors"
        users = (
            "Users may add their own."
            if getattr(settings, "mcp_user_connectors", False)
            else "Users may not add their own."
        )
        message = f"Connectors are on: {count} operator {noun}. {users}"
    return SetupItem(
        id="connectors",
        state="info",
        required=False,
        message=message,
        settings=list(CONNECTOR_SETTINGS),
    )
