"""Server-sent events for the chat.

Errors raised before the stream starts are ordinary error responses. The writer
only sees errors raised after that, so it reports them as `error` events with
the same envelope and ends the stream without `done`.

A chat turn's stream is a view of its running turn's event log
(`app.chat.running`), which already ends with its terminal event, so it is
written as it is (`log_response`). `/compact` is still tied to its request
and uses `event_stream`, which adds the terminal event itself.
"""

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from fastapi.responses import StreamingResponse

from app.errors import ApiError, ErrorCode

logger = logging.getLogger(__name__)

Event = tuple[str, dict[str, Any]]


def format_event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def error_event(code: str, message: str) -> str:
    return format_event("error", {"error": {"code": code, "message": message}})


DONE: Event = ("done", {})


def terminal_event(exc: Exception) -> Event:
    """The `error` event that ends a stream an exception broke.

    An ApiError keeps its code and message; anything else is logged and sent
    as `internal_error`, so no detail of it reaches the browser.
    """
    if isinstance(exc, ApiError):
        return ("error", {"error": {"code": exc.code, "message": exc.message}})
    logger.error("Unhandled error while streaming a chat answer", exc_info=exc)
    return ("error", {"error": {"code": ErrorCode.INTERNAL_ERROR, "message": "Something went wrong."}})


async def event_stream(
    events: AsyncIterator[Event],
    on_close: Callable[[], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    try:
        try:
            async for name, data in events:
                yield format_event(name, data)
        except Exception as exc:
            yield format_event(*terminal_event(exc))
            return
        yield format_event(*DONE)
    finally:
        if on_close is not None:
            await on_close()


async def _written(events: AsyncIterator[Event]) -> AsyncIterator[str]:
    async for name, data in events:
        yield format_event(name, data)


def _streaming(body: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        body,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def sse_response(
    events: AsyncIterator[Event],
    on_close: Callable[[], Awaitable[None]] | None = None,
) -> StreamingResponse:
    return _streaming(event_stream(events, on_close))


def log_response(events: AsyncIterator[Event]) -> StreamingResponse:
    """Write events that already end with their terminal event, as they are."""
    return _streaming(_written(events))
