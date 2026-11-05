"""The first-run setup wizard's API. Every route needs a login and the setup token."""

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.models import User
from app.setup.state import require_setup
from app.setup.status import SetupStatus, build_status, complete_setup

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatus)
async def setup_status(
    user: User = Depends(require_setup),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SetupStatus:
    return await build_status(session, user, settings)


@router.post("/complete", status_code=204)
async def finish_setup(
    user: User = Depends(require_setup),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> Response:
    await complete_setup(session, user, settings)
    return Response(status_code=204)
