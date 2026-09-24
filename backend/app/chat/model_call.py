"""Calls to the conversation's model, with the model's settings applied.

A call never falls back to another model. A provider error is mapped to a
spec error that names the model; an unmapped one is raised as it is.
"""

import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx2
import openai
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.chat.model_info import cached_model
from app.errors import ApiError, model_unsupported
from app.models import User
from app.provider_config import ProviderPreset
from app.provider_models import ModelItem
from app.providers import client_for, map_provider_error

# A reasoning model may think for a while before its first token.
MODEL_CALL_TIMEOUT_SECONDS = 120.0
# The SDK retries a 429 and a server error this many times before failing.
MODEL_CALL_RETRIES = 2

Messages = list[dict[str, Any]]


def _refusal_mentions(exc: openai.OpenAIError, *words: str) -> bool:
    text = str(exc).lower()
    return isinstance(exc, openai.BadRequestError) and any(word in text for word in words)


@dataclass
class ModelCall:
    """One model with its settings, and a client for this request."""

    provider: ProviderPreset
    model: str
    temperature: float
    max_tokens: int
    reasoning_effort: str | None
    client: AsyncOpenAI
    user_id: uuid.UUID | None = None

    @property
    def reports_usage(self) -> bool:
        return self.provider.capabilities.stream_usage != "none"

    async def info(self) -> ModelItem | None:
        """The model's listed context length and prices, from the per-user cache."""
        if self.user_id is None:
            return None
        return await cached_model(self.user_id, self.provider, self.model, self.client)

    def request(self, messages: Messages, **extra: Any) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            **extra,
        }
        if self.reasoning_effort is not None:
            request["reasoning_effort"] = self.reasoning_effort
        return request

    @contextmanager
    def mapping_errors(self, *, with_tools: bool = False) -> Iterator[None]:
        try:
            yield
        except openai.OpenAIError as exc:
            mapped: ApiError | None = None
            if self.reasoning_effort is not None and _refusal_mentions(exc, "effort", "reasoning"):
                mapped = model_unsupported(
                    self.model, f"reasoning effort '{self.reasoning_effort}'"
                )
            elif with_tools and _refusal_mentions(exc, "tool"):
                mapped = model_unsupported(self.model, "tool calling")
            else:
                mapped = map_provider_error(
                    exc, self.provider, saved_key=True, model_id=self.model
                )
            if mapped is None:
                raise
            raise mapped from exc

    async def complete(self, messages: Messages, **extra: Any) -> Any:
        """A non-streamed call. Returns the SDK's completion."""
        with self.mapping_errors(with_tools="tools" in extra):
            return await self.client.chat.completions.create(**self.request(messages, **extra))

    async def stream(self, messages: Messages, **extra: Any) -> AsyncIterator[Any]:
        """Open a streamed call and return its chunks.

        Awaiting this raises the errors that arrive before the first byte.
        Iterating the result raises the ones that arrive after it.
        """
        with_tools = "tools" in extra
        # A provider that reports no usage in a stream is not asked for it.
        if self.reports_usage:
            extra = {"stream_options": {"include_usage": True}, **extra}
        with self.mapping_errors(with_tools=with_tools):
            response = await self.client.chat.completions.create(
                **self.request(messages, stream=True, **extra)
            )

        async def chunks() -> AsyncIterator[Any]:
            with self.mapping_errors(with_tools=with_tools):
                async for chunk in response:
                    yield chunk

        return chunks()

    async def aclose(self) -> None:
        await self.client.close()


async def open_model_call(
    session: AsyncSession,
    user: User,
    provider: ProviderPreset,
    model: str,
    *,
    temperature: float,
    max_tokens: int,
    reasoning_effort: str | None,
    settings: Settings,
    http_client: httpx2.AsyncClient | None = None,
) -> ModelCall:
    """Build the client for one model call. Raises provider_key_missing without a key."""
    client = await client_for(
        session,
        user,
        provider,
        settings,
        http_client=http_client,
        timeout=MODEL_CALL_TIMEOUT_SECONDS,
        max_retries=MODEL_CALL_RETRIES,
    )
    return ModelCall(
        provider=provider,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        client=client,
        user_id=user.id,
    )
