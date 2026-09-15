import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health(session: AsyncSession = Depends(get_session)):
    """Unauthenticated liveness check that also confirms the database answers."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Health check: database unavailable", exc_info=True)
        return JSONResponse(status_code=503, content={"status": "database_unavailable"})
    return {"status": "ok"}
