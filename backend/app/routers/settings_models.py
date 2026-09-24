"""The model settings: the loadout, the default, the temperature, and Test."""

from decimal import Decimal
from typing import Literal

import httpx2
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_serializer
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.chat.config import ChatConfig, get_chat_config
from app.chat.loadout import MAX_LOADOUT_MODELS, get_loadout, get_user_settings
from app.chat.model_test import run_model_test
from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError, ErrorCode, model_unknown
from app.models import ChatModel, User, UserSettings
from app.provider_models import ModelItem, ModelPrices, fetch_models
from app.providers import get_provider_http_client, provider_for_user

router = APIRouter(prefix="/api/settings/models")


def _invalid(message: str) -> ApiError:
    return ApiError(422, ErrorCode.VALIDATION_ERROR, message)


class LoadoutEntryIn(BaseModel):
    provider_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: str | None = None
    is_default: bool = False


class LoadoutEntry(BaseModel):
    provider_id: str
    model: str
    reasoning_effort: str | None = None
    is_default: bool
    # The efforts offered for this model, from the effort table.
    efforts: list[str]
    # Filled in from the provider's model list when a save reads it.
    tool_calling: str | None = None
    unconfirmed: bool | None = None
    context_length: int | None = None
    prices: ModelPrices | None = None

    @model_serializer(mode="wrap")
    def _omit_unreported(self, handler):
        # Fields from the model list are omitted, not null, when not known.
        data = handler(self)
        for name in ("tool_calling", "unconfirmed", "context_length", "prices"):
            if data.get(name) is None:
                data.pop(name, None)
        return data


class UsageWarning(BaseModel):
    """A monthly warning threshold, in estimated dollars or in tokens."""

    unit: Literal["usd", "tokens"]
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=6)


class UsageWarningOut(BaseModel):
    unit: Literal["usd", "tokens"]
    amount: float


class ModelSettings(BaseModel):
    models: list[LoadoutEntry]
    temperature: float | None
    warning: UsageWarningOut | None = None
    temperature_default: float
    temperature_min: float
    temperature_max: float
    max_models: int
    model_hint: str


class SaveModelSettings(BaseModel):
    models: list[LoadoutEntryIn]
    temperature: float | None = None
    # Like the rest of the body, a save without a warning clears it.
    warning: UsageWarning | None = None


class EffortsResponse(BaseModel):
    efforts: list[str]


class ModelTestRequest(BaseModel):
    provider_id: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: str | None = None


class ModelTestResult(BaseModel):
    ok: bool
    model: str
    message: str


def _entry(row: ChatModel, config: ChatConfig, listed: ModelItem | None = None) -> LoadoutEntry:
    entry = LoadoutEntry(
        provider_id=row.provider_id,
        model=row.model,
        reasoning_effort=row.reasoning_effort,
        is_default=row.is_default,
        efforts=config.efforts_for(row.model),
    )
    if listed is not None:
        entry.tool_calling = listed.features.tool_calling
        entry.unconfirmed = listed.features.tool_calling != "supported"
        entry.context_length = listed.context_length
        entry.prices = listed.prices
    return entry


def warning_of(user_settings: UserSettings | None) -> UsageWarningOut | None:
    if (
        user_settings is None
        or user_settings.warning_unit is None
        or user_settings.warning_amount is None
    ):
        return None
    return UsageWarningOut(
        unit=user_settings.warning_unit, amount=float(user_settings.warning_amount)
    )


def _response(
    rows: list[ChatModel],
    user_settings: UserSettings | None,
    config: ChatConfig,
    listed: dict[tuple[str, str], ModelItem] | None = None,
) -> ModelSettings:
    listed = listed or {}
    return ModelSettings(
        models=[_entry(row, config, listed.get((row.provider_id, row.model))) for row in rows],
        temperature=user_settings.temperature if user_settings is not None else None,
        warning=warning_of(user_settings),
        temperature_default=config.temperature.default,
        temperature_min=config.temperature.min,
        temperature_max=config.temperature.max,
        max_models=MAX_LOADOUT_MODELS,
        model_hint=config.model_hint,
    )


def check_effort(effort: str | None, model: str, config: ChatConfig) -> None:
    if effort is None:
        return
    if effort not in config.documented_efforts:
        raise _invalid(
            f"Reasoning effort '{effort}' is not one of {', '.join(config.documented_efforts)}."
        )
    if effort not in config.efforts_for(model):
        raise _invalid(f"The model '{model}' does not accept reasoning effort '{effort}'.")


def _check_shape(body: SaveModelSettings, config: ChatConfig) -> None:
    """Every check that needs no provider, so a bad body costs no network call."""
    if len(body.models) > MAX_LOADOUT_MODELS:
        raise _invalid(f"The loadout is full: it holds at most {MAX_LOADOUT_MODELS} models.")
    keys = [(entry.provider_id, entry.model) for entry in body.models]
    if len(set(keys)) != len(keys):
        raise _invalid("A model appears twice in the loadout.")
    if sum(entry.is_default for entry in body.models) > 1:
        raise _invalid("Only one model can be the default.")
    if body.temperature is not None and not (
        config.temperature.min <= body.temperature <= config.temperature.max
    ):
        raise _invalid(
            f"Temperature must be between {config.temperature.min} and {config.temperature.max}."
        )
    for entry in body.models:
        check_effort(entry.reasoning_effort, entry.model, config)


@router.get("", response_model=ModelSettings)
async def get_model_settings(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    config: ChatConfig = Depends(get_chat_config),
) -> ModelSettings:
    user_settings = await get_user_settings(session, user)
    return _response(await get_loadout(session, user), user_settings, config)


@router.put("", response_model=ModelSettings)
async def save_model_settings(
    body: SaveModelSettings,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    config: ChatConfig = Depends(get_chat_config),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ModelSettings:
    """Replace the loadout, default, and temperature with exactly the body.

    Every model is checked against its provider's list for this user's key
    before anything is written, so a refused save leaves the old one in place.
    """
    _check_shape(body, config)

    listed: dict[tuple[str, str], ModelItem] = {}
    for provider_id in dict.fromkeys(entry.provider_id for entry in body.models):
        provider = await provider_for_user(session, user, provider_id, settings)
        models = await fetch_models(session, user, provider, settings, http_client=http_client)
        by_id = {item.id: item for item in models}
        for entry in body.models:
            if entry.provider_id != provider_id:
                continue
            if entry.model not in by_id:
                raise model_unknown(provider.label, entry.model)
            listed[(provider_id, entry.model)] = by_id[entry.model]

    await session.execute(delete(ChatModel).where(ChatModel.user_id == user.id))
    rows = [
        ChatModel(
            user_id=user.id,
            provider_id=entry.provider_id,
            model=entry.model,
            reasoning_effort=entry.reasoning_effort,
            is_default=entry.is_default,
            position=position,
        )
        for position, entry in enumerate(body.models)
    ]
    session.add_all(rows)
    user_settings = await get_user_settings(session, user)
    if user_settings is None:
        user_settings = UserSettings(user_id=user.id)
        session.add(user_settings)
    user_settings.temperature = body.temperature
    unit = body.warning.unit if body.warning is not None else None
    amount = body.warning.amount if body.warning is not None else None
    if (unit, amount) != (user_settings.warning_unit, user_settings.warning_amount):
        # A new threshold warns again, even in a month that already had a notice.
        user_settings.warning_notified_month = None
    user_settings.warning_unit = unit
    user_settings.warning_amount = amount
    await session.commit()
    return _response(rows, user_settings, config, listed)


@router.get("/efforts", response_model=EffortsResponse)
async def get_model_efforts(
    model: str = Query(min_length=1),
    _user: User = Depends(get_current_user),
    config: ChatConfig = Depends(get_chat_config),
) -> EffortsResponse:
    """The efforts offered for any model, for choosing one before it is saved."""
    return EffortsResponse(efforts=config.efforts_for(model))


@router.post("/test", response_model=ModelTestResult)
async def test_model(
    body: ModelTestRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    config: ChatConfig = Depends(get_chat_config),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ModelTestResult:
    """Try a model and effort. Changes no stored setting."""
    check_effort(body.reasoning_effort, body.model, config)
    provider = await provider_for_user(session, user, body.provider_id, settings)
    message = await run_model_test(
        session,
        user,
        provider,
        body.model,
        body.reasoning_effort,
        config=config,
        settings=settings,
        http_client=http_client,
    )
    return ModelTestResult(ok=True, model=body.model, message=message)
