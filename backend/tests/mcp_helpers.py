"""A local Streamable HTTP MCP server for tests (pytest plugin).

`mcp_server` starts one uvicorn server per test session on a free port, in a
thread of its own, serving:

- `/mcp`: an MCP server built on the SDK's low-level `Server`, with tools
  listed two per page. Every request's headers are kept in `seen_headers`.
  A test can hide tools from the list or add some (`hidden`, `extra_tools`).
- `/401`: answers every request with HTTP 401.
- `/html`: answers every request with a plain HTML page and status 200.
- `/hang`: never answers.

Its tools: `list_events` (read-only hint) and `create_event` (no hint) echo
their `text` argument; `mixed` returns text, an image, audio, a resource link
and an embedded resource; `structured` returns only structured content;
`fails` returns an `isError` result; `slow` sleeps `seconds` before answering.
Any other name gets a JSON-RPC error. While a test sets `hold_create`,
`create_event` waits for it (and sets `create_entered` first). The HTTP
method of every /mcp request is kept in `methods`, and `open_connections()`
counts the client connections the server holds now.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field

import mcp_types as types
import pytest
import uvicorn
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import MCPError

PAGE_SIZE = 2
_SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}}


def server_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_events",
            title="List events",
            description="Lists calendar events.",
            input_schema=_SCHEMA,
            annotations=types.ToolAnnotations(read_only_hint=True),
        ),
        types.Tool(name="create_event", description="Creates an event.", input_schema=_SCHEMA),
        types.Tool(name="mixed", description="Every content kind.", input_schema=_SCHEMA),
        types.Tool(name="structured", description="Structured only.", input_schema=_SCHEMA),
        types.Tool(name="fails", description="An isError result.", input_schema=_SCHEMA),
        types.Tool(
            name="slow",
            description="Sleeps.",
            input_schema={"type": "object", "properties": {"seconds": {"type": "number"}}},
        ),
    ]


def _lister(state: McpTestServer):
    async def list_tools(
        ctx, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        if state.list_error is not None:
            raise state.list_error
        tools = [tool for tool in server_tools() if tool.name not in state.hidden]
        tools += state.extra_tools
        return _page(tools, params)

    return list_tools


def _page(tools: list[types.Tool], params: types.PaginatedRequestParams | None):
    start = int(params.cursor) if params and params.cursor else 0
    end = start + PAGE_SIZE
    return types.ListToolsResult(
        tools=tools[start:end], next_cursor=str(end) if end < len(tools) else None
    )


def _caller(state: McpTestServer):
    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        hold = state.hold_create
        if params.name == "create_event" and hold is not None:
            state.create_entered.set()
            deadline = time.monotonic() + 10
            while not hold.is_set() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
        state.called.append(params.name)
        return await _call_tool(ctx, params)

    return call_tool


async def _call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    name = params.name
    arguments = params.arguments or {}
    if name in ("list_events", "create_event"):
        text = f"{name}: {arguments.get('text', '')}"
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])
    if name == "mixed":
        return types.CallToolResult(
            content=[
                types.TextContent(type="text", text="first"),
                types.ImageContent(type="image", data="iVBORw0KGgo=", mime_type="image/png"),
                types.AudioContent(type="audio", data="UklGRg==", mime_type="audio/wav"),
                types.ResourceLink(type="resource_link", uri="file:///a.txt", name="a.txt"),
                types.EmbeddedResource(
                    type="resource",
                    resource=types.TextResourceContents(uri="file:///b.txt", text="hidden"),
                ),
                types.TextContent(type="text", text="second"),
            ]
        )
    if name == "structured":
        return types.CallToolResult(
            content=[], structured_content={"events": [{"id": 1, "title": "Dentist"}]}
        )
    if name == "fails":
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="calendar not found")], is_error=True
        )
    if name == "slow":
        await asyncio.sleep(float(arguments.get("seconds", 60)))
        return types.CallToolResult(content=[types.TextContent(type="text", text="late")])
    raise MCPError(code=types.INVALID_PARAMS, message=f"Unknown tool: {name}")


@dataclass
class McpTestServer:
    base: str
    seen_headers: list[dict[str, str]] = field(default_factory=list)
    # Authorization header values that /mcp answers with 401 from now on.
    revoked: set[str] = field(default_factory=set)
    # Changes to the listed tools: names left out, and tools added at the end.
    # A test that sets them puts them back (see `reset`).
    hidden: set[str] = field(default_factory=set)
    extra_tools: list[types.Tool] = field(default_factory=list)
    # A JSON-RPC error that tools/list answers with, while set.
    list_error: MCPError | None = None
    # The HTTP method of every /mcp request, in order.
    methods: list[str] = field(default_factory=list)
    # How many client connections the server holds open now. A client
    # session that ends closes its connections (the SDK used here gives no
    # session id, so no DELETE ends it).
    open_connections: Callable[[], int] = lambda: 0
    # The names of the tools called, in order, once each call is answered.
    called: list[str] = field(default_factory=list)
    # While set, create_event waits until the event is set.
    hold_create: threading.Event | None = None
    create_entered: threading.Event = field(default_factory=threading.Event)

    def reset(self) -> None:
        if self.hold_create is not None:
            self.hold_create.set()
        self.hold_create = None
        self.create_entered.clear()
        self.methods.clear()
        self.called.clear()
        self.list_error = None
        self.seen_headers.clear()
        self.revoked.clear()
        self.hidden.clear()
        self.extra_tools.clear()

    @property
    def url(self) -> str:
        return f"{self.base}/mcp"


def _app(state: McpTestServer):
    server = Server("test", on_list_tools=_lister(state), on_call_tool=_caller(state))
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp")

    async def app(scope, receive, send):
        if scope["type"] == "lifespan" or scope["path"] == "/mcp":
            if scope["type"] == "http":
                headers = {k.decode(): v.decode() for k, v in scope["headers"]}
                state.seen_headers.append(headers)
                state.methods.append(scope["method"])
                if headers.get("authorization") in state.revoked:
                    scope = {**scope, "path": "/401"}
                else:
                    return await mcp_app(scope, receive, send)
            else:
                return await mcp_app(scope, receive, send)
        if scope["path"] == "/hang":
            # Read the request, then wait until the client goes away.
            while (await receive())["type"] != "http.disconnect":
                pass
            return
        status, content_type, body = {
            "/401": (401, "application/json", b'{"error":"unauthorized"}'),
            "/html": (200, "text/html", b"<html><body>Not an MCP server</body></html>"),
        }.get(scope["path"], (404, "text/plain", b"not found"))
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", content_type.encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return app


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def running_mcp_server():
    """Run the test server on a free port until the block ends."""
    port = free_port()
    state = McpTestServer(base=f"http://127.0.0.1:{port}")
    server = uvicorn.Server(
        uvicorn.Config(
            _app(state),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            # A slow call may still run; do not wait long for it at shutdown.
            timeout_graceful_shutdown=1,
        )
    )
    state.open_connections = lambda: len(server.server_state.connections)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("The MCP test server did not start")
        time.sleep(0.02)
    try:
        yield state
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def mcp_server():
    with running_mcp_server() as state:
        yield state
