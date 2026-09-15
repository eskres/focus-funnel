from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_error_handlers
from app.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup, not on first request, when settings are missing or invalid.
    get_settings()
    yield


app = FastAPI(title="Focus Funnel API", lifespan=lifespan)
register_error_handlers(app)
app.include_router(health.router)
