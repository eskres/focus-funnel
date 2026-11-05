"""When setup is open, the setup token, and the dependency that checks it.

The token is printed to stderr at each start while setup is open, never
through logging, and only its SHA-256 hex digest is stored. A request to a
setup route needs a login and the current token in the X-Setup-Token header.
"""

import hashlib
import hmac
import os
import secrets
import sys
from collections.abc import Callable
from datetime import UTC, datetime

from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_session, get_sessionmaker
from app.errors import setup_token_invalid
from app.models import SetupState, User
from app.models.setup_state import SETUP_STATE_ID
from app.ownership import not_found

SETUP_MODES = ("oidc", "firebase")
SETUP_MIGRATION = "4d7a1c9e2b60 (add setup state)"


def setup_enabled(settings: Settings) -> bool:
    """Whether this instance's settings allow setup to open at all."""
    return settings.auth_mode in SETUP_MODES and settings.setup_wizard


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def get_setup_state(session: AsyncSession, *, for_update: bool = False) -> SetupState | None:
    """The setup row, read fresh from the database (never from the session's cache)."""
    query = select(SetupState).where(SetupState.id == SETUP_STATE_ID)
    if for_update:
        query = query.with_for_update()
    query = query.execution_options(populate_existing=True)
    return (await session.execute(query)).scalar_one_or_none()


def is_open(settings: Settings, row: SetupState | None) -> bool:
    return setup_enabled(settings) and row is not None and row.completed_at is None


def _setup_address() -> str:
    # The backend container gets APP_BASE_URL from .env; Settings does not hold it.
    base = os.environ.get("APP_BASE_URL", "").strip().rstrip("/")
    if base:
        return f"Open {base}/setup (the app's /setup, not Pocket ID's), log in, and enter this token."
    return (
        "Open /setup on the app (port 3000 by default, not Pocket ID's /setup), "
        "log in, and enter this token."
    )


def _say(text: str) -> None:
    # stderr, not logging: no log configuration can hide it, and it is never
    # registered with log masking.
    print(text, file=sys.stderr, flush=True)


async def open_setup(
    settings: Settings,
    sessionmaker: Callable[[], async_sessionmaker[AsyncSession]] = get_sessionmaker,
) -> None:
    """Print a new setup token and store its hash, when setup is open.

    Checks the settings before touching the database, so an instance with
    setup off or in demo mode never reads the table.
    """
    if not setup_enabled(settings):
        return
    async with sessionmaker()() as session:
        row = await get_setup_state(session, for_update=True)
        if row is None:
            _say(
                "Focus Funnel setup record missing: setup is closed. The setup_state row "
                f"is created only by the migration {SETUP_MIGRATION}."
            )
            return
        if row.completed_at is not None:
            return
        token = secrets.token_urlsafe(24)
        row.token_hash = hash_token(token)
        row.token_created_at = datetime.now(UTC)
        await session.commit()
    _say(
        "\n".join(
            (
                "Focus Funnel setup is open.",
                f"Setup token: {token}",
                _setup_address(),
                "A new token is printed each time the backend starts, until setup is finished.",
            )
        )
    )


async def require_setup(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    token: str | None = Header(default=None, alias="X-Setup-Token"),
) -> User:
    """Let a logged-in user with the current setup token through.

    Closed setup answers 404 before the token is looked at; a missing, empty,
    wrong, or old token, or no stored hash, answers 403 with one message.
    """
    row = await get_setup_state(session)
    if not is_open(settings, row):
        raise not_found()
    expected = row.token_hash
    if not token or expected is None:
        raise setup_token_invalid()
    if not hmac.compare_digest(hash_token(token), expected):
        raise setup_token_invalid()
    return user
