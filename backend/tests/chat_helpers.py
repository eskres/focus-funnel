"""A fake OpenAI-compatible provider for chat tests, and API fixtures.

Loaded as a pytest plugin from conftest.py, so its fixtures are available
to every test module.

FakeLLM answers the model list and chat completions. Each chat completion
takes the next scripted reply; a reply is either a finished completion (a
dict) or a list of streamed chunks, and may end in a mid-stream failure.
"""

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.auth import get_jwks_cache
from app.main import app
from app.providers import get_provider_http_client
from tests.conftest import FakeProvider

PROVIDERS_FIXTURE = Path(__file__).parent / "fixtures" / "providers" / "valid.yaml"
NANO = "vendor/nano-model"
BIG = "vendor/big-model"
NO_TOOLS = "vendor/no-tools-model"

MODEL_LIST = {
    "object": "list",
    "data": [
        {
            "id": NANO,
            "context_length": 131072,
            "pricing": {"prompt": "0.00000006", "completion": "0.00000024"},
            "supported_features": ["tools"],
        },
        {
            "id": BIG,
            "context_length": 262144,
            "pricing": {"prompt": "0.000001", "completion": "0.000003"},
            "supported_features": ["tools"],
        },
        {"id": NO_TOOLS, "context_length": 8192, "supported_features": ["json_mode"]},
    ],
}


class MidStreamFailure(Exception):
    """Put last in a streamed reply to break the connection there."""


def completion(content: str | None = "Hello!", tool_calls=None, finish_reason="stop", usage=None):
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": "cmpl-1",
        "object": "chat.completion",
        "created": 0,
        "model": NANO,
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def tool_call(name: str, arguments: dict | str, call_id: str = "call_1") -> dict:
    args = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def _chunk(delta: dict | None = None, finish_reason=None, usage=None) -> dict:
    chunk: dict[str, Any] = {
        "id": "chunk",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": NANO,
        "choices": []
        if delta is None
        else [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def text_chunks(*parts: str, finish_reason: str = "stop") -> list[dict]:
    chunks = [_chunk({"role": "assistant", "content": ""})]
    chunks += [_chunk({"content": part}) for part in parts]
    chunks.append(_chunk({}, finish_reason=finish_reason))
    return chunks


def tool_call_chunks(name: str, arguments: str, call_id: str = "call_1", index: int = 0) -> list[dict]:
    """A tool call streamed as a provider does: name first, arguments in pieces."""
    middle = len(arguments) // 2
    return [
        _chunk(
            {
                "tool_calls": [
                    {
                        "index": index,
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": ""},
                    }
                ]
            }
        ),
        _chunk({"tool_calls": [{"index": index, "function": {"arguments": arguments[:middle]}}]}),
        _chunk({"tool_calls": [{"index": index, "function": {"arguments": arguments[middle:]}}]}),
    ]


def reasoning_chunk(text: str) -> dict:
    return _chunk({"reasoning": text})


def finish_chunk(finish_reason: str = "stop") -> dict:
    return _chunk({}, finish_reason=finish_reason)


def usage_chunk(prompt_tokens: int = 100, completion_tokens: int = 20) -> dict:
    return _chunk(
        None,
        usage={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    )


class _SseStream(httpx2.AsyncByteStream):
    def __init__(self, items: list):
        self._items = items

    async def __aiter__(self):
        for item in self._items:
            if item is MidStreamFailure or isinstance(item, MidStreamFailure):
                raise httpx2.ReadError("connection reset")
            if isinstance(item, asyncio.Event):
                # Hold the stream here until the test sets the event.
                await asyncio.wait_for(item.wait(), timeout=5)
                continue
            yield f"data: {json.dumps(item)}\n\n".encode()
        yield b"data: [DONE]\n\n"


Reply = dict | list | httpx2.Response | Callable[[httpx2.Request], httpx2.Response]


def api_error(status_code: int, message: str = "refused") -> httpx2.Response:
    return httpx2.Response(status_code, json={"error": {"message": message}})


class _SharedClient(httpx2.AsyncClient):
    """One request may open several SDK clients on this transport; closing one
    must not close it for the others (in production each has its own)."""

    async def aclose(self) -> None:
        pass


class FakeLLM(FakeProvider):
    """FakeProvider with routes: answers /models and /chat/completions from a
    script, streamed or not, and records every chat request body."""

    def __init__(self, replies: list[Reply] | None = None, models: dict | None = None):
        super().__init__(self._route)
        self.replies = list(replies or [])
        self.models = models if models is not None else MODEL_LIST
        self.chat_requests: list[dict] = []
        self.model_list_calls = 0

    def queue(self, *replies: Reply) -> "FakeLLM":
        self.replies.extend(replies)
        return self

    def _route(self, request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/models"):
            self.model_list_calls += 1
            return httpx2.Response(200, json=self.models)
        if request.url.path.endswith("/chat/completions"):
            body = json.loads(request.content)
            self.chat_requests.append(body)
            if not self.replies:
                raise AssertionError(f"Unexpected model call: {body}")
            reply = self.replies.pop(0)
            if callable(reply) and not isinstance(reply, httpx2.Response):
                return reply(request)
            if isinstance(reply, httpx2.Response):
                return reply
            if isinstance(reply, list):
                return httpx2.Response(
                    200, headers={"content-type": "text/event-stream"}, stream=_SseStream(reply)
                )
            return httpx2.Response(200, json=reply)
        return httpx2.Response(404, json={"error": {"message": "no route"}})

    def http_client(self) -> httpx2.AsyncClient:
        return _SharedClient(transport=httpx2.MockTransport(self._handle))

    def install(self) -> "FakeLLM":
        app.dependency_overrides[get_provider_http_client] = self.http_client
        return self


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM().install()


@pytest.fixture
def client(test_database_url, jwks_cache, settings_env):
    """The app with the provider fixture file. Modules may define their own `client`."""
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(PROVIDERS_FIXTURE))
    app.dependency_overrides[get_jwks_cache] = lambda: jwks_cache
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def alice(make_token):
    return {"Authorization": f"Bearer {make_token(sub='auth0|alice')}"}


@pytest.fixture
def bob(make_token):
    return {"Authorization": f"Bearer {make_token(sub='auth0|bob')}"}


def save_key(client, headers, provider="nebius", key="nb-valid-key-aaaa1111"):
    response = client.put(f"/api/providers/{provider}/key", headers=headers, json={"key": key})
    assert response.status_code == 200, response.text
    return response


def entry(model=NANO, provider_id="nebius", effort=None, default=False) -> dict:
    return {
        "provider_id": provider_id,
        "model": model,
        "reasoning_effort": effort,
        "is_default": default,
    }


def save_models(client, headers, *entries: dict, temperature=None):
    return client.put(
        "/api/settings/models",
        headers=headers,
        json={"models": list(entries), "temperature": temperature},
    )


def error_code(response) -> str:
    return response.json()["error"]["code"]


def run_db(url: str, work):
    """Run `await work(session)` against the test database and return its result."""
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker
    from sqlalchemy.pool import NullPool

    from app.db import create_engine

    async def main():
        engine = create_engine(url, poolclass=NullPool)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                return await work(session)
        finally:
            await engine.dispose()

    return asyncio.run(main())


def user_id_for(client, headers):
    """Make sure the user exists (the first request creates it) and return its id."""
    return client.get("/api/me", headers=headers).json()["id"]


def seed_conversation(
    url: str,
    client,
    headers,
    title: str = "A conversation",
    messages: tuple[str, ...] = ("hello", "Hi!"),
    minutes_ago: int = 0,
    **fields,
):
    """Store a conversation with alternating user and assistant messages; return its id."""
    import uuid
    from datetime import UTC, datetime, timedelta

    from app.models import Conversation, Message

    user_id = uuid.UUID(user_id_for(client, headers))

    async def work(session):
        conversation = Conversation(
            user_id=user_id,
            title=title,
            last_activity_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
            **fields,
        )
        session.add(conversation)
        await session.flush()
        for position, content in enumerate(messages):
            role = "user" if position % 2 == 0 else "assistant"
            session.add(
                Message(
                    conversation_id=conversation.id, position=position, role=role, content=content
                )
            )
        await session.commit()
        return str(conversation.id)

    return run_db(url, work)


def chat(client, headers, message: str, conversation_id: str | None = None, **extra):
    body = {"message": message, **extra}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return client.post("/api/chat", headers=headers, json=body)


def ready_user(client, headers, *entries: dict):
    """Save a Nebius key and a loadout, NANO as the default unless entries are given."""
    save_key(client, headers)
    response = save_models(client, headers, *(entries or (entry(NANO, default=True),)))
    assert response.status_code == 200, response.text
