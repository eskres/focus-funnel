"""Provider listing, per-provider API key management, and model listing."""

from datetime import datetime
from urllib.parse import urlparse

import httpx2
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.crypto import encrypt_secret
from app.db import get_session
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
from app.providers import PLACEHOLDER_KEY, check_provider_key, get_provider_http_client

router = APIRouter(prefix="/api/providers")


def _not_found() -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND, "No such provider.")


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


async def _find_key(session: AsyncSession, user: User, provider_id: str) -> ProviderKey | None:
    return (
        await session.execute(
            select(ProviderKey).where(
                ProviderKey.user_id == user.id, ProviderKey.provider_id == provider_id
            )
        )
    ).scalar_one_or_none()


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


def _resolve_provider(
    provider_id: str, settings: Settings, saved_row: ProviderKey | None = None
) -> ProviderPreset:
    """Look up a preset, or build the custom provider descriptor.

    For the custom provider, the base URL comes from saved_row when one is
    given (an existing saved row) rather than from the request body.
    """
    if provider_id == CUSTOM_PROVIDER_ID:
        if not settings.allow_custom_provider:
            raise _validation_error("Custom providers are turned off on this server.")
        base_url = saved_row.base_url if saved_row is not None else None
        if not base_url:
            raise _not_found()
        return custom_provider(base_url)

    preset = get_providers_config().get(provider_id)
    if preset is None:
        raise _not_found()
    return preset


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
    statuses = []
    for preset in config.providers.values():
        row = await _find_key(session, user, preset.id)
        statuses.append(_status_for(preset, row))

    if settings.allow_custom_provider:
        row = await _find_key(session, user, CUSTOM_PROVIDER_ID)
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
            raise _not_found()
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

    row = await _find_key(session, user, provider_id)
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
) -> Response:
    await session.execute(
        delete(ProviderKey).where(
            ProviderKey.user_id == user.id, ProviderKey.provider_id == provider_id
        )
    )
    await session.commit()
    return Response(status_code=204)


@router.get("/{provider_id}/models", response_model=ModelsResponse)
async def get_provider_models(
    provider_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_provider_http_client),
) -> ModelsResponse:
    row = await _find_key(session, user, provider_id)
    provider = _resolve_provider(provider_id, settings, saved_row=row)
    models = await fetch_models(session, user, provider, settings, http_client=http_client)
    return ModelsResponse(models=models)
