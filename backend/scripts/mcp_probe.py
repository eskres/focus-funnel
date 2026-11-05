"""Probe an MCP server over Streamable HTTP with the official SDK.

Task 1.1 of the mcp-connectors change: find out how the `mcp` SDK connects,
lists tools page by page, calls a tool, and reports failures, before
app/mcp_client.py depends on it. The findings are in design decision 1.

The SDK is a backend dependency since task 4.1 (app/mcp_client.py wraps it).
Run the probe from backend/:

  uv run python -m scripts.mcp_probe list URL [-H "Name: value"]
  uv run python -m scripts.mcp_probe call URL TOOL '{"a": 1}'
  uv run python -m scripts.mcp_probe selftest

`list` prints the negotiated protocol version, every page of `tools/list`,
and each tool's annotations. `call` prints the raw `tools/call` result.
`selftest` starts local servers on free ports and runs the cases the client
has to tell apart: a paged tool list, a call, the result fields, auth
headers arriving, a closed port, HTTP 401 and 403, a plain HTML answer, a
JSON-RPC error, and a call that outlasts the read timeout.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import threading
import time
from contextlib import AsyncExitStack
from typing import Any

import anyio
import httpx2
import mcp_types as types
import uvicorn
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.lowlevel import Server

CONNECT_SECONDS = 3.0
CALL_SECONDS = 2.0


async def open_client(
    stack: AsyncExitStack,
    url: str,
    headers: dict[str, str] | None = None,
    connect_seconds: float = CONNECT_SECONDS,
    call_seconds: float = CALL_SECONDS,
) -> Client:
    """Connect the way app/mcp_client.py will: our own httpx2 client for
    headers and timeouts, no response cache, protocol negotiated by `auto`."""
    http = await stack.enter_async_context(
        httpx2.AsyncClient(
            headers=headers or {},
            # The HTTP read timeout must outlast the SDK's per-request timeout,
            # or httpx2's ReadTimeout wins the race and tears down the session
            # instead of the call failing with MCPError REQUEST_TIMEOUT.
            timeout=httpx2.Timeout(call_seconds + 5, connect=connect_seconds),
        )
    )
    transport = streamable_http_client(url, http_client=http)
    return await stack.enter_async_context(
        Client(transport, read_timeout_seconds=call_seconds, cache=None)
    )


async def list_all(client: Client) -> list[list[types.Tool]]:
    pages: list[list[types.Tool]] = []
    cursor: str | None = None
    while True:
        page = await client.list_tools(cursor=cursor)
        pages.append(page.tools)
        cursor = page.next_cursor
        if cursor is None:
            return pages


def describe_tool(tool: types.Tool) -> str:
    wire = tool.model_dump(by_alias=True, mode="json", exclude_none=True)
    return json.dumps(wire, separators=(",", ":"))


async def cmd_list(url: str, headers: dict[str, str]) -> None:
    async with AsyncExitStack() as stack:
        client = await open_client(stack, url, headers, call_seconds=30)
        print(f"protocol {client.protocol_version}; server {client.server_info}")
        for number, page in enumerate(await list_all(client), start=1):
            print(f"page {number}: {len(page)} tools")
            for tool in page:
                print("  " + describe_tool(tool))


async def cmd_call(url: str, headers: dict[str, str], tool: str, arguments: dict) -> None:
    async with AsyncExitStack() as stack:
        client = await open_client(stack, url, headers, call_seconds=30)
        result = await client.call_tool(tool, arguments)
        print(json.dumps(result.model_dump(by_alias=True, mode="json"), indent=2))


# --- selftest servers -------------------------------------------------------

PAGE_SIZE = 2
seen_headers: list[dict[str, str]] = []


def _tools() -> list[types.Tool]:
    schema = {"type": "object", "properties": {"text": {"type": "string"}}}
    return [
        types.Tool(
            name="list_events",
            title="List events",
            description="Reads.",
            input_schema=schema,
            annotations=types.ToolAnnotations(read_only_hint=True, open_world_hint=False),
        ),
        types.Tool(
            name="create_event",
            description="Writes.",
            input_schema=schema,
            annotations=types.ToolAnnotations(
                read_only_hint=False, destructive_hint=False, idempotent_hint=False
            ),
        ),
        types.Tool(name="structured", description="Structured only.", input_schema=schema),
        types.Tool(name="fails", description="isError result.", input_schema=schema),
        types.Tool(name="image", description="Image content.", input_schema=schema),
        types.Tool(name="slow", description="Sleeps.", input_schema=schema),
    ]


async def _list_tools(ctx: Any, params: types.PaginatedRequestParams | None) -> types.ListToolsResult:
    tools = _tools()
    start = int(params.cursor) if params and params.cursor else 0
    end = start + PAGE_SIZE
    return types.ListToolsResult(
        tools=tools[start:end], next_cursor=str(end) if end < len(tools) else None
    )


async def _call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    name = params.name
    text = (params.arguments or {}).get("text", "")
    if name == "structured":
        return types.CallToolResult(content=[], structured_content={"events": [{"id": 1}]})
    if name == "fails":
        return types.CallToolResult(
            content=[types.TextContent(type="text", text="calendar not found")], is_error=True
        )
    if name == "image":
        return types.CallToolResult(
            content=[types.ImageContent(type="image", data="iVBORw0KGgo=", mime_type="image/png")]
        )
    if name == "slow":
        await asyncio.sleep(10)
    if name not in {tool.name for tool in _tools()}:
        from mcp.shared.exceptions import MCPError

        raise MCPError(code=types.INVALID_PARAMS, message=f"Unknown tool: {name}")
    return types.CallToolResult(content=[types.TextContent(type="text", text=f"{name}: {text}")])


def selftest_app():
    server = Server("probe", on_list_tools=_list_tools, on_call_tool=_call_tool)
    mcp_app = server.streamable_http_app(streamable_http_path="/mcp")

    async def app(scope, receive, send):
        if scope["type"] == "lifespan" or scope["path"] == "/mcp":
            if scope["type"] == "http":
                seen_headers.append({k.decode(): v.decode() for k, v in scope["headers"]})
            return await mcp_app(scope, receive, send)
        if scope["path"] == "/hang":
            await asyncio.sleep(60)
        status, ctype, body = {
            "/401": (401, "application/json", b'{"error":"unauthorized"}'),
            "/403": (403, "text/plain", b"forbidden"),
            "/html": (200, "text/html", b"<html><body>Not an MCP server</body></html>"),
            "/jsonrpc-error": (
                400,
                "application/json",
                b'{"jsonrpc":"2.0","id":null,"error":{"code":-32600,"message":"Bad request"}}',
            ),
        }.get(scope["path"], (404, "text/plain", b"not found"))
        headers = [(b"content-type", ctype.encode())]
        if status == 401:
            headers.append((b"www-authenticate", b'Bearer realm="probe"'))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    return app


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_server(port: int) -> uvicorn.Server:
    server = uvicorn.Server(
        uvicorn.Config(selftest_app(), host="127.0.0.1", port=port, log_level="warning")
    )
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


async def outcome(label: str, run) -> None:
    started = time.monotonic()
    try:
        value = await run()
        print(f"[{label}] ok in {time.monotonic() - started:.2f}s: {value}")
    except BaseException as exc:  # noqa: BLE001 - the point is to see what is raised
        detail = f"{type(exc).__module__}.{type(exc).__name__}: {exc!r}"
        code = getattr(exc, "code", None)
        if code is not None:
            detail += f" (code {code})"
        if isinstance(exc, BaseExceptionGroup):
            detail += " leaves: " + ", ".join(
                f"{type(e).__module__}.{type(e).__name__}: {e!r}" for e in _leaves(exc)
            )
        print(f"[{label}] raised in {time.monotonic() - started:.2f}s: {detail}")


def _leaves(group: BaseExceptionGroup) -> list[BaseException]:
    out: list[BaseException] = []
    for exc in group.exceptions:
        out.extend(_leaves(exc) if isinstance(exc, BaseExceptionGroup) else [exc])
    return out


async def cmd_selftest() -> None:
    port = free_port()
    server = start_server(port)
    base = f"http://127.0.0.1:{port}"
    try:

        async def listing():
            async with AsyncExitStack() as stack:
                client = await open_client(
                    stack, f"{base}/mcp", {"Authorization": "Bearer probe-secret"}
                )
                pages = await list_all(client)
                lines = [f"protocol {client.protocol_version}, {len(pages)} pages"]
                lines += [describe_tool(tool) for page in pages for tool in page]
                return "\n  " + "\n  ".join(lines)

        async def calls():
            async with AsyncExitStack() as stack:
                client = await open_client(stack, f"{base}/mcp")
                lines = []
                for name in ["list_events", "structured", "fails", "image"]:
                    result = await client.call_tool(name, {"text": "hi"})
                    wire = result.model_dump(by_alias=True, mode="json", exclude_none=True)
                    lines.append(
                        f"{name}: is_error={result.is_error} "
                        f"structured_content={result.structured_content!r} wire={json.dumps(wire)}"
                    )
                return "\n  " + "\n  ".join(lines)

        async def call_unknown():
            async with AsyncExitStack() as stack:
                client = await open_client(stack, f"{base}/mcp")
                return await client.call_tool("nope", {})

        async def call_slow():
            async with AsyncExitStack() as stack:
                client = await open_client(stack, f"{base}/mcp")
                return await client.call_tool("slow", {})

        async def connect(path: str, url: str | None = None):
            async with AsyncExitStack() as stack:
                client = await open_client(stack, url or f"{base}{path}")
                return client.protocol_version

        async def legacy_initialize():
            async with AsyncExitStack() as stack:
                http = await stack.enter_async_context(httpx2.AsyncClient())
                client = await stack.enter_async_context(
                    Client(
                        streamable_http_client(f"{base}/mcp", http_client=http),
                        mode="legacy",
                        cache=None,
                    )
                )
                tools = await client.list_tools()
                return f"protocol {client.protocol_version}, first page {len(tools.tools)} tools"

        await outcome("list (paged, with auth header)", listing)
        auth = [h.get("authorization") for h in seen_headers]
        print(f"  Authorization headers seen by the server: {sorted(set(filter(None, auth)))}")
        print(f"  Protocol headers seen: {sorted({h.get('mcp-protocol-version', '-') for h in seen_headers})}")
        await outcome("legacy initialize", legacy_initialize)
        await outcome("calls", calls)
        await outcome("call unknown tool", call_unknown)
        await outcome(f"call past read timeout ({CALL_SECONDS}s)", call_slow)
        closed = free_port()
        await outcome("closed port", lambda: connect("", f"http://127.0.0.1:{closed}/mcp"))
        await outcome("unresolvable host", lambda: connect("", "http://no-such-host.invalid/mcp"))
        await outcome("HTTP 401", lambda: connect("/401"))
        await outcome("HTTP 403", lambda: connect("/403"))
        await outcome("HTTP 404", lambda: connect("/missing"))
        await outcome("plain HTML 200", lambda: connect("/html"))
        await outcome("JSON-RPC error body", lambda: connect("/jsonrpc-error"))
        await outcome(f"server that never answers (read {CALL_SECONDS}s)", lambda: connect("/hang"))

        async def bounded_connect():
            with anyio.fail_after(1.0):
                return await connect("/hang")

        await outcome("never answers, connect bounded by fail_after(1.0)", bounded_connect)

        async def status_hook():
            statuses: list[int] = []

            async def record(response: httpx2.Response) -> None:
                statuses.append(response.status_code)

            async with AsyncExitStack() as stack:
                http = await stack.enter_async_context(
                    httpx2.AsyncClient(event_hooks={"response": [record]})
                )
                try:
                    await stack.enter_async_context(
                        Client(streamable_http_client(f"{base}/401", http_client=http), cache=None)
                    )
                except BaseException:  # noqa: BLE001 - any failure; the hook is the point
                    return f"statuses seen by a response event hook: {statuses}"
            return "connected?"

        await outcome("HTTP 401 status via event hook", status_hook)

        async def caught_inside():
            async with AsyncExitStack() as stack:
                client = await open_client(stack, f"{base}/mcp")
                try:
                    await client.call_tool("slow", {})
                except Exception as exc:  # noqa: BLE001
                    return f"inside the client context: {type(exc).__name__}({exc}) code {exc.code}"

        await outcome("timeout caught inside the client context", caught_inside)
    finally:
        server.should_exit = True


def parse_headers(raw: list[str]) -> dict[str, str]:
    headers = {}
    for item in raw:
        name, _, value = item.partition(":")
        headers[name.strip()] = value.strip()
    return headers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("list", "call"):
        cmd = sub.add_parser(name)
        cmd.add_argument("url")
        cmd.add_argument("-H", "--header", action="append", default=[])
        if name == "call":
            cmd.add_argument("tool")
            cmd.add_argument("arguments", nargs="?", default="{}")
    sub.add_parser("selftest")
    args = parser.parse_args()
    if args.command == "list":
        asyncio.run(cmd_list(args.url, parse_headers(args.header)))
    elif args.command == "call":
        asyncio.run(
            cmd_call(args.url, parse_headers(args.header), args.tool, json.loads(args.arguments))
        )
    else:
        asyncio.run(cmd_selftest())


if __name__ == "__main__":
    main()
