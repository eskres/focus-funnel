"""The provider's model list, cached per user for five minutes.

The chat reads a model's context length and prices from here, so a turn
adds no list call. A stale entry only affects the meter and the price
estimate: choosing a model in settings still reads the list fresh. A list
that cannot be read gives None, and the chat carries on without it.
"""

import logging
import time
import uuid

import httpx2
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import User
from app.provider_config import ProviderPreset
from app.provider_models import ModelItem, fetch_model_list
from app.providers import client_for, provider_for_user

logger = logging.getLogger(__name__)

CACHE_SECONDS = 300.0

_Key = tuple[uuid.UUID, str, str]
_cache: dict[_Key, tuple[float, dict[str, ModelItem]]] = {}


def clear_model_info_cache() -> None:
    _cache.clear()


async def cached_model(
    user_id: uuid.UUID, provider: ProviderPreset, model: str, client: AsyncOpenAI
) -> ModelItem | None:
    """The listed entry for a model, from the cache or read with this client."""
    key = (user_id, provider.id, provider.base_url)
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1].get(model)
    try:
        items = await fetch_model_list(client, provider.capabilities)
    except Exception:
        logger.info("Could not read the model list of %s for the meter", provider.id)
        return None
    by_id = {item.id: item for item in items}
    _cache[key] = (time.monotonic() + CACHE_SECONDS, by_id)
    return by_id.get(model)


async def model_info(
    session: AsyncSession,
    user: User,
    provider_id: str,
    model: str,
    settings: Settings,
    http_client: httpx2.AsyncClient | None = None,
) -> ModelItem | None:
    """The listed entry for a model, opening a client only when the cache misses."""
    try:
        provider = await provider_for_user(session, user, provider_id, settings)
        key = (user.id, provider.id, provider.base_url)
        hit = _cache.get(key)
        if hit is not None and hit[0] > time.monotonic():
            return hit[1].get(model)
        client = await client_for(session, user, provider, settings, http_client=http_client)
    except Exception:
        logger.info("No model list for %s: the provider or its key is not usable", provider_id)
        return None
    try:
        return await cached_model(user.id, provider, model, client)
    finally:
        await client.close()
