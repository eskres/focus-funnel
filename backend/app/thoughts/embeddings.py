"""Choosing the embedding model and calling it with the user's own key."""

import uuid
from dataclasses import dataclass
from decimal import Decimal

import httpx2
import openai
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.model_info import cached_model
from app.chat.usage import utc_now
from app.config import Settings
from app.errors import embedding_mismatch
from app.models import UsageEvent, User
from app.provider_config import ProviderPreset, ProvidersConfig
from app.providers import client_for, map_provider_error, provider_for_user, unreachable

# Most texts sent in one embeddings call.
BATCH_SIZE = 64
# An embedding call is short; a slow provider should not hold up a search.
EMBED_TIMEOUT_SECONDS = 10.0


class EmbeddingConfigError(ValueError):
    """The embedding settings name a provider that cannot be used."""


def check_embedding_provider(settings: Settings, providers: ProvidersConfig) -> None:
    """Refuse at startup an EMBEDDING_PROVIDER that is not a preset."""
    if providers.get(settings.embedding_provider) is None:
        known = ", ".join(sorted(providers.providers))
        raise EmbeddingConfigError(
            f"EMBEDDING_PROVIDER '{settings.embedding_provider}' is not a provider preset: "
            f"use one of {known}"
        )


@dataclass(frozen=True)
class EmbeddingChoice:
    provider_id: str
    model: str
    dimensions: int | None


def resolve_embedding_model(user: User, settings: Settings) -> EmbeddingChoice:
    """The embedding model for a new search index of this user.

    Called only when an index is created. Every other operation reads the
    model from the user's index. A per-user choice is added here and nowhere
    else.
    """
    return EmbeddingChoice(
        provider_id=settings.embedding_provider,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )


async def _record(
    session: AsyncSession,
    user: User,
    provider: ProviderPreset,
    model: str,
    prompt_tokens: int | None,
    cost: Decimal | None,
    conversation_id: uuid.UUID | None,
) -> None:
    session.add(
        UsageEvent(
            user_id=user.id,
            conversation_id=conversation_id,
            kind="embed",
            provider_id=provider.id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=None,
            cost_usd=cost,
            created_at=utc_now(),
        )
    )
    await session.commit()


async def embed_texts(
    session: AsyncSession,
    user: User,
    provider_id: str,
    model: str,
    texts: list[str],
    *,
    settings: Settings,
    dimensions: int | None = None,
    conversation_id: uuid.UUID | None = None,
    http_client: httpx2.AsyncClient | None = None,
    max_retries: int = 0,
) -> list[list[float]]:
    """One vector per text, from the provider with this user's own key.

    Sends batches of at most BATCH_SIZE texts and records one usage event per
    call, holding no text. Raises the provider_* errors as a chat call does,
    model_unavailable for a model the key cannot use, and embedding_mismatch
    when the provider returns vectors of unequal length.
    """
    if not texts:
        return []
    provider = await provider_for_user(session, user, provider_id, settings)
    client = await client_for(
        session,
        user,
        provider,
        settings,
        http_client=http_client,
        timeout=EMBED_TIMEOUT_SECONDS,
        max_retries=max_retries,
    )
    extra = {"dimensions": dimensions} if dimensions is not None else {}
    vectors: list[list[float]] = []
    try:
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            try:
                response = await client.embeddings.create(
                    model=model, input=batch, encoding_format="float", **extra
                )
            except openai.OpenAIError as exc:
                mapped = map_provider_error(exc, provider, saved_key=True, model_id=model)
                if mapped is None:
                    raise
                raise mapped from exc
            rows = sorted(response.data, key=lambda row: row.index)
            if len(rows) != len(batch):
                raise unreachable(provider)
            vectors.extend(list(row.embedding) for row in rows)
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            info = await cached_model(user.id, provider, model, client)
            cost = (
                Decimal(info.prices.prompt) * prompt_tokens
                if info is not None and info.prices is not None and prompt_tokens is not None
                else None
            )
            await _record(session, user, provider, model, prompt_tokens, cost, conversation_id)
    finally:
        await client.close()
    lengths = {len(vector) for vector in vectors}
    if len(lengths) != 1:
        raise embedding_mismatch(f"vectors of lengths {sorted(lengths)} from {model}")
    return vectors
