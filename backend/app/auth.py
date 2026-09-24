"""Turns a request's credential into the current user.

One authenticator per auth mode checks the credential and names an Identity
(issuer, subject, email). get_current_user applies the email allow-list and
finds or creates the user. Routers depend only on get_current_user.

- oidc: the provider's ID token, checked against the keys its discovery
  document names, the configured issuer, and the client id as audience.
- firebase: a Firebase ID token, checked against Google's published keys with
  the project as issuer and audience. No service account.
- demo: a demo session value, looked up by its hash (app.demo).
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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
from app.errors import ApiError, ErrorCode, not_allowed
from app.models import User

logger = logging.getLogger(__name__)

# Only asymmetric algorithms: HS* would let anyone holding the client secret
# mint tokens, and "none" is unsigned.
ASYMMETRIC_ALGORITHMS = frozenset({"RS256", "ES256", "EdDSA"})
# OIDC Core: RS256 is the default when discovery lists no algorithms.
DEFAULT_OIDC_ALGORITHMS = frozenset({"RS256"})
JWKS_TIMEOUT_SECONDS = 5.0
FIREBASE_JWKS_URL = (
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
)
FIREBASE_ISSUER_PREFIX = "https://securetoken.google.com/"

JwksFetcher = Callable[[], Awaitable[dict[str, Any]]]


def unauthenticated() -> ApiError:
    return ApiError(401, ErrorCode.UNAUTHENTICATED, "A valid login is required.")


@dataclass(frozen=True)
class Identity:
    issuer: str
    subject: str
    email: str | None = None
    email_verified: bool = False


class JwksCache:
    """Caches a provider's signing keys and refetches at most once per interval.

    algorithms reports which signing algorithms the provider allows, when the
    key source knows (from OIDC discovery); otherwise all asymmetric ones.
    """

    def __init__(
        self,
        fetch: JwksFetcher,
        min_refresh_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        algorithms: Callable[[], frozenset[str]] = lambda: ASYMMETRIC_ALGORITHMS,
    ):
        self._fetch = fetch
        self._min_refresh_seconds = min_refresh_seconds
        self._clock = clock
        self._algorithms = algorithms
        self._keys: dict[str, jwt.PyJWK] = {}
        self._last_fetch_at: float | None = None
        self._last_fetch_ok = False
        self._lock = asyncio.Lock()

    @property
    def algorithms(self) -> frozenset[str]:
        return self._algorithms() & ASYMMETRIC_ALGORITHMS

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
        except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWKSetError):
            logger.warning("Could not fetch the login provider's signing keys", exc_info=True)
            self._last_fetch_ok = False
            return
        self._keys = {key.key_id: key for key in key_set.keys if key.key_id}
        self._last_fetch_ok = True


def replace_origin(url: str, public_origin: str, internal_url: str | None) -> str:
    """Point a URL on the public origin at the internal address instead.

    The discovery document names the public origin on every endpoint, which a
    container may not reach. URLs on other origins are left alone.
    """
    if not internal_url:
        return url
    parts = urlsplit(url)
    public = urlsplit(public_origin)
    if (parts.scheme, parts.netloc) != (public.scheme, public.netloc):
        return url
    internal = urlsplit(internal_url)
    return urlunsplit((internal.scheme, internal.netloc, parts.path, parts.query, parts.fragment))


class OidcDiscovery:
    """Reads the issuer's discovery document and fetches the keys it names."""

    def __init__(
        self,
        issuer: str,
        internal_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.issuer = issuer
        self.internal_url = internal_url
        # Tests pass a mock transport.
        self._transport = transport
        self.algorithms: frozenset[str] = DEFAULT_OIDC_ALGORITHMS

    @property
    def discovery_url(self) -> str:
        url = f"{self.issuer.rstrip('/')}/.well-known/openid-configuration"
        return replace_origin(url, self.issuer, self.internal_url)

    async def fetch_jwks(self) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=JWKS_TIMEOUT_SECONDS, transport=self._transport
        ) as client:
            response = await client.get(self.discovery_url)
            response.raise_for_status()
            document = response.json()
            listed = document.get("id_token_signing_alg_values_supported")
            if isinstance(listed, list):
                self.algorithms = frozenset(str(alg) for alg in listed)
            jwks_uri = replace_origin(document["jwks_uri"], self.issuer, self.internal_url)
            keys = await client.get(jwks_uri)
            keys.raise_for_status()
            return keys.json()


def http_jwks_fetcher(url: str) -> JwksFetcher:
    async def fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=JWKS_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    return fetch


@lru_cache
def _oidc_jwks_cache(issuer: str, internal_url: str | None) -> JwksCache:
    discovery = OidcDiscovery(issuer, internal_url)
    return JwksCache(discovery.fetch_jwks, algorithms=lambda: discovery.algorithms)


@lru_cache
def _firebase_jwks_cache() -> JwksCache:
    return JwksCache(http_jwks_fetcher(FIREBASE_JWKS_URL))


def get_jwks_cache(settings: Settings = Depends(get_settings)) -> JwksCache | None:
    """The signing keys of the configured provider; None in demo mode."""
    if settings.auth_mode == "oidc":
        return _oidc_jwks_cache(settings.oidc_issuer or "", settings.oidc_internal_url)
    if settings.auth_mode == "firebase":
        return _firebase_jwks_cache()
    return None


class Authenticator:
    """Checks a bearer credential and returns the user it names."""

    async def authenticate(self, token: str) -> Identity:
        raise NotImplementedError

    async def current_user(
        self, token: str, session: AsyncSession, settings: Settings
    ) -> User:
        identity = await self.authenticate(token)
        check_allowed(identity, settings.allowed_emails)
        return await get_or_create_user(session, identity.issuer, identity.subject)


class JwtAuthenticator(Authenticator):
    """Verifies a signed ID token against a provider's published keys."""

    def __init__(self, issuer: str, audience: str, jwks: JwksCache):
        self.issuer = issuer
        self.audience = audience
        self.jwks = jwks

    async def authenticate(self, token: str) -> Identity:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            raise unauthenticated()

        algorithm = header.get("alg")
        kid = header.get("kid")
        if algorithm not in ASYMMETRIC_ALGORITHMS or not kid:
            raise unauthenticated()

        signing_key = await self.jwks.get_signing_key(kid)
        # Checked after the fetch, which is when discovery says what is allowed.
        if algorithm not in self.jwks.algorithms:
            raise unauthenticated()
        try:
            # The audience check accepts "aud" as a string or as a list that
            # holds the audience; Pocket ID sends a list.
            claims = jwt.decode(
                token,
                signing_key.key,
                algorithms=[algorithm],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except jwt.InvalidTokenError:
            raise unauthenticated()
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject:
            raise unauthenticated()
        email = claims.get("email")
        return Identity(
            issuer=claims["iss"],
            subject=subject,
            email=email if isinstance(email, str) else None,
            email_verified=claims.get("email_verified") is True,
        )


class OidcAuthenticator(JwtAuthenticator):
    def __init__(self, settings: Settings, jwks: JwksCache):
        super().__init__(settings.oidc_issuer or "", settings.oidc_client_id or "", jwks)


class FirebaseAuthenticator(JwtAuthenticator):
    def __init__(self, settings: Settings, jwks: JwksCache):
        project = settings.firebase_project_id or ""
        super().__init__(FIREBASE_ISSUER_PREFIX + project, project, jwks)


def email_allowed(email: str, allowed: frozenset[str]) -> bool:
    email = email.strip().lower()
    _, at, domain = email.rpartition("@")
    return email in allowed or (bool(at) and f"@{domain}" in allowed)


def check_allowed(identity: Identity, allowed: frozenset[str] | None) -> None:
    """Refuse a user the allow-list does not let in, before any user row exists."""
    if allowed is None:
        return
    if not identity.email or not identity.email_verified:
        raise not_allowed()
    if not email_allowed(identity.email, allowed):
        raise not_allowed()


def get_authenticator(
    settings: Settings = Depends(get_settings),
    jwks: JwksCache | None = Depends(get_jwks_cache),
) -> Authenticator:
    if settings.auth_mode == "oidc" and jwks is not None:
        return OidcAuthenticator(settings, jwks)
    if settings.auth_mode == "firebase" and jwks is not None:
        return FirebaseAuthenticator(settings, jwks)
    raise RuntimeError(f"No authenticator for AUTH_MODE {settings.auth_mode!r}")


_bearer = HTTPBearer(auto_error=False)


def bearer_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthenticated()
    return credentials.credentials


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
    token: str = Depends(bearer_token),
    authenticator: Authenticator = Depends(get_authenticator),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User:
    return await authenticator.current_user(token, session, settings)
