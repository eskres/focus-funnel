"""MCP connector settings: list, add, change, remove, Test, and tool switches.

Openspec mcp-connectors design decisions 4, 6, 7 and 11. Every route answers
404 not_found while MCP_ENABLED is off. Operator connectors come from
connectors.yaml and get a row per user when the user lists connectors; users
may add their own only with MCP_USER_CONNECTORS on. An auth value is stored
encrypted and only its last 4 characters are ever returned.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.chat.config import get_chat_config
from app.config import Settings, get_settings
from app.connector_auth import store_auth
from app.connector_config import (
    ConnectorConfig,
    get_connector_config,
    header_problem,
    name_problem,
)
from app.connectors import (
    OPERATOR,
    USER,
    auth_headers,
    connector_url,
    current_setting,
    now,
    offered_tools,
    operator_entry,
    refresh_availability,
    same_origin,
    starts_as_reads,
    store_tools,
    sync_operator_rows,
    tool_available,
    url_problem,
    visible_connectors,
)
from app.crypto import DecryptionError
from app.db import get_session
from app.errors import (
    ApiError,
    ErrorCode,
    connector_failed,
    operator_connector,
    user_connectors_disabled,
)
from app.log_masking import register_secret
from app.mcp_client import ConnectorError, McpConnect, get_mcp_connect
from app.models import Connector, User
from app.ownership import get_owned_or_404, not_found


def require_mcp_enabled(settings: Settings = Depends(get_settings)) -> None:
    if not settings.mcp_enabled:
        raise not_found()


def require_user_connectors(settings: Settings = Depends(get_settings)) -> None:
    if not settings.mcp_user_connectors:
        raise user_connectors_disabled()


router = APIRouter(
    prefix="/api/connectors", dependencies=[Depends(require_mcp_enabled)]
)

AuthKind = Literal["none", "bearer", "header"]


def _invalid(field: str, problem: str) -> ApiError:
    return ApiError(422, ErrorCode.VALIDATION_ERROR, f"{field}: {problem}")


class ConnectorToolOut(BaseModel):
    name: str
    title: str | None = None
    description: str
    read_only_hint: bool | None = None
    # False when `<connector>__<tool>` is not a valid tool name; never switchable.
    available: bool
    enabled: bool
    acts: bool
    always_allow: bool
    # Whether the badge may say reads: the server's hint or the operator's list.
    reads_allowed: bool


class ConnectorOut(BaseModel):
    id: uuid.UUID
    name: str
    source: Literal["user", "operator"]
    # User connectors only; an operator connector's URL stays in its configuration.
    url: str | None = None
    auth_kind: AuthKind
    auth_header: str | None = None
    auth_set: bool
    # The stored value's last 4 characters; never the value, never for operator rows.
    auth_last4: str | None = None
    tools: list[ConnectorToolOut]
    tools_listed_at: datetime | None = None


class CatalogEntryOut(BaseModel):
    name: str
    title: str
    description: str
    url: str
    auth_kind: AuthKind
    auth_header: str | None = None
    guide: str


class ConnectorsResponse(BaseModel):
    connectors: list[ConnectorOut]
    user_connectors_allowed: bool
    # Offered only when users may add connectors.
    catalog: list[CatalogEntryOut]
    warning_accepted: bool
    max_tools: int


def _strip(value: str | None) -> str | None:
    return value.strip() if isinstance(value, str) else value


def _secret(value: str | None) -> str | None:
    value = _strip(value)
    if value:
        register_secret(value)
    return value or None


class AddConnectorRequest(BaseModel):
    name: str
    url: str
    auth_kind: AuthKind = "none"
    auth_header: str | None = None
    auth_value: str | None = None

    _strip_text = field_validator("name", "url", "auth_header")(_strip)
    _mask_value = field_validator("auth_value")(_secret)


class ChangeConnectorRequest(BaseModel):
    name: str | None = None
    url: str | None = None
    auth_kind: AuthKind | None = None
    auth_header: str | None = None
    # Omitted: keep the stored value (unless auth_kind changes).
    auth_value: str | None = None

    _strip_text = field_validator("name", "url", "auth_header")(_strip)
    _mask_value = field_validator("auth_value")(_secret)


class ChangeToolRequest(BaseModel):
    enabled: bool | None = None
    acts: bool | None = None
    always_allow: bool | None = None


def connector_out(connector: Connector, config: ConnectorConfig) -> ConnectorOut:
    entry = operator_entry(connector, config)
    tools = []
    for tool in offered_tools(connector, config):
        available = tool_available(connector.name, tool["name"])
        setting = current_setting(connector, tool, entry)
        tools.append(
            ConnectorToolOut(
                name=tool["name"],
                title=tool.get("title"),
                description=tool.get("description") or "",
                read_only_hint=tool.get("read_only_hint"),
                available=available,
                enabled=setting["enabled"] and available,
                acts=setting["acts"],
                always_allow=setting["always_allow"],
                reads_allowed=starts_as_reads(tool, entry),
            )
        )
    if entry is not None:
        auth_kind, auth_header = entry.auth.kind, entry.auth.header
        auth_set, last4 = entry.auth.kind != "none", None
    else:
        auth_kind, auth_header = connector.auth_kind, connector.auth_header
        auth_set, last4 = connector.auth_ciphertext is not None, connector.auth_last4
    return ConnectorOut(
        id=connector.id,
        name=connector.name,
        source=connector.source,
        url=connector.url if entry is None else None,
        auth_kind=auth_kind,
        auth_header=auth_header,
        auth_set=auth_set,
        auth_last4=last4,
        tools=tools,
        tools_listed_at=connector.tools_listed_at,
    )


async def get_visible(
    session: AsyncSession,
    connector_id: uuid.UUID,
    user: User,
    config: ConnectorConfig,
    settings: Settings,
) -> Connector:
    """The user's connector, or 404 when it is not theirs or its operator
    entry is gone; 403 for a user connector while users may not add them."""
    connector = await get_owned_or_404(session, Connector, connector_id, user)
    if connector.source == OPERATOR:
        if operator_entry(connector, config) is None:
            raise not_found()
    elif not settings.mcp_user_connectors:
        raise user_connectors_disabled()
    return connector


async def _get_own(
    session: AsyncSession,
    connector_id: uuid.UUID,
    user: User,
    config: ConnectorConfig,
    settings: Settings,
) -> Connector:
    """A user connector the user may change: 403 operator_connector otherwise."""
    connector = await get_owned_or_404(session, Connector, connector_id, user)
    if connector.source == OPERATOR:
        if operator_entry(connector, config) is None:
            raise not_found()
        raise operator_connector()
    if not settings.mcp_user_connectors:
        raise user_connectors_disabled()
    return connector


async def _check_name(
    session: AsyncSession,
    name: str,
    user_id: uuid.UUID,
    config: ConnectorConfig,
    exclude: uuid.UUID | None = None,
) -> None:
    problem = name_problem(name)
    if problem:
        raise _invalid("name", problem)
    if config.get(name) is not None:
        raise _invalid(
            "name", f"'{name}' is reserved for a connector the operator set up"
        )
    query = select(Connector.id).where(
        Connector.user_id == user_id, Connector.name == name
    )
    if exclude is not None:
        query = query.where(Connector.id != exclude)
    if (await session.execute(query)).first() is not None:
        raise _invalid("name", f"you already have a connector named '{name}'")


def _check_url(url: str) -> None:
    problem = url_problem(url)
    if problem:
        raise _invalid("url", problem)


def _check_auth(
    kind: str, header: str | None, value: str | None, value_kept: bool
) -> None:
    if kind == "none":
        if value:
            raise _invalid("auth_value", "must be empty when auth_kind is none")
        if header:
            raise _invalid("auth_header", "is only for auth_kind header")
        return
    if kind == "header":
        problem = header_problem(header)
        if problem:
            raise _invalid("auth_header", problem)
    elif header:
        raise _invalid("auth_header", "is only for auth_kind header")
    if not value and not value_kept:
        raise _invalid("auth_value", f"is required for auth_kind {kind}")


async def _commit_named(session: AsyncSession, name: str) -> None:
    """Commit; a name taken by a request that committed first is a validation error."""
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _invalid("name", f"you already have a connector named '{name}'") from None


@router.get("", response_model=ConnectorsResponse)
async def list_connectors(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ConnectorsResponse:
    config = get_connector_config()
    user_id, warning_accepted = user.id, user.connector_warning_accepted_at is not None
    await sync_operator_rows(session, user_id, config)
    rows = await visible_connectors(session, user_id, config, settings)
    allowed = settings.mcp_user_connectors
    return ConnectorsResponse(
        connectors=[connector_out(row, config) for row in rows],
        user_connectors_allowed=allowed,
        catalog=[
            CatalogEntryOut(
                name=entry.name,
                title=entry.title,
                description=entry.description,
                url=entry.url,
                auth_kind=entry.auth.kind,
                auth_header=entry.auth.header,
                guide=entry.guide,
            )
            for entry in config.catalog
        ]
        if allowed
        else [],
        warning_accepted=warning_accepted,
        max_tools=get_chat_config().connectors.max_tools,
    )


@router.post("/warning", status_code=204)
async def accept_warning(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if user.connector_warning_accepted_at is None:
        user.connector_warning_accepted_at = now()
        await session.commit()
    return Response(status_code=204)


@router.post(
    "",
    response_model=ConnectorOut,
    status_code=201,
    dependencies=[Depends(require_user_connectors)],
)
async def add_connector(
    body: AddConnectorRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ConnectorOut:
    config = get_connector_config()
    await _check_name(session, body.name, user.id, config)
    _check_url(body.url)
    _check_auth(body.auth_kind, body.auth_header, body.auth_value, value_kept=False)
    connector = Connector(
        id=uuid.uuid4(),
        user_id=user.id,
        name=body.name,
        source=USER,
        url=body.url,
        auth_kind=body.auth_kind,
        auth_header=body.auth_header if body.auth_kind == "header" else None,
        tools=[],
        tool_settings={},
    )
    store_auth(settings.key_encryption_key, connector, body.auth_value)
    session.add(connector)
    await _commit_named(session, body.name)
    return connector_out(connector, config)


@router.patch("/{connector_id}", response_model=ConnectorOut)
async def change_connector(
    connector_id: uuid.UUID,
    body: ChangeConnectorRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ConnectorOut:
    config = get_connector_config()
    connector = await _get_own(session, connector_id, user, config, settings)
    fields = body.model_fields_set
    if "name" in fields:
        if body.name is None:
            raise _invalid("name", "must not be empty")
        if body.name != connector.name:
            await _check_name(session, body.name, user.id, config, exclude=connector.id)
    if "url" in fields:
        if body.url is None:
            raise _invalid("url", "must not be empty")
        _check_url(body.url)
    kind = body.auth_kind if body.auth_kind is not None else connector.auth_kind
    header = body.auth_header if "auth_header" in fields else connector.auth_header
    if kind != "header" and "auth_header" not in fields:
        header = None
    # The stored value is kept while the kind stays the same.
    value_kept = kind == connector.auth_kind and connector.auth_ciphertext is not None
    if {"auth_kind", "auth_header", "auth_value"} & fields:
        _check_auth(kind, header, body.auth_value, value_kept=value_kept)
    url_changed = "url" in fields and body.url != connector.url
    if (
        url_changed
        and kind != "none"
        and not body.auth_value
        and not same_origin(body.url, connector.url)
    ):
        # The stored value is never sent to another server unless the user
        # enters it again: it can't be read back, so it can't be redirected.
        raise _invalid(
            "auth_value", "enter it again: a stored value is not sent to a new server"
        )

    if "name" in fields and body.name != connector.name:
        connector.name = body.name
        refresh_availability(connector, config)
    if url_changed:
        connector.url = body.url
        # Another server's tools are not this one's: the list, the switches,
        # and the badges wait for a Test of the new address.
        connector.tools = []
        connector.tool_settings = {}
        connector.tools_listed_at = None
    connector.auth_kind = kind
    connector.auth_header = header if kind == "header" else None
    if kind == "none":
        store_auth(settings.key_encryption_key, connector, None)
    elif body.auth_value:
        store_auth(settings.key_encryption_key, connector, body.auth_value)
    connector.updated_at = now()
    await _commit_named(session, connector.name)
    return connector_out(connector, config)


@router.delete("/{connector_id}", status_code=204)
async def delete_connector(
    connector_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    config = get_connector_config()
    connector = await _get_own(session, connector_id, user, config, settings)
    # The database removes it from conversations and keeps its action cards.
    await session.delete(connector)
    await session.commit()
    return Response(status_code=204)


@router.post("/{connector_id}/test", response_model=ConnectorOut)
async def test_connector(
    connector_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    connect: McpConnect = Depends(get_mcp_connect),
) -> ConnectorOut:
    config = get_connector_config()
    limits = get_chat_config().connectors
    connector = await get_visible(session, connector_id, user, config, settings)
    url = connector_url(connector, config)
    if url is None:
        raise not_found()
    try:
        headers = auth_headers(connector, config, settings)
    except DecryptionError:
        raise _invalid(
            "auth_value", "the stored value can't be read any more; enter it again"
        ) from None
    try:
        mcp = await connect(
            url,
            headers,
            connect_seconds=limits.connect_seconds,
            call_seconds=limits.call_seconds,
        )
        try:
            listed = await mcp.list_tools()
        finally:
            await mcp.aclose()
    except ConnectorError as exc:
        # The stored list stays as it was.
        raise connector_failed(exc.code, exc.reason) from None
    store_tools(connector, listed, config)
    connector.updated_at = now()
    await session.commit()
    return connector_out(connector, config)


@router.patch("/{connector_id}/tools/{tool:path}", response_model=ConnectorOut)
async def change_tool(
    connector_id: uuid.UUID,
    tool: str,
    body: ChangeToolRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ConnectorOut:
    config = get_connector_config()
    connector = await get_visible(session, connector_id, user, config, settings)
    stored: dict[str, Any] | None = next(
        (item for item in offered_tools(connector, config) if item["name"] == tool),
        None,
    )
    if stored is None:
        raise not_found()
    entry = operator_entry(connector, config)
    setting = current_setting(connector, stored, entry)
    reads_allowed = starts_as_reads(stored, entry)
    if body.enabled and not tool_available(connector.name, tool):
        raise _invalid(
            "enabled",
            f"'{connector.name}__{tool}' is not a valid tool name, so this tool can't be "
            "switched on",
        )
    if body.acts is False and not reads_allowed:
        raise _invalid(
            "acts", "the server does not mark this tool read-only, so it stays acts"
        )
    acts = setting["acts"] if body.acts is None else body.acts
    if body.always_allow and not acts:
        raise _invalid("always_allow", "is only for tools that act")
    if body.enabled is not None:
        setting["enabled"] = body.enabled
    setting["acts"] = acts
    # Moving to reads clears always allow, which only acts tools have.
    always_allow = (
        setting["always_allow"] if body.always_allow is None else body.always_allow
    )
    setting["always_allow"] = always_allow and acts
    connector.tool_settings = {**connector.tool_settings, tool: setting}
    connector.updated_at = now()
    await session.commit()
    return connector_out(connector, config)
