from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_error_handlers
from app.log_masking import install_log_masking
from app.routers import api_key, health, me


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup, not on first request, when settings are missing or invalid.
    get_settings()
    yield


install_log_masking()

app = FastAPI(title="Focus Funnel API", lifespan=lifespan)
register_error_handlers(app)
app.include_router(health.router)
app.include_router(me.router)
app.include_router(api_key.router)
