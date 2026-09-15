from datetime import datetime

import httpx2
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.crypto import encrypt_secret
from app.db import get_session
from app.log_masking import register_secret
from app.models import NebiusApiKey, User
from app.nebius import check_api_key, get_nebius_http_client

router = APIRouter(prefix="/api/settings/api-key")


class ApiKeyStatus(BaseModel):
    saved: bool
    last4: str | None = None
    saved_at: datetime | None = None


class SaveApiKeyRequest(BaseModel):
    api_key: str

    @field_validator("api_key")
    @classmethod
    def strip_and_require(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("API key is required")
        return value


async def _find_key(session: AsyncSession, user: User) -> NebiusApiKey | None:
    return (
        await session.execute(select(NebiusApiKey).where(NebiusApiKey.user_id == user.id))
    ).scalar_one_or_none()


def _status_for(row: NebiusApiKey | None) -> ApiKeyStatus:
    if row is None:
        return ApiKeyStatus(saved=False)
    return ApiKeyStatus(saved=True, last4=row.last4, saved_at=row.updated_at)


@router.get("", response_model=ApiKeyStatus, response_model_exclude_none=True)
async def get_api_key_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyStatus:
    return _status_for(await _find_key(session, user))


@router.put("", response_model=ApiKeyStatus, response_model_exclude_none=True)
async def save_api_key(
    body: SaveApiKeyRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    http_client: httpx2.AsyncClient | None = Depends(get_nebius_http_client),
) -> ApiKeyStatus:
    register_secret(body.api_key)
    # Check with Nebius before any write, so a rejected key never replaces a saved one.
    await check_api_key(body.api_key, settings, http_client=http_client)

    secret = encrypt_secret(settings.key_encryption_key, user.id, body.api_key)
    row = await _find_key(session, user)
    if row is None:
        row = NebiusApiKey(user_id=user.id)
        session.add(row)
    row.ciphertext = secret.ciphertext
    row.nonce = secret.nonce
    row.key_version = secret.key_version
    row.last4 = body.api_key[-4:]
    await session.commit()
    await session.refresh(row)
    return _status_for(row)


@router.delete("", status_code=204)
async def delete_api_key(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await session.execute(delete(NebiusApiKey).where(NebiusApiKey.user_id == user.id))
    await session.commit()
    return Response(status_code=204)
