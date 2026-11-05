"""Connector rows: operator rows per user, tool lists, switches, and auth headers.

Openspec mcp-connectors design decisions 3, 4, 6 and 7. The connector routes
(app/routers/connectors.py) and, later, the chat turn use these helpers, so a
tool's name, availability, and starting badge are worked out in one place.
Nothing here imports the MCP SDK.
"""

import logging
import os
import re
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.connector_auth import read_auth
from app.connector_config import ConnectorConfig, OperatorConnector
from app.log_masking import register_secret
from app.mcp_client import McpTool
from app.models import Connector

logger = logging.getLogger(__name__)

USER = "user"
OPERATOR = "operator"
# Tool names OpenAI-compatible APIs accept (design decision 3).
TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
MAX_URL_LENGTH = 2048


def now() -> datetime:
    return datetime.now(UTC)


def full_name(connector_name: str, tool: str) -> str:
    """The name the model sees: `<connector>__<tool>`."""
    return f"{connector_name}__{tool}"


def tool_available(connector_name: str, tool: str) -> bool:
    return TOOL_NAME.fullmatch(full_name(connector_name, tool)) is not None


def url_problem(url: str) -> str | None:
    """Why a user connector URL is refused, or None when it is fine.

    The custom provider's check (http or https with a host), plus no user name
    or password: a token belongs in the auth field, where it is encrypted.
    """
    if len(url) > MAX_URL_LENGTH:
        return f"must be at most {MAX_URL_LENGTH} characters"
    try:
        parsed = urlparse(url)
        parsed.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError:
        return "must be an http or https address"
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "must be an http or https address"
    if parsed.username is not None or parsed.password is not None:
        return "must not hold a user name or password; put a token in the auth field"
    return None


def same_origin(first: str | None, second: str | None) -> bool:
    """True when two URLs reach the same server: scheme, host, and port."""
    if first is None or second is None:
        return False

    def origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlparse(url)
        port = parsed.port or {"http": 80, "https": 443}.get(parsed.scheme)
        return parsed.scheme, (parsed.hostname or "").lower(), port

    try:
        return origin(first) == origin(second)
    except ValueError:
        return False


def operator_entry(
    connector: Connector, config: ConnectorConfig
) -> OperatorConnector | None:
    """The configuration entry behind an operator row, or None if it is gone."""
    if connector.source != OPERATOR or connector.operator_key is None:
        return None
    return config.get(connector.operator_key)


def starts_as_reads(tool: dict[str, Any], entry: OperatorConnector | None) -> bool:
    """The badge's starting value (decision 7): the operator's read_only list,
    else the server's readOnlyHint, else acts. Only such a tool may be reads."""
    if entry is not None and tool["name"] in entry.read_only:
        return True
    return tool.get("read_only_hint") is True


def offered_tools(
    connector: Connector, config: ConnectorConfig
) -> list[dict[str, Any]]:
    """The stored tools this connector offers: for an operator row, only the
    ones its configuration lists (all when it lists none)."""
    entry = operator_entry(connector, config)
    if entry is None or entry.tools is None:
        return list(connector.tools)
    return [tool for tool in connector.tools if tool["name"] in entry.tools]


def tool_setting(connector: Connector, name: str) -> dict[str, bool]:
    stored = connector.tool_settings.get(name) or {}
    return {
        "enabled": bool(stored.get("enabled", False)),
        "acts": bool(stored.get("acts", True)),
        "always_allow": bool(stored.get("always_allow", False)),
    }


def current_setting(
    connector: Connector, tool: dict[str, Any], entry: OperatorConnector | None
) -> dict[str, bool]:
    """The stored setting with the rules applied against the configuration
    now, so a tool the operator no longer lists in read_only is acts at once,
    not only after the next Test (decision 7)."""
    return _settled(
        tool_setting(connector, tool["name"]),
        starts_as_reads(tool, entry),
        tool_available(connector.name, tool["name"]),
    )


def _starting_setting(reads: bool) -> dict[str, bool]:
    return {"enabled": False, "acts": not reads, "always_allow": False}


def _settled(setting: dict[str, bool], reads: bool, available: bool) -> dict[str, bool]:
    """A setting that keeps the rules: only a starting reads tool may be
    reads, always allow is only for acts, and an unavailable tool is off."""
    acts = setting["acts"] or not reads
    return {
        "enabled": setting["enabled"] and available,
        "acts": acts,
        "always_allow": setting["always_allow"] and acts,
    }


def store_tools(
    connector: Connector, listed: list[McpTool], config: ConnectorConfig
) -> None:
    """Store a fresh tool list from Test (decision 6).

    An operator row keeps only the tools its configuration offers. Switches
    of tools still offered are kept; the others are dropped, and new tools
    start switched off with the badge from the hint or the operator's list.
    """
    entry = operator_entry(connector, config)
    tools = []
    settings: dict[str, dict[str, bool]] = {}
    for item in listed:
        if (
            entry is not None
            and entry.tools is not None
            and item.name not in entry.tools
        ):
            continue
        if any(tool["name"] == item.name for tool in tools):
            continue
        tool = {
            "name": item.name,
            "title": item.title,
            "description": item.description,
            "input_schema": item.input_schema,
            "read_only_hint": item.read_only_hint,
            "available": tool_available(connector.name, item.name),
        }
        tools.append(tool)
        reads = starts_as_reads(tool, entry)
        previous = connector.tool_settings.get(item.name)
        setting = (
            tool_setting(connector, item.name) if previous else _starting_setting(reads)
        )
        settings[item.name] = _settled(setting, reads, tool["available"])
    connector.tools = tools
    connector.tool_settings = settings
    connector.tools_listed_at = now()


def refresh_availability(connector: Connector, config: ConnectorConfig) -> None:
    """Work availability out again after a rename, switching off tools whose
    full name no longer fits."""
    entry = operator_entry(connector, config)
    tools = []
    settings = dict(connector.tool_settings)
    for tool in connector.tools:
        tool = {**tool, "available": tool_available(connector.name, tool["name"])}
        tools.append(tool)
        if tool["name"] in settings:
            settings[tool["name"]] = _settled(
                tool_setting(connector, tool["name"]),
                starts_as_reads(tool, entry),
                tool["available"],
            )
    connector.tools = tools
    connector.tool_settings = settings


def auth_headers(
    connector: Connector, config: ConnectorConfig, settings: Settings
) -> dict[str, str]:
    """The headers that carry the connector's auth.

    A user connector's value is decrypted (raises DecryptionError when it
    does not belong to this connector); an operator connector's is read from
    the environment now. Both are registered with log masking.
    """
    entry = operator_entry(connector, config)
    if entry is not None:
        kind, header = entry.auth.kind, entry.auth.header
        value = (
            os.environ.get(entry.auth.env or "", "").strip() if kind != "none" else None
        )
        if value:
            register_secret(value)
    else:
        kind, header = connector.auth_kind, connector.auth_header
        value = (
            read_auth(settings.key_encryption_key, connector)
            if kind != "none"
            else None
        )
    if not value:
        return {}
    if kind == "bearer":
        return {"Authorization": f"Bearer {value}"}
    if kind == "header" and header:
        return {header: value}
    return {}


def connector_url(connector: Connector, config: ConnectorConfig) -> str | None:
    entry = operator_entry(connector, config)
    return entry.url if entry is not None else connector.url


async def prune_operator_rows(session: AsyncSession, config: ConnectorConfig) -> None:
    """Delete every operator row whose entry is no longer configured, for all
    users. Deleting the row removes it from conversations by cascade."""
    names = [entry.name for entry in config.connectors]
    query = delete(Connector).where(Connector.source == OPERATOR)
    if names:
        query = query.where(Connector.operator_key.not_in(names))
    await session.execute(query)


async def sync_operator_rows(
    session: AsyncSession, user_id: uuid.UUID, config: ConnectorConfig
) -> None:
    """Give the user a row for each configured operator connector, and delete
    their rows for connectors no longer configured (decision 4). Commits.

    An operator connector whose name the user already uses for a connector of
    their own is skipped for that user, with a warning in the log.
    """
    names = {entry.name for entry in config.connectors}
    rows = (
        (await session.execute(select(Connector).where(Connector.user_id == user_id)))
        .scalars()
        .all()
    )
    stale = [
        row.id
        for row in rows
        if row.source == OPERATOR and row.operator_key not in names
    ]
    if stale:
        await session.execute(delete(Connector).where(Connector.id.in_(stale)))
    taken = {row.name for row in rows if row.id not in stale}
    have = {row.operator_key for row in rows if row.source == OPERATOR}
    for entry in config.connectors:
        if entry.name in have:
            continue
        if entry.name in taken:
            logger.warning(
                "Operator connector '%s' is not offered to user %s, whose own connector "
                "has that name",
                entry.name,
                user_id,
            )
            continue
        session.add(
            Connector(
                user_id=user_id,
                name=entry.name,
                source=OPERATOR,
                operator_key=entry.name,
                auth_kind=entry.auth.kind,
                auth_header=entry.auth.header,
            )
        )
    try:
        await session.commit()
    except IntegrityError:
        # Another request created the same rows first.
        await session.rollback()


async def visible_connectors(
    session: AsyncSession,
    user_id: uuid.UUID,
    config: ConnectorConfig,
    settings: Settings,
) -> list[Connector]:
    """The user's connectors to show: configured operator rows first, then
    their own when users may add connectors, each group by name."""
    rows = (
        (
            await session.execute(
                select(Connector)
                .where(Connector.user_id == user_id)
                .order_by(Connector.name)
            )
        )
        .scalars()
        .all()
    )
    operator = [row for row in rows if operator_entry(row, config) is not None]
    own = (
        [row for row in rows if row.source == USER]
        if settings.mcp_user_connectors
        else []
    )
    return operator + own
