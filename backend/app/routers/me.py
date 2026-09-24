import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.models import User
from app.ownership import not_found
from app.user_data import delete_user_data

router = APIRouter(prefix="/api")


class MeResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    # Demo mode only.
    mode: str | None = None
    expires_at: datetime | None = None
    demo_notice_accepted: bool | None = None


@router.get("/me", response_model=MeResponse, response_model_exclude_none=True)
async def me(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> MeResponse:
    response = MeResponse(id=user.id, created_at=user.created_at)
    if settings.auth_mode == "demo":
        response.mode = "demo"
        response.expires_at = user.expires_at
        response.demo_notice_accepted = user.demo_notice_accepted_at is not None
    return response


@router.delete("/me", status_code=204)
async def delete_my_data(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete the user and everything they own: thoughts and search indexes,
    provider keys, models and settings, conversations, and usage records.

    Demo mode has "End demo" for this instead.
    """
    if settings.auth_mode == "demo":
        raise not_found()
    await delete_user_data(session, user)
    return Response(status_code=204)
