import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.models import User

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
