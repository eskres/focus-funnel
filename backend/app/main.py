import asyncio
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.chat.config import get_chat_config
from app.config import get_settings
from app.db import get_engine, get_sessionmaker
from app.demo import cleanup_loop
from app.errors import register_error_handlers
from app.log_masking import install_log_masking
from app.provider_config import get_providers_config
from app.routers import (
    chat,
    conversations,
    demo,
    health,
    me,
    providers,
    settings_models,
    usage,
)
from app.thoughts import check_vector_extension
from app.thoughts.embeddings import check_embedding_provider


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at startup, not on first request, when settings or the provider or
    # chat configuration are missing or invalid.
    settings = get_settings()
    check_embedding_provider(settings, get_providers_config())
    get_chat_config()
    async with get_engine().connect() as connection:
        await check_vector_extension(connection)
    cleanup = None
    if settings.auth_mode == "demo":
        cleanup = asyncio.create_task(cleanup_loop(get_sessionmaker))
    yield
    if cleanup is not None:
        cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup


install_log_masking()

app = FastAPI(title="Focus Funnel API", lifespan=lifespan)
register_error_handlers(app)
app.include_router(health.router)
app.include_router(me.router)
app.include_router(demo.router)
app.include_router(providers.router)
app.include_router(settings_models.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(usage.router)
