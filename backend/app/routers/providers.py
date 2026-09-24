"""Provider listing, per-provider API key management, and model listing."""

from datetime import datetime
from urllib.parse import urlparse

import httpx2
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.crypto import encrypt_secret
from app.db import get_session
from app.demo_keys import HeldKey, held_keys
from app.errors import ApiError, ErrorCode
from app.log_masking import register_secret
from app.models import ProviderKey, User
from app.provider_config import (
    CUSTOM_PROVIDER_ID,
    ProviderPreset,
    custom_provider,
    get_providers_config,
)
from app.provider_models import ModelItem, fetch_models
from app.providers import (
    PLACEHOLDER_KEY,
    check_provider_key,
    find_key_row,
    get_provider_http_client,
    provider_not_found,
    resolve_provider,
)

router = APIRouter(prefix="/api/providers")


def _validation_error(message: str) -> ApiError:
    return ApiError(422, ErrorCode.VALIDATION_ERROR, message)


class ProviderStatus(BaseModel):
    id: str
    label: str
    key_url: str
    notice: str
    key_required: bool
    is_custom: bool
    base_url: str | None = None
    key_saved: bool
    key_last4: str | None = None
    key_saved_at: datetime | None = None
    # Demo mode: the key is held by the browser, not stored, until key_expires_at.
    key_held: bool = False
    key_expires_at: datetime | None = None


class ProvidersResponse(BaseModel):
    providers: list[ProviderStatus]
    custom_provider_allowed: bool


class SaveProviderKeyRequest(BaseModel):
    key: str = ""
    base_url: str | None = None

    @field_validator("key")
    @classmethod
    def strip_key(cls, value: str) -> str:
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def strip_base_url(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None


class ModelsResponse(BaseModel):
    models: list[ModelItem]


def _status_for(provider: ProviderPreset, row: ProviderKey | None) -> ProviderStatus:
    is_custom = provider.id == CUSTOM_PROVIDER_ID
    return ProviderStatus(
        id=provider.id,
        label=provider.label,
        key_url=provider.key_url,
        notice=provider.notice,
        key_required=provider.key_required,
        is_custom=is_custom,
        base_url=(row.base_url if row is not None else None) if is_custom else provider.base_url,
        key_saved=row is not None and row.ciphertext is not None,
        key_last4=row.last4 if row is not None else None,
        key_saved_at=row.updated_at if row is not None else None,
    )


def _held_status_for(provider: ProviderPreset, held: HeldKey | None) -> ProviderStatus:
    """A provider's status in demo mode, from the key sent with the request."""
    return ProviderStatus(
        id=provider.id,
        label=provider.label,
        key_url=provider.key_url,
        notice=provider.notice,
        key_required=provider.key_required,
        is_custom=False,
        base_url=provider.base_url,
        key_saved=held is not None,
        key_last4=held.key[-4:] if held is not None else None,
        key_held=held is not None,
        key_expires_at=held.expires_at if held is not None else None,
    )


def _validate_custom_base_url(base_url: str) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise _validation_error("base_url must be an http or https address.")


@router.get("", response_model=ProvidersResponse)
async def list_providers(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> ProvidersResponse:
    config = get_providers_config()
    if settings.auth_mode == "demo":
        held = held_keys()
        return ProvidersResponse(
            providers=[_held_status_for(p, held.get(p.id)) for p in config.providers.values()],
            custom_provider_allowed=False,
        )

    statuses = []
    for preset in config.providers.values():
        row = await find_key_row(session, user, preset.id)
        statuses.append(_status_for(preset, row))

    if settings.allow_custom_provider:
        row = await find_key_row(session, user, CUSTOM_PROVIDER_ID)
        provider = custom_provider(row.base_url if row is not None else "")
        statuses.append(_status_for(provider, row))

    return ProvidersResponse(
        providers=statuses, custom_provider_allowed=settings.allow_custom_provider
    )


@router.put("/{provider_id}/key", response_model=ProviderStatus)
async def save_provider_key(
    provider_id: str,
    body: SaveProviderKeyRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ProviderStatus:
    if provider_id == CUSTOM_PROVIDER_ID:
        if not settings.allow_custom_provider:
            raise _validation_error("Custom providers are turned off on this server.")
        if not body.base_url:
            raise _validation_error("base_url is required for the custom provider.")
        _validate_custom_base_url(body.base_url)
        provider = custom_provider(body.base_url)
    else:
        preset = get_providers_config().get(provider_id)
        if preset is None:
            raise provider_not_found()
        if body.base_url is not None:
            raise _validation_error(f"{preset.label}'s base URL can't be changed.")
        provider = preset

    if not body.key:
        if provider.key_required:
            raise _validation_error("A key is required for this provider.")
    else:
        register_secret(body.key)

    # Check with the provider before any write, so a rejected key never
    # replaces a saved one, and an unreachable provider stores nothing.
    await check_provider_key(provider, body.key or PLACEHOLDER_KEY, http_client=http_client)

    if settings.auth_mode == "demo":
        # Nothing is stored: the frontend server holds the key in the
        # visitor's encrypted cookie after this answer.
        return _held_status_for(provider, HeldKey(body.key, None) if body.key else None)

    row = await find_key_row(session, user, provider_id)
    if row is None:
        row = ProviderKey(user_id=user.id, provider_id=provider_id)
        session.add(row)

    if provider_id == CUSTOM_PROVIDER_ID:
        row.base_url = body.base_url

    if body.key:
        secret = encrypt_secret(settings.key_encryption_key, user.id, provider_id, body.key)
        row.ciphertext = secret.ciphertext
        row.nonce = secret.nonce
        row.key_version = secret.key_version
        row.last4 = body.key[-4:]
    else:
        row.ciphertext = None
        row.nonce = None
        row.key_version = None
        row.last4 = None

    await session.commit()
    await session.refresh(row)
    return _status_for(provider, row)


@router.delete("/{provider_id}/key", status_code=204)
async def delete_provider_key(
    provider_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    if settings.auth_mode == "demo":
        # Demo keys live in the visitor's cookie, which the frontend server clears.
        return Response(status_code=204)
    await session.execute(
        delete(ProviderKey).where(
            ProviderKey.user_id == user.id, ProviderKey.provider_id == provider_id
        )
    )
    await session.commit()
    return Response(status_code=204)


@router.get("/{provider_id}/models", response_model=ModelsResponse, response_model_exclude_none=True)
async def get_provider_models(
    provider_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ModelsResponse:
    row = await find_key_row(session, user, provider_id)
    provider = resolve_provider(provider_id, settings, saved_row=row)
    models = await fetch_models(session, user, provider, settings, http_client=http_client)
    return ModelsResponse(models=models)
