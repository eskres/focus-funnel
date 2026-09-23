"""Fetches a provider's model list, reporting only the fields it says it has."""

from typing import Any

import httpx2
import openai
from openai import AsyncOpenAI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.models import User
from app.provider_config import ProviderCapabilities, ProviderPreset
from app.provider_features import classify_features
from app.providers import client_for, map_provider_error


class ModelPrices(BaseModel):
    prompt: str
    completion: str


class ModelFeatures(BaseModel):
    tool_calling: str


class ModelItem(BaseModel):
    id: str
    context_length: int | None = None
    prices: ModelPrices | None = None
    features: ModelFeatures


# The field a provider's model list uses for a model's reported feature/
# parameter names differs: Nebius (and providers sharing its schema) use
# "supported_features"; OpenRouter (and providers sharing its schema, which
# lists every accepted request parameter, not just features) use
# "supported_parameters". Both list "tools" when a model accepts it, which is
# all the classifier reads, so trying each field name in turn covers both
# without a config knob for something this narrow.
SUPPORTED_FEATURES_FIELDS = ("supported_features", "supported_parameters")


def _field(model: Any, name: str) -> Any:
    """Read a field from either a dict (tests) or an OpenAI SDK model object.

    Fields the SDK's schema doesn't know about land in __pydantic_extra__.
    """
    if isinstance(model, dict):
        return model.get(name)
    value = getattr(model, name, None)
    if value is None:
        extra = getattr(model, "__pydantic_extra__", None) or {}
        value = extra.get(name)
    return value


async def fetch_model_list(
    client: AsyncOpenAI, capabilities: ProviderCapabilities
) -> list[ModelItem]:
    """List models with only the fields this provider's capabilities say it reports."""
    wants_extra = (
        capabilities.model_list.prices
        or capabilities.model_list.context_length
        or capabilities.model_list.features
    )
    # Nebius (and providers sharing its model-list shape) only include prices,
    # context length, and features when asked for verbose=true.
    extra_query = {"verbose": "true"} if wants_extra else {}
    response = await client.models.list(extra_query=extra_query)

    items: list[ModelItem] = []
    async for model in response:
        context_length = (
            _field(model, "context_length") if capabilities.model_list.context_length else None
        )

        prices = None
        if capabilities.model_list.prices:
            pricing = _field(model, "pricing")
            if isinstance(pricing, dict) and pricing.get("prompt") is not None:
                prices = ModelPrices(
                    prompt=str(pricing["prompt"]),
                    completion=str(pricing.get("completion", "0")),
                )

        supported_features = None
        if capabilities.model_list.features:
            for field_name in SUPPORTED_FEATURES_FIELDS:
                supported_features = _field(model, field_name)
                if supported_features is not None:
                    break

        items.append(
            ModelItem(
                id=_field(model, "id"),
                context_length=context_length,
                prices=prices,
                features=ModelFeatures(**classify_features(supported_features)),
            )
        )
    return items


async def fetch_models(
    session: AsyncSession,
    user: User,
    provider: ProviderPreset,
    settings: Settings | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> list[ModelItem]:
    """List the models this user's key can use on this provider."""
    settings = settings or get_settings()
    client = await client_for(session, user, provider, settings, http_client=http_client)
    try:
        return await fetch_model_list(client, provider.capabilities)
    except openai.OpenAIError as exc:
        mapped = map_provider_error(exc, provider, saved_key=True)
        if mapped is not None:
            raise mapped from exc
        raise
    finally:
        await client.close()
