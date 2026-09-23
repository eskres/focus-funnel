import httpx
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from app.chat.sse import event_stream, format_event, sse_response
from app.errors import ApiError, ErrorCode, register_error_handlers
from tests.sse_helpers import parse_events


async def events(*items):
    for item in items:
        yield item


async def frames(stream) -> str:
    return "".join([frame async for frame in stream])


def test_format_event_is_one_named_frame_with_json_data():
    assert format_event("delta", {"text": "a\nb"}) == 'event: delta\ndata: {"text": "a\\nb"}\n\n'


async def test_success_stream_is_the_events_then_done():
    body = await frames(event_stream(events(("delta", {"text": "Hel"}), ("delta", {"text": "lo"}))))
    assert parse_events(body) == [
        ("delta", {"text": "Hel"}),
        ("delta", {"text": "lo"}),
        ("done", {}),
    ]


async def test_on_close_runs_after_the_stream_ends():
    closed = []

    async def on_close():
        closed.append(True)

    await frames(event_stream(events(("delta", {"text": "x"})), on_close))
    assert closed == [True]


async def test_mid_stream_api_error_is_an_error_event_without_done():
    async def failing():
        yield ("delta", {"text": "partial"})
        raise ApiError(409, ErrorCode.PROVIDER_KEY_REJECTED, "Key stopped working.")

    parsed = parse_events(await frames(event_stream(failing())))

    assert [name for name, _ in parsed] == ["delta", "error"]
    assert parsed[-1][1] == {
        "error": {"code": ErrorCode.PROVIDER_KEY_REJECTED, "message": "Key stopped working."}
    }


async def test_unexpected_mid_stream_error_is_an_internal_error_event():
    async def failing():
        raise RuntimeError("boom")
        yield ("delta", {})

    body = await frames(event_stream(failing()))

    assert [name for name, _ in parse_events(body)] == ["error"]
    assert parse_events(body)[-1][1]["error"]["code"] == ErrorCode.INTERNAL_ERROR
    assert "boom" not in body


async def post(fail_before: bool) -> httpx.Response:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/chat")
    async def chat() -> StreamingResponse:
        if fail_before:
            raise ApiError(409, ErrorCode.PROVIDER_KEY_REJECTED, "Key stopped working.")
        return sse_response(events(("delta", {"text": "Hi"})))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post("/chat")


async def test_error_before_the_first_byte_is_an_http_error():
    response = await post(fail_before=True)
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error"]["code"] == ErrorCode.PROVIDER_KEY_REJECTED


async def test_response_is_an_unbuffered_event_stream():
    response = await post(fail_before=False)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-accel-buffering"] == "no"
    assert parse_events(response.text) == [("delta", {"text": "Hi"}), ("done", {})]
