"""Demo mode: anonymous sessions, their expiry, and keys sent with each request.

A demo user has issuer 'demo' and, as subject, the SHA-256 hex of the session
value, so the database never holds a value that would work as a cookie.
"""

import asyncio
import base64
import hashlib
import logging
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth import Authenticator, Identity, unauthenticated
from app.config import Settings
from app.errors import demo_full, demo_session_expired
from app.models import User
from app.models.user import DEMO_ISSUER
from app.user_data import delete_user_data

logger = logging.getLogger(__name__)

SESSION_BYTES = 32
CLEANUP_INTERVAL_SECONDS = 300


def now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; they were stored as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def hash_session_value(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_session_value() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(SESSION_BYTES)).rstrip(b"=").decode()


def live_demo_users():
    return (User.issuer == DEMO_ISSUER) & (User.expires_at > now())


async def start_session(session: AsyncSession, settings: Settings) -> tuple[str, datetime]:
    """Create an anonymous user and return its session value and expiry."""
    live = (
        await session.execute(select(func.count()).select_from(User).where(live_demo_users()))
    ).scalar_one()
    if live >= settings.demo_max_sessions:
        raise demo_full()
    value = new_session_value()
    expires_at = now() + timedelta(hours=settings.demo_session_ttl_hours)
    session.add(User(issuer=DEMO_ISSUER, subject=hash_session_value(value), expires_at=expires_at))
    await session.commit()
    return value, expires_at


class DemoAuthenticator(Authenticator):
    """Finds the anonymous user behind a demo session value."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def authenticate(self, token: str) -> Identity:
        return Identity(issuer=DEMO_ISSUER, subject=hash_session_value(token))

    async def current_user(self, token: str, session: AsyncSession, settings: Settings) -> User:
        identity = await self.authenticate(token)
        user = (
            await session.execute(
                select(User).where(User.issuer == identity.issuer, User.subject == identity.subject)
            )
        ).scalar_one_or_none()
        if user is None or user.expires_at is None:
            raise unauthenticated()
        # Refused as soon as it expires, whether or not cleanup has run yet.
        if as_utc(user.expires_at) <= now():
            raise demo_session_expired()
        return user


async def delete_expired_demo_users(session: AsyncSession) -> int:
    expired = (
        await session.execute(
            select(User).where(User.issuer == DEMO_ISSUER, User.expires_at <= now())
        )
    ).scalars().all()
    for user in expired:
        await delete_user_data(session, user)
    return len(expired)


async def cleanup_loop(
    sessionmaker: Callable[[], async_sessionmaker[AsyncSession]],
    interval_seconds: float = CLEANUP_INTERVAL_SECONDS,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Delete expired demo users now and every interval; an error never stops it."""
    while True:
        try:
            async with sessionmaker()() as session:
                deleted = await delete_expired_demo_users(session)
            if deleted:
                logger.info("Deleted %d expired demo sessions", deleted)
        except Exception:
            logger.exception("Demo cleanup failed; trying again next round")
        await sleep(interval_seconds)
