from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.errors import register_error_handlers
from app.log_masking import install_log_masking
from app.provider_config import get_providers_config
from app.routers import health, me, providers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup, not on first request, when settings or the provider
    # configuration are missing or invalid.
    get_settings()
    get_providers_config()
    yield


install_log_masking()

app = FastAPI(title="Focus Funnel API", lifespan=lifespan)
register_error_handlers(app)
app.include_router(health.router)
app.include_router(me.router)
app.include_router(providers.router)
