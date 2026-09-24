"""Auth0 access token checks for the backend API."""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any

import httpx
import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_session
from app.errors import ApiError, ErrorCode
from app.models import User

logger = logging.getLogger(__name__)

ALGORITHM = "RS256"
JWKS_TIMEOUT_SECONDS = 5.0

JwksFetcher = Callable[[], Awaitable[dict[str, Any]]]


def unauthenticated() -> ApiError:
    return ApiError(401, ErrorCode.UNAUTHENTICATED, "A valid access token is required.")


class JwksCache:
    """Caches Auth0 signing keys and refetches at most once per interval."""

    def __init__(
        self,
        fetch: JwksFetcher,
        min_refresh_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._fetch = fetch
        self._min_refresh_seconds = min_refresh_seconds
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._last_fetch_at: float | None = None
        self._last_fetch_ok = False
        self._lock = asyncio.Lock()

    async def get_signing_key(self, kid: str) -> jwt.PyJWK:
        if kid in self._keys:
            return self._keys[kid]

        async with self._lock:
            if kid not in self._keys and self._refresh_allowed():
                await self._refresh()

        if kid in self._keys:
            return self._keys[kid]
        if not self._last_fetch_ok:
            # The token may be valid; we just can't check it right now.
            raise ApiError(
                503,
                ErrorCode.SERVICE_UNAVAILABLE,
                "Sign-in keys are unavailable. Try again shortly.",
            )
        raise unauthenticated()

    def _refresh_allowed(self) -> bool:
        return (
            self._last_fetch_at is None
            or self._clock() - self._last_fetch_at >= self._min_refresh_seconds
        )

    async def _refresh(self) -> None:
        self._last_fetch_at = self._clock()
        try:
            data = await self._fetch()
            key_set = jwt.PyJWKSet.from_dict(data)
        except (httpx.HTTPError, ValueError, KeyError, jwt.PyJWKSetError):
            logger.warning("Could not fetch Auth0 JWKS", exc_info=True)
            self._last_fetch_ok = False
            return
        self._keys = {key.key_id: key for key in key_set.keys if key.key_id}
        self._last_fetch_ok = True


def http_jwks_fetcher(issuer: str) -> JwksFetcher:
    discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"

    async def fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=JWKS_TIMEOUT_SECONDS) as client:
            discovery = await client.get(discovery_url)
            discovery.raise_for_status()
            response = await client.get(discovery.json()["jwks_uri"])
            response.raise_for_status()
            return response.json()

    return fetch


@lru_cache
def _jwks_cache_for(issuer: str) -> JwksCache:
    return JwksCache(http_jwks_fetcher(issuer))


def get_jwks_cache(settings: Settings = Depends(get_settings)) -> JwksCache:
    return _jwks_cache_for(settings.oidc_issuer or "")


async def verify_access_token(
    token: str, settings: Settings, jwks: JwksCache
) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise unauthenticated()

    kid = header.get("kid")
    if header.get("alg") != ALGORITHM or not kid:
        raise unauthenticated()

    signing_key = await jwks.get_signing_key(kid)
    try:
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[ALGORITHM],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.InvalidTokenError:
        raise unauthenticated()


_bearer = HTTPBearer(auto_error=False)


async def get_token_claims(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
    jwks: JwksCache = Depends(get_jwks_cache),
) -> dict[str, Any]:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthenticated()
    return await verify_access_token(credentials.credentials, settings, jwks)


_INSERTS_BY_DIALECT = {"postgresql": postgresql_insert, "sqlite": sqlite_insert}


async def get_or_create_user(session: AsyncSession, issuer: str, subject: str) -> User:
    """Return the user for an issuer and subject, creating it on first sight.

    INSERT ... ON CONFLICT DO NOTHING keeps concurrent first requests from
    creating duplicates without an application-level lock.
    """
    dialect = (await session.connection()).dialect.name
    insert = _INSERTS_BY_DIALECT[dialect]
    await session.execute(
        insert(User)
        .values(id=uuid.uuid4(), issuer=issuer, subject=subject)
        .on_conflict_do_nothing(index_elements=[User.issuer, User.subject])
    )
    await session.commit()
    return (
        await session.execute(
            select(User).where(User.issuer == issuer, User.subject == subject)
        )
    ).scalar_one()


async def get_current_user(
    claims: dict[str, Any] = Depends(get_token_claims),
    session: AsyncSession = Depends(get_session),
) -> User:
    return await get_or_create_user(session, claims["iss"], claims["sub"])
