"""Helpers for connector API tests: an app with MCP on and a connectors.yaml."""

import uuid
from contextlib import contextmanager
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.auth import get_jwks_cache
from app.connector_config import get_connector_config
from app.main import app
from tests.chat_helpers import PROVIDERS_FIXTURE, run_db

CATALOG = [
    {
        "name": "calendar",
        "title": "Google Calendar",
        "description": "Read your calendar and add events.",
        "url": "http://gcal-mcp:8000/mcp",
        "auth": {"kind": "none"},
        "guide": "https://example.com/docs/connectors.md#google-calendar",
    }
]


def write_config(
    path: Path, connectors: list[dict] | None = None, catalog=CATALOG
) -> Path:
    path.write_text(
        yaml.safe_dump({"connectors": connectors or [], "catalog": catalog})
    )
    get_connector_config.cache_clear()
    return path


@contextmanager
def connectors_app(
    settings_env,
    jwks_cache,
    config_path: Path,
    *,
    enabled: bool = True,
    users: bool = True,
):
    """Start the app with MCP_ENABLED and MCP_USER_CONNECTORS as given."""
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    settings_env.setenv("MCP_ENABLED", "true" if enabled else "false")
    settings_env.setenv("MCP_USER_CONNECTORS", "true" if users else "false")
    settings_env.setenv("MCP_CONNECTORS_PATH", str(config_path))
    from app.config import get_settings
    from app.db import get_engine, get_sessionmaker

    get_settings.cache_clear()
    get_connector_config.cache_clear()
    # A test may start the app twice; a Postgres engine from the first start
    # is tied to that start's event loop.
    get_engine.cache_clear()
    get_sessionmaker.cache_clear()
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def add(client, headers, name="calendar", url="http://127.0.0.1:9/mcp", **auth):
    return client.post(
        "/api/connectors", headers=headers, json={"name": name, "url": url, **auth}
    )


def listing(client, headers) -> dict:
    response = client.get("/api/connectors", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def by_name(body: dict, name: str) -> dict:
    return next(c for c in body["connectors"] if c["name"] == name)


def link(url: str, conversation_id: str, connector_id: str) -> None:
    """Turn a connector on in a conversation, straight in the database."""
    from app.models import ConversationConnector

    async def work(session):
        session.add(
            ConversationConnector(
                conversation_id=uuid.UUID(conversation_id),
                connector_id=uuid.UUID(connector_id),
            )
        )
        await session.commit()

    run_db(url, work)


def links(url: str) -> list[tuple[str, str]]:
    from sqlalchemy import select

    from app.models import ConversationConnector

    async def work(session):
        rows = (await session.execute(select(ConversationConnector))).scalars().all()
        return sorted((str(r.conversation_id), str(r.connector_id)) for r in rows)

    return run_db(url, work)


def connector_rows(url: str) -> list:
    from sqlalchemy import select

    from app.models import Connector

    async def work(session):
        return (await session.execute(select(Connector))).scalars().all()

    return run_db(url, work)
