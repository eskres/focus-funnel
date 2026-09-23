"""Server-sent events for the chat.

Errors raised before the stream starts are ordinary error responses. The writer
only sees errors raised after that, so it reports them as `error` events with
the same envelope and ends the stream without `done`.
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


async def event_stream(
    events: AsyncIterator[Event],
    on_close: Callable[[], Awaitable[None]] | None = None,
) -> AsyncIterator[str]:
    try:
        try:
            async for name, data in events:
                yield format_event(name, data)
        except ApiError as exc:
            yield error_event(exc.code, exc.message)
            return
        except Exception:
            logger.exception("Unhandled error while streaming a chat answer")
            yield error_event(ErrorCode.INTERNAL_ERROR, "Something went wrong.")
            return
        yield format_event("done", {})
    finally:
        if on_close is not None:
            await on_close()


def sse_response(
    events: AsyncIterator[Event],
    on_close: Callable[[], Awaitable[None]] | None = None,
) -> StreamingResponse:
    return StreamingResponse(
        event_stream(events, on_close),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
