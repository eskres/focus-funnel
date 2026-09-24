"""Demo session routes. They exist only in demo mode and answer 404 otherwise."""

from datetime import datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_session
from app.demo import now, start_session
from app.models import User
from app.ownership import not_found
from app.user_data import delete_user_data


def require_demo_mode(settings: Settings = Depends(get_settings)) -> None:
    if settings.auth_mode != "demo":
        raise not_found()


router = APIRouter(prefix="/api/demo", dependencies=[Depends(require_demo_mode)])


class DemoSessionResponse(BaseModel):
    # The only time the value leaves the server; only its hash is stored.
    session: str
    expires_at: datetime


@router.post("/sessions", response_model=DemoSessionResponse, status_code=201)
async def create_demo_session(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> DemoSessionResponse:
    value, expires_at = await start_session(session, settings)
    return DemoSessionResponse(session=value, expires_at=expires_at)


@router.delete("/session", status_code=204)
async def end_demo_session(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await delete_user_data(session, user)
    return Response(status_code=204)


@router.post("/notice", status_code=204)
async def accept_demo_notice(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if user.demo_notice_accepted_at is None:
        user.demo_notice_accepted_at = now()
        await session.commit()
    return Response(status_code=204)
