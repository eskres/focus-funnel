"""The tool-provider seam: the tools one turn offers, and who runs each.

Openspec mcp-connectors design decisions 2, 3, 8 and 9. `Turn` gets a list
of providers: the built-in tools first (`BuiltinTools` in app/chat/turn.py,
names without a prefix), then one `ConnectorTools` per connector that is on
in the conversation, whose tools are offered as `<connector>__<tool>`. Turn
offers every provider's definitions, finds the provider that owns a called
name, and stores what the provider's `ToolOutcome` says.

A connector opens its MCP session only when the model calls one of its
tools, keeps it for the rest of the turn, and closes it in the turn's
cleanup. A connector that fails becomes a tool error for the model; it never
ends the turn.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.actions import ActionTarget
from app.chat.config import ConnectorLimits
from app.chat.sse import Event
from app.config import Settings
from app.connector_config import get_connector_config
from app.connectors import (
    OPERATOR,
    USER,
    auth_headers,
    connector_url,
    full_name,
    offered_tools,
    operator_entry,
    tool_available,
    tool_setting,
)
from app.crypto import DecryptionError
from app.errors import ErrorCode
from app.mcp_client import (
    ConnectorError,
    McpConnect,
    McpSession,
    ToolResult,
    result_for_model,
)
from app.models import Connector, ConversationConnector

logger = logging.getLogger(__name__)


@dataclass
class TurnToolState:
    """What the providers of one turn share."""

    # Set once a connector's own content (an isError result included) went
    # back to the model in this turn; from then on every acts tool needs a
    # card (decision 8). Our own failure text does not set it.
    read_connector_data: bool = False


@dataclass
class ToolOutcome:
    """What one tool call produced."""

    # The tool message's content: what the model reads.
    result: str
    # The chat's line for the call, sent with the tool end event.
    summary: str
    # More fields for the tool end event (the search's sources).
    extra: dict[str, Any] = field(default_factory=dict)
    # Stored on the tool message, so a reload shows the same (sources, proposal_id).
    details: dict[str, Any] | None = None
    # Events sent before the tool end event (a proposal card).
    events: list[Event] = field(default_factory=list)
    # The connector failed (decision 9): the end event carries failed: true.
    failed: bool = False


@dataclass
class ConnectorRun:
    """One call to a connector's server: its result, or why it failed."""

    result: ToolResult | None = None
    # The failure's error code and reason ("could not be reached").
    code: str | None = None
    reason: str | None = None


class ToolProvider(Protocol):
    def definitions(self) -> list[dict[str, Any]]:
        """OpenAI-shaped tool definitions, as the model sees them."""
        ...

    def owns(self, name: str) -> bool: ...

    def needs_approval(self, name: str, turn: TurnToolState) -> bool:
        """True when a call must wait for the user's approval (decision 7)."""
        ...

    def action_target(self, name: str) -> ActionTarget:
        """What the card names, for a call that needs approval."""
        ...

    async def call(self, name: str, arguments: dict[str, Any], turn: TurnToolState) -> ToolOutcome:
        """Run one call. Raises ValueError or ToolArgumentError for bad
        arguments, which Turn sends back to the model."""
        ...

    async def aclose(self) -> None:
        """Release what the turn opened. Safe to call more than once."""
        ...


def tool_label(name: str) -> str:
    """A tool name as the chat shows it: `calendar__list_events` reads
    `calendar: list_events`. A connector name has no `__`, so the first one
    splits it (decision 3)."""
    connector, sep, tool = name.partition("__")
    return f"{connector}: {tool}" if sep else name


class ConnectorTools:
    """The switched-on, available tools of one connector, for one turn."""

    def __init__(
        self,
        connector_id: uuid.UUID,
        name: str,
        url: str,
        tools: list[dict[str, Any]],
        settings: dict[str, dict[str, bool]],
        headers: Callable[[], dict[str, str]],
        connect: McpConnect,
        limits: ConnectorLimits,
    ):
        self.connector_id = connector_id
        self.name = name
        self._url = url
        # Full name -> stored tool, for the tools offered in this turn.
        self._tools = {full_name(name, tool["name"]): tool for tool in tools}
        self._settings = settings
        # Called when the session opens, so a turn that calls no tool of this
        # connector never decrypts its auth.
        self._headers = headers
        self._connect = connect
        self._limits = limits
        self._session: McpSession | None = None
        # A connect that failed is not tried again in the same turn.
        self._connect_error: ConnectorError | None = None

    def definitions(self) -> list[dict[str, Any]]:
        return [_definition(name, tool) for name, tool in self._tools.items()]

    def owns(self, name: str) -> bool:
        return name in self._tools

    def needs_approval(self, name: str, turn: TurnToolState) -> bool:
        setting = self._settings[self._tools[name]["name"]]
        if not setting["acts"]:
            return False
        return not setting["always_allow"] or turn.read_connector_data

    def action_target(self, name: str) -> ActionTarget:
        """What the card for a call to this tool names (decision 7)."""
        tool = self._tools[name]
        return ActionTarget(self.connector_id, self.name, tool["name"], tool.get("title"))

    async def run(self, name: str, arguments: dict[str, Any]) -> ConnectorRun:
        """Call the server's tool. A failure is returned, never raised."""
        tool = self._tools[name]["name"]
        try:
            session = await self._open()
            return ConnectorRun(result=await session.call_tool(tool, arguments))
        except ConnectorError as exc:
            return ConnectorRun(code=exc.code, reason=exc.reason)
        except Exception:
            logger.exception("Connector %s failed while calling %s", self.name, tool)
            return ConnectorRun(code=ErrorCode.INTERNAL_ERROR, reason="failed unexpectedly")

    async def call(self, name: str, arguments: dict[str, Any], turn: TurnToolState) -> ToolOutcome:
        tool = self._tools[name]["name"]
        label = tool_label(name)
        run = await self.run(name, arguments)
        if run.result is None:
            return self._failed(label, run.reason or "failed unexpectedly")
        result = run.result
        # The server's own content reached the model, even an error result.
        turn.read_connector_data = True
        return ToolOutcome(
            result=result_for_model(result, self.name, tool, self._limits.result_max_chars),
            summary=f"Used {label}" + (" (it reported an error)" if result.is_error else ""),
        )

    def _failed(self, label: str, reason: str) -> ToolOutcome:
        """A connector failure as a plain tool error (decision 9)."""
        summary = f"{label} failed: the connector {reason}"
        return ToolOutcome(
            result=f"Error: the {self.name} connector {reason}. Tell the user.",
            summary=summary,
            # Stored on the tool message, so a reloaded chat still shows the failure.
            details={"failed": True, "summary": summary},
            failed=True,
        )

    async def _open(self) -> McpSession:
        if self._session is not None:
            return self._session
        if self._connect_error is not None:
            raise self._connect_error
        try:
            try:
                headers = self._headers()
            except DecryptionError:
                raise ConnectorError(
                    ErrorCode.CONNECTOR_AUTH_FAILED,
                    "has an auth value that can't be read any more; enter it again in settings",
                ) from None
            self._session = await self._connect(
                self._url,
                headers,
                connect_seconds=self._limits.connect_seconds,
                call_seconds=self._limits.call_seconds,
            )
        except ConnectorError as exc:
            self._connect_error = exc
            raise
        return self._session

    async def aclose(self) -> None:
        session, self._session = self._session, None
        if session is not None:
            await session.aclose()


def _definition(name: str, tool: dict[str, Any]) -> dict[str, Any]:
    parameters = dict(tool.get("input_schema") or {})
    parameters.setdefault("type", "object")
    if parameters["type"] == "object":
        parameters.setdefault("properties", {})
    function: dict[str, Any] = {"name": name, "parameters": parameters}
    description = tool.get("description") or tool.get("title")
    if description:
        function["description"] = description
    return {"type": "function", "function": function}


def connector_tools(
    connector: Connector,
    settings: Settings,
    connect: McpConnect,
    limits: ConnectorLimits,
) -> ConnectorTools | None:
    """The provider for one connector that is on, or None when it cannot be
    offered: an operator connector no longer configured, a user connector
    while users may not have their own, or one with no URL."""
    config = get_connector_config()
    if connector.source == OPERATOR and operator_entry(connector, config) is None:
        return None
    if connector.source == USER and not settings.mcp_user_connectors:
        return None
    url = connector_url(connector, config)
    if url is None:
        return None
    tools = [
        tool
        for tool in offered_tools(connector, config)
        if tool.get("available")
        and tool_available(connector.name, tool["name"])
        and tool_setting(connector, tool["name"])["enabled"]
    ]
    return ConnectorTools(
        connector.id,
        connector.name,
        url,
        tools,
        {tool["name"]: tool_setting(connector, tool["name"]) for tool in tools},
        lambda: auth_headers(connector, config, settings),
        connect,
        limits,
    )


async def conversation_connector_tools(
    session: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    settings: Settings,
    connect: McpConnect,
    limits: ConnectorLimits,
) -> list[ConnectorTools]:
    """One provider per connector that is on in the conversation, by name.

    Reads nothing while MCP_ENABLED is off.
    """
    if not settings.mcp_enabled:
        return []
    rows = (
        (
            await session.execute(
                select(Connector)
                .join(ConversationConnector, ConversationConnector.connector_id == Connector.id)
                .where(
                    ConversationConnector.conversation_id == conversation_id,
                    Connector.user_id == user_id,
                )
                .order_by(Connector.name)
            )
        )
        .scalars()
        .all()
    )
    providers = [connector_tools(row, settings, connect, limits) for row in rows]
    return [provider for provider in providers if provider is not None]


def connector_definitions(providers: list[ConnectorTools]) -> list[dict[str, Any]]:
    """The tool definitions these connectors offer, in order."""
    return [definition for provider in providers for definition in provider.definitions()]


def connector_tool_count(providers: list[ConnectorTools]) -> int:
    """The switched-on tools these connectors offer, for connectors.max_tools."""
    return len(connector_definitions(providers))
