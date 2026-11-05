import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field


def parse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.strip().split("\n\n"):
        if not frame:
            continue
        name, data = frame.split("\n")
        assert name.startswith("event: ") and data.startswith("data: ")
        events.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return events


@dataclass
class Left:
    """What a client saw of a stream before it went away."""

    status: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""

    @property
    def events(self) -> list[tuple[str, dict]]:
        return parse_events(self.body)

    @property
    def names(self) -> list[str]:
        return [name for name, _ in self.events]


async def leave(
    app,
    path: str,
    headers: dict[str, str],
    body: dict | None,
    when: Callable[[str], bool] | asyncio.Event,
    method: str = "POST",
    timeout: float = 10,
) -> Left:
    """Call `app` as a browser that disconnects part way, and return once the
    response has ended.

    The client goes away once the body so far makes `when(body)` true, or once
    `when` (an event) is set. TestClient and httpx read whole responses, so
    they cannot drop one; this talks ASGI directly, with a spec version that
    makes Starlette listen for the disconnect.
    """
    gone = asyncio.Event()
    seen = Left()
    request_sent = False

    async def receive():
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            payload = json.dumps(body).encode() if body is not None else b""
            return {"type": "http.request", "body": payload, "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            seen.status = message["status"]
            seen.headers = {k.decode(): v.decode() for k, v in message["headers"]}
        elif message["type"] == "http.response.body":
            seen.body += message.get("body", b"").decode()
            if callable(when) and when(seen.body):
                gone.set()

    async def leave_on_event():
        await when.wait()
        gone.set()

    watcher = None if callable(when) else asyncio.ensure_future(leave_on_event())
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        + [(b"content-type", b"application/json"), (b"host", b"test")],
        "client": ("127.0.0.1", 50000),
        "server": ("test", 80),
    }
    try:
        await asyncio.wait_for(app(scope, receive, send), timeout)
    finally:
        if watcher is not None:
            watcher.cancel()
    return seen


def after_first(event_name: str) -> Callable[[str], bool]:
    """Leave once the body holds an event of this name."""
    return lambda body: f"event: {event_name}\n" in body
