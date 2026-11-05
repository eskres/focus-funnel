"""Check an install from the command line, without starting the server.

  python -m app.doctor [--json]

In compose, with the same -f files the install runs with:

  docker compose run --rm --entrypoint python backend -m app.doctor
  docker compose run --rm --no-deps --entrypoint python backend -m app.doctor

It prints one line per check: its state (ok, missing, failed, warning, info,
or skipped), an id, and a message. The exit status is 1 when a check failed
and 0 otherwise. Each check gives up after 5 seconds.

The checks follow openspec self-hosting-setup design decision 11: settings,
configuration files, the setup status's instance items (built by
app.setup.checks, with the same messages), migrations, setup, the login
provider, the provider presets, and the operator connectors. The doctor never
imports app.main, so no lifespan runs and no setup token is made, and it
prints no secret: a settings error is built from the variable name and the
rule only, a URL is shown without userinfo or query string (the database
password as ***), and the setup token's hash is never read.
"""

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import httpx
import httpx2
from pydantic import BaseModel, ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.pool import NullPool

from app.auth import FIREBASE_JWKS_URL, OidcDiscovery
from app.chat.config import ChatConfigError, load_chat_config
from app.chat.config import get_config_path as chat_config_path
from app.config import Settings
from app.connector_config import (
    ConnectorConfig,
    ConnectorConfigError,
    OperatorConnector,
    load_connector_config,
)
from app.db import create_engine
from app.provider_config import (
    ProviderConfigError,
    ProviderPreset,
    ProvidersConfig,
    load_providers_config,
)
from app.provider_config import get_config_path as providers_config_path
from app.setup.checks import (
    CONNECTOR_SETTINGS,
    LOGIN_SETTINGS,
    SetupItem,
    allow_list_item,
    connectors_item,
    custom_provider_item,
    database_answer_item,
    database_error_item,
    database_not_migrated_item,
    database_timeout_item,
    encryption_key_item,
    login_item,
    origin_of,
    redact_url,
)
from app.thoughts.embeddings import EmbeddingConfigError, check_embedding_provider

CHECK_TIMEOUT_SECONDS = 5.0
# Disposing an engine whose connect was cancelled must not hang the doctor.
DISPOSE_TIMEOUT_SECONDS = 2.0
ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
NOT_MIGRATED = "The database is not migrated yet; the backend applies the migrations when it starts."
NEEDS_SETTINGS = "Skipped: needs valid settings (see the settings lines)."
NEEDS_DATABASE = "Skipped: the database did not answer."
VALUE_ERROR_PREFIX = "Value error, "
SETTING_NAME = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b")

DoctorState = Literal["ok", "missing", "failed", "warning", "info", "skipped"]


class DoctorItem(BaseModel):
    """A setup status item, whose state may also be skipped."""

    id: str
    state: DoctorState
    required: bool
    message: str
    settings: list[str]

    def line(self, width: int = 16) -> str:
        return f"{self.state:<8} {self.id:<{width}} {self.message}"


def item(
    id: str,
    state: DoctorState,
    message: str,
    settings: Sequence[str] = (),
    required: bool = True,
) -> DoctorItem:
    return DoctorItem(
        id=id, state=state, required=required, message=message, settings=list(settings)
    )


def from_setup(setup_item: SetupItem) -> DoctorItem:
    return DoctorItem(**setup_item.model_dump())


def skipped(
    id: str, message: str, settings: Sequence[str] = (), required: bool = True
) -> DoctorItem:
    return item(id, "skipped", message, settings, required)


# 1. settings


def _settings_error_message(error: Any) -> str:
    """The variable and the rule it breaks, never its value.

    Built only from the error's loc and msg: str(exc) and the error's input
    hold the bad value (a wrong KEY_ENCRYPTION_KEY, say).
    """
    name = ".".join(str(part) for part in error.get("loc", ())).upper()
    message = str(error.get("msg", "is not valid"))
    message = message.removeprefix(VALUE_ERROR_PREFIX)
    if name and not message.startswith(name):
        message = f"{name}: {message}"
    if not message.endswith("."):
        message += "."
    return message


def check_settings(
    build: Callable[[], Settings] = Settings,
) -> tuple[Settings | None, list[DoctorItem]]:
    try:
        settings = build()
    except ValidationError as exc:
        items = []
        for error in exc.errors(include_input=False, include_url=False):
            name = ".".join(str(part) for part in error.get("loc", ())).upper()
            message = _settings_error_message(error)
            if not name:
                # A rule across settings (AUTH_MODE and what each mode needs)
                # names its variable in its own message.
                found = SETTING_NAME.search(message)
                name = found.group(0) if found else ""
            items.append(item("settings", "failed", message, [name] if name else []))
        return None, items
    except Exception as exc:  # noqa: BLE001 - reported by class only, never its text
        return None, [
            item(
                "settings",
                "failed",
                f"The settings could not be read ({type(exc).__name__}).",
            )
        ]
    return settings, [item("settings", "ok", "The backend settings load.")]


# 2. configuration files


def check_config_files(
    settings: Settings | None,
    load_connectors: Callable[[], ConnectorConfig] = load_connector_config,
) -> tuple[ProvidersConfig | None, ConnectorConfig | None, list[DoctorItem]]:
    """The providers file (and the embedding preset), the chat file, and, when
    connectors are on, the connectors file. Each failure is its loader's own
    message, which names what is wrong and never a secret value."""
    items: list[DoctorItem] = []
    providers: ProvidersConfig | None = None
    try:
        providers = load_providers_config()
    except ProviderConfigError as exc:
        items.append(
            item("providers_file", "failed", str(exc), ["PROVIDERS_CONFIG_PATH"])
        )
    if providers is not None:
        names = ", ".join(providers.providers)
        message = f"{providers_config_path()} loads, with the presets {names}."
        state: DoctorState = "ok"
        if settings is not None:
            try:
                check_embedding_provider(settings, providers)
            except EmbeddingConfigError as exc:
                state, message = "failed", f"{exc}."
        items.append(
            item(
                "providers_file",
                state,
                message,
                ["PROVIDERS_CONFIG_PATH", "EMBEDDING_PROVIDER"],
            )
        )

    try:
        load_chat_config()
    except ChatConfigError as exc:
        items.append(item("chat_file", "failed", str(exc), ["CHAT_CONFIG_PATH"]))
    else:
        items.append(
            item(
                "chat_file", "ok", f"{chat_config_path()} loads.", ["CHAT_CONFIG_PATH"]
            )
        )

    connectors: ConnectorConfig | None = None
    if settings is not None and settings.mcp_enabled:
        try:
            connectors = load_connectors()
        except ConnectorConfigError as exc:
            # The loader's message names the connector and the unset auth.env
            # variable, never a value.
            items.append(
                item(
                    "connectors_file",
                    "failed",
                    str(exc),
                    CONNECTOR_SETTINGS,
                    required=False,
                )
            )
        except Exception as exc:  # noqa: BLE001 - reported by class only
            items.append(
                item(
                    "connectors_file",
                    "failed",
                    f"The connectors file could not be read ({type(exc).__name__}).",
                    CONNECTOR_SETTINGS,
                    required=False,
                )
            )
        else:
            count = len(connectors.connectors)
            items.append(
                item(
                    "connectors_file",
                    "ok",
                    f"The connectors file loads, with {count} operator connector(s).",
                    CONNECTOR_SETTINGS,
                    required=False,
                )
            )
    return providers, connectors, items


# 3-5. database, migrations, setup


@dataclass
class DatabaseFacts:
    dialect: str
    alembic_versions: list[str] | None  # None: no alembic_version table
    installed_pgvector: str | None
    available_pgvector: str | None
    setup_table: bool
    # (row present, completed) when the table exists; never the token hash.
    setup_row: tuple[bool, bool] | None


async def _read_facts(connection: AsyncConnection) -> DatabaseFacts:
    await connection.execute(text("SELECT 1"))
    dialect = connection.dialect.name
    tables = await connection.run_sync(
        lambda sync: set(inspect(sync).get_table_names())
    )
    versions = None
    if "alembic_version" in tables:
        versions = list(
            (
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalars()
        )
    installed = available = None
    if dialect == "postgresql":
        installed = (
            await connection.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
            )
        ).scalar()
        available = (
            await connection.execute(
                text(
                    "SELECT default_version FROM pg_available_extensions WHERE name = 'vector'"
                )
            )
        ).scalar()
    setup_row = None
    if "setup_state" in tables:
        completed = (
            await connection.execute(
                text("SELECT completed_at FROM setup_state WHERE id = 1")
            )
        ).first()
        setup_row = (
            completed is not None,
            completed is not None and completed[0] is not None,
        )
    return DatabaseFacts(
        dialect=dialect,
        alembic_versions=versions,
        installed_pgvector=installed,
        available_pgvector=available,
        setup_table="setup_state" in tables,
        setup_row=setup_row,
    )


async def probe_database(url: str, timeout: float) -> DatabaseFacts:
    """Connect once and read what the database, migrations, and setup lines need."""
    connect_args = {}
    if make_url(url).get_driver_name() == "asyncpg":
        connect_args["timeout"] = timeout
    engine = create_engine(url, poolclass=NullPool, connect_args=connect_args)
    try:
        async with engine.connect() as connection:
            return await _read_facts(connection)
    finally:
        with suppress(Exception):
            await asyncio.wait_for(engine.dispose(), DISPOSE_TIMEOUT_SECONDS)


def script_head() -> tuple[Any, str | None]:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    return script, script.get_current_head()


def migration_position(facts: DatabaseFacts) -> str:
    """ "missing", "head", "behind", or "unknown"."""
    if not facts.alembic_versions:
        return "missing"
    script, head = script_head()
    current = facts.alembic_versions[0]
    if len(facts.alembic_versions) == 1 and current == head:
        return "head"
    try:
        list(script.iterate_revisions(head, current))
    except Exception:  # noqa: BLE001 - a revision this backend does not know
        return "unknown"
    return "behind"


def migrations_item(facts: DatabaseFacts) -> DoctorItem:
    position = migration_position(facts)
    if position == "missing":
        return item("migrations", "warning", NOT_MIGRATED, ["DATABASE_URL"])
    script, head = script_head()
    current = facts.alembic_versions[0]
    if position == "head":
        return item(
            "migrations", "ok", f"The database is at the latest migration ({head})."
        )
    if position == "unknown":
        return item(
            "migrations",
            "failed",
            f"The database is at migration {current}, which this backend does not know "
            f"(its latest is {head}). Was it migrated by a newer version?",
        )
    behind = len(list(script.iterate_revisions(head, current)))
    noun = "migration" if behind == 1 else "migrations"
    return item(
        "migrations",
        "warning",
        f"The database is {behind} {noun} behind ({current}, latest {head}); "
        "the backend applies them when it starts.",
    )


def database_line(facts: DatabaseFacts, position: str) -> DoctorItem:
    not_migrated = position in ("missing", "behind")
    if (
        facts.dialect == "postgresql"
        and facts.installed_pgvector is None
        and not_migrated
    ):
        return from_setup(database_not_migrated_item(facts.available_pgvector))
    return from_setup(database_answer_item(facts.dialect, facts.installed_pgvector))


def setup_item(settings: Settings | None, facts: DatabaseFacts | None) -> DoctorItem:
    names = ["SETUP_WIZARD", "AUTH_MODE"]
    if settings is None:
        return skipped("setup", NEEDS_SETTINGS, names, required=False)
    if settings.auth_mode == "demo":
        return item(
            "setup", "info", "Setup is not used in demo mode.", names, required=False
        )
    if not settings.setup_wizard:
        return item(
            "setup", "info", "Setup is off (SETUP_WIZARD=false).", names, required=False
        )
    if facts is None:
        return skipped("setup", NEEDS_DATABASE, names, required=False)
    if not facts.setup_table:
        return item("setup", "warning", NOT_MIGRATED, names, required=False)
    present, completed = facts.setup_row or (False, False)
    if not present:
        return item(
            "setup",
            "warning",
            "The setup record is missing, so setup is closed. Only the migration creates it.",
            names,
            required=False,
        )
    if completed:
        return item("setup", "ok", "Setup is finished.", names, required=False)
    return item(
        "setup",
        "info",
        "Setup is open. Restart the backend to print a new setup token, then open /setup.",
        names,
        required=False,
    )


async def check_database(
    url: str | None, timeout: float
) -> tuple[DatabaseFacts | None, list[DoctorItem]]:
    """The database and migrations lines (decision 11 steps 3 and 4)."""
    if not url:
        return None, [
            item("database", "failed", "DATABASE_URL is not set.", ["DATABASE_URL"]),
            skipped("migrations", NEEDS_DATABASE),
        ]
    try:
        make_url(url)
        shown = redact_url(url, mask_password=True)
    except Exception as exc:  # noqa: BLE001 - its text would hold the URL
        return None, [
            item(
                "database",
                "failed",
                f"DATABASE_URL is not a database URL ({type(exc).__name__}).",
                ["DATABASE_URL"],
            ),
            skipped("migrations", NEEDS_DATABASE),
        ]
    try:
        facts = await asyncio.wait_for(probe_database(url, timeout), timeout)
    except TimeoutError:
        database = from_setup(database_timeout_item(timeout))
        facts = None
    except Exception as exc:  # noqa: BLE001 - reported by class only
        database = from_setup(database_error_item(exc))
        facts = None
    if facts is None:
        database.message = f"{shown}: {database.message}"
        return None, [database, skipped("migrations", NEEDS_DATABASE)]
    position = migration_position(facts)
    database = database_line(facts, position)
    database.message = f"{shown}: {database.message}"
    return facts, [database, migrations_item(facts)]


# 6-8. connections


def _error_name(exc: BaseException) -> str:
    if isinstance(exc, httpx.HTTPStatusError | httpx2.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


async def check_login_provider(
    settings: Settings | None,
    transport: httpx.AsyncBaseTransport | None = None,
    timeout: float = CHECK_TIMEOUT_SECONDS,
) -> DoctorItem:
    if settings is None:
        return skipped("login_provider", NEEDS_SETTINGS, ["AUTH_MODE"])
    mode = settings.auth_mode or ""
    names = LOGIN_SETTINGS.get(mode, ["AUTH_MODE"])
    if mode == "oidc":
        issuer = settings.oidc_issuer or ""
        discovery = OidcDiscovery(
            issuer, settings.oidc_internal_url, transport=transport
        )
        url = redact_url(discovery.discovery_url)
        try:
            document = await asyncio.wait_for(discovery.fetch_document(), timeout)
        except TimeoutError:
            return item(
                "login_provider",
                "failed",
                f"The issuer did not answer within {timeout:g} seconds at {url}.",
                names,
            )
        except Exception as exc:  # noqa: BLE001 - reported by class or status only
            return item(
                "login_provider",
                "failed",
                f"Could not fetch the discovery document from {url} ({_error_name(exc)}).",
                names,
            )
        named = document.get("issuer")
        # Exact, as the backend's token check compares `iss` with OIDC_ISSUER:
        # a trailing slash on one side only fails every login.
        if not isinstance(named, str) or named != issuer:
            shown = redact_url(named) if isinstance(named, str) else "no issuer"
            return item(
                "login_provider",
                "failed",
                f"The discovery document at {url} names {shown}, not OIDC_ISSUER "
                f"{redact_url(issuer)}. Set OIDC_ISSUER to the issuer's public address.",
                names,
            )
        return item("login_provider", "ok", f"The issuer answers at {url}.", names)
    if mode == "firebase":
        url = redact_url(FIREBASE_JWKS_URL)

        async def fetch() -> Any:
            async with httpx.AsyncClient(
                timeout=timeout, transport=transport
            ) as client:
                response = await client.get(FIREBASE_JWKS_URL)
                response.raise_for_status()
                return response.json()

        try:
            keys = await asyncio.wait_for(fetch(), timeout)
        except TimeoutError:
            return item(
                "login_provider",
                "failed",
                f"Google's signing keys did not arrive within {timeout:g} seconds from {url}.",
                names,
            )
        except Exception as exc:  # noqa: BLE001
            return item(
                "login_provider",
                "failed",
                f"Could not fetch Google's signing keys from {url} ({_error_name(exc)}).",
                names,
            )
        if not isinstance(keys, dict) or not keys.get("keys"):
            return item(
                "login_provider",
                "failed",
                f"{url} answered without signing keys.",
                names,
            )
        return item(
            "login_provider", "ok", f"Google's signing keys load from {url}.", names
        )
    return skipped(
        "login_provider", "Demo mode has no login provider.", names, required=False
    )


async def _get(
    url: str, transport: httpx2.AsyncBaseTransport | None, timeout: float
) -> httpx2.Response:
    async with httpx2.AsyncClient(timeout=timeout, transport=transport) as client:
        return await client.get(url)


def _model_ids(response: httpx2.Response) -> list[str] | None:
    try:
        body = response.json()
    except Exception:  # noqa: BLE001 - not a model list
        return None
    if not isinstance(body, dict) or "data" not in body:
        return None
    # Ollama answers "data": null while no model is pulled.
    data = body["data"] or []
    if not isinstance(data, list):
        return None
    return [str(model.get("id")) for model in data if isinstance(model, dict)]


async def check_provider(
    preset: ProviderPreset,
    settings: Settings,
    transport: httpx2.AsyncBaseTransport | None = None,
    timeout: float = CHECK_TIMEOUT_SECONDS,
) -> DoctorItem:
    """GET {base_url}models with no key: any HTTP answer is reachable."""
    embedding = preset.id == settings.embedding_provider
    id = f"provider:{preset.id}"
    names = ["PROVIDERS_CONFIG_PATH"] + (
        ["EMBEDDING_PROVIDER", "EMBEDDING_MODEL"] if embedding else []
    )
    url = f"{preset.base_url.rstrip('/')}/models"
    shown = redact_url(url)
    try:
        response = await asyncio.wait_for(_get(url, transport, timeout), timeout)
    except Exception as exc:  # noqa: BLE001 - reported by class only
        reason = (
            f"did not answer within {timeout:g} seconds"
            if isinstance(exc, TimeoutError)
            else f"did not answer ({type(exc).__name__})"
        )
        if embedding:
            return item(
                id,
                "failed",
                f"{preset.label} {reason} at {shown}. Search uses it (EMBEDDING_PROVIDER), "
                "so search cannot work.",
                names,
            )
        return item(
            id,
            "warning",
            f"{preset.label} {reason} at {shown}. Chat with its models will fail.",
            names,
            required=False,
        )
    message = f"{preset.label} answers at {shown} (HTTP {response.status_code})."
    state: DoctorState = "ok"
    if not preset.key_required:
        models = _model_ids(response)
        if models is not None:
            noun = "model" if len(models) == 1 else "models"
            listed = settings.embedding_model in models
            message += (
                f" It lists {len(models)} {noun}; EMBEDDING_MODEL {settings.embedding_model} "
                f"is {'' if listed else 'not '}among them."
            )
            if embedding and not listed:
                state = "warning"
                message += " Search needs it: add the model to the server."
    return item(id, state, message, names, required=embedding)


async def check_connector(
    connector: OperatorConnector,
    transport: httpx2.AsyncBaseTransport | None = None,
    timeout: float = CHECK_TIMEOUT_SECONDS,
) -> DoctorItem:
    """Any HTTP answer from an operator connector's URL is reachable. Only the
    URL's scheme, host, and port are shown: a connectors.yaml URL may carry
    user:pass@ or ?token= despite auth.env being the place for them."""
    name = connector.name
    shown = origin_of(connector.url)
    try:
        response = await asyncio.wait_for(
            _get(connector.url, transport, timeout), timeout
        )
    except Exception as exc:  # noqa: BLE001 - reported by class only
        reason = (
            f"did not answer within {timeout:g} seconds"
            if isinstance(exc, TimeoutError)
            else f"did not answer ({type(exc).__name__})"
        )
        return item(
            f"connector:{name}",
            "warning",
            f"Connector {name} {reason} at {shown}. Its tools will be unavailable.",
            CONNECTOR_SETTINGS,
            required=False,
        )
    return item(
        f"connector:{name}",
        "ok",
        f"Connector {name} answers at {shown} (HTTP {response.status_code}).",
        CONNECTOR_SETTINGS,
        required=False,
    )


# all checks


FRONTEND_LINE = item(
    "frontend",
    "info",
    "The frontend checks its own settings when it starts: see docker compose logs frontend.",
    required=False,
)


async def run_checks(
    *,
    login_transport: httpx.AsyncBaseTransport | None = None,
    http_transport: httpx2.AsyncBaseTransport | None = None,
    load_settings: Callable[[], Settings] = Settings,
    load_connectors: Callable[[], ConnectorConfig] = load_connector_config,
    timeout: float = CHECK_TIMEOUT_SECONDS,
) -> list[DoctorItem]:
    items: list[DoctorItem] = []

    # 1. settings
    settings, settings_items = check_settings(load_settings)
    items += settings_items

    # 2. configuration files
    providers, connectors, file_items = check_config_files(settings, load_connectors)
    items += file_items

    # 3-4. the instance items, with the database and migrations lines
    database_url = (
        settings.database_url
        if settings
        else os.environ.get("DATABASE_URL", "").strip()
    )
    facts, database_items = await check_database(database_url, timeout)
    items.append(database_items[0])
    if settings is None:
        items += [
            skipped("encryption_key", NEEDS_SETTINGS, ["KEY_ENCRYPTION_KEY"]),
            skipped("login", NEEDS_SETTINGS, ["AUTH_MODE"]),
            skipped(
                "allow_list", NEEDS_SETTINGS, ["AUTH_ALLOWED_EMAILS"], required=False
            ),
        ]
    else:
        items += [
            from_setup(encryption_key_item()),
            from_setup(login_item(settings, state="info")),
            from_setup(allow_list_item(settings)),
        ]
    if settings is None or providers is None:
        items.append(
            skipped(
                "custom_provider",
                NEEDS_SETTINGS
                if settings is None
                else "Skipped: the providers file did not load.",
                ["PROVIDERS_CONFIG_PATH", "ALLOW_CUSTOM_PROVIDER"],
                required=False,
            )
        )
    else:
        items.append(from_setup(custom_provider_item(settings, providers)))
    if settings is None:
        items.append(
            skipped("connectors", NEEDS_SETTINGS, CONNECTOR_SETTINGS, required=False)
        )
    elif settings.mcp_enabled and connectors is None:
        items.append(
            skipped(
                "connectors",
                "Skipped: the connectors file did not load.",
                CONNECTOR_SETTINGS,
                required=False,
            )
        )
    else:
        items.append(from_setup(connectors_item(settings, lambda: connectors)))
    items += database_items[1:]

    # 5. setup
    items.append(setup_item(settings, facts))

    # 6. login provider
    items.append(await check_login_provider(settings, login_transport, timeout))

    # 7. providers
    if settings is None or providers is None:
        items.append(
            skipped(
                "providers",
                NEEDS_SETTINGS
                if settings is None
                else "Skipped: the providers file did not load.",
                ["PROVIDERS_CONFIG_PATH"],
                required=False,
            )
        )
    else:
        for preset in providers.providers.values():
            items.append(
                await check_provider(preset, settings, http_transport, timeout)
            )

    # 8. connectors
    if connectors is not None:
        for connector in connectors.connectors:
            items.append(await check_connector(connector, http_transport, timeout))

    items.append(FRONTEND_LINE)
    return items


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.doctor",
        description="Check this install's settings, database, login provider, and providers.",
    )
    parser.add_argument("--json", action="store_true", help="print the checks as JSON")
    return parser.parse_args(argv)


async def main(
    argv: list[str] | None = None,
    *,
    login_transport: httpx.AsyncBaseTransport | None = None,
    http_transport: httpx2.AsyncBaseTransport | None = None,
    load_settings: Callable[[], Settings] = Settings,
    load_connectors: Callable[[], ConnectorConfig] = load_connector_config,
) -> int:
    args = parse_args(argv)
    items = await run_checks(
        login_transport=login_transport,
        http_transport=http_transport,
        load_settings=load_settings,
        load_connectors=load_connectors,
    )
    if args.json:
        print(json.dumps({"items": [entry.model_dump() for entry in items]}, indent=2))
    else:
        width = max(len(entry.id) for entry in items)
        for entry in items:
            print(entry.line(width))
    return 1 if any(entry.state == "failed" for entry in items) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
