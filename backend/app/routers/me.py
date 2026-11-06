import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_session, get_sessionmaker
from app.demo import as_utc
from app.models import User
from app.ownership import not_found
from app.thoughts import export
from app.user_data import (
    delete_user_content,
    delete_user_data,
    delete_user_usage,
    stop_and_claim,
)

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
async def delete_my_account(
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
    # Running answers stop first and store their usage; one that still runs
    # makes this answer 409 and delete nothing (design decision 13).
    await stop_and_claim(session, user.id)
    await delete_user_data(session, user)
    return Response(status_code=204)


@router.delete("/me/content", status_code=204)
async def delete_my_content(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete the user's thoughts, search indexes, conversations, and messages.

    Keeps the account, provider keys, model settings, and usage records.
    """
    if settings.auth_mode == "demo":
        raise not_found()
    await stop_and_claim(session, user.id)
    await delete_user_content(session, user)
    return Response(status_code=204)


@router.delete("/me/usage", status_code=204)
async def delete_my_usage(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Delete the user's usage records, and nothing else."""
    if settings.auth_mode == "demo":
        raise not_found()
    await delete_user_usage(session, user)
    return Response(status_code=204)


@router.get("/me/export")
async def export_my_thoughts(
    format: Literal["json", "markdown"] = Query(),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """All the user's thoughts as one JSON or Markdown file, streamed
    (thought-export design decisions 1 to 8). Demo mode is offered too.

    Everything that can refuse comes before the first byte: the login, the
    format, and the one-export-per-format lease, taken last.
    """
    user_id = user.id
    # The demo session's end, aware, so the lease can compare it with
    # demo.now() on SQLite too (design decision 12).
    expires_at = as_utc(user.expires_at) if user.expires_at is not None else None
    # The request's session would otherwise stay open, idle in a
    # transaction, until the stream ends; the export reads through its own.
    await session.close()
    exported_at = export.utcnow()
    lease = export.take_lease(user_id, format, expires_at)
    try:
        batches = export.export_thoughts(get_sessionmaker(), user_id, lease)
        return export.ExportResponse(lease, batches, exported_at)
    except BaseException:
        export.release(lease)
        raise
