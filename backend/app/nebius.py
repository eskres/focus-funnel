"""Nebius client creation, key checks, and error mapping.

Error codes and HTTP statuses:
- nebius_key_invalid (400): Nebius rejected a key the user is saving.
- nebius_key_missing (409): the user has no usable saved key.
- nebius_key_rejected (409): Nebius rejected the user's saved key during a call.
- nebius_unreachable (502): Nebius timed out, refused the connection, or failed.

The openai SDK sends requests through the httpx2 package. Tests inject an
httpx2.AsyncClient with a mock transport through the http_client arguments.
"""

import httpx2
import openai
from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.crypto import DecryptionError, EncryptedSecret, decrypt_secret
from app.errors import ApiError, ErrorCode
from app.log_masking import register_secret
from app.models import NebiusApiKey, User

KEY_CHECK_TIMEOUT_SECONDS = 10.0


def key_invalid() -> ApiError:
    return ApiError(400, ErrorCode.NEBIUS_KEY_INVALID, "Nebius rejected this API key.")


def key_missing() -> ApiError:
    return ApiError(
        409,
        ErrorCode.NEBIUS_KEY_MISSING,
        "Add your Nebius API key in settings to use this feature.",
    )


def key_rejected() -> ApiError:
    return ApiError(
        409,
        ErrorCode.NEBIUS_KEY_REJECTED,
        "Your saved Nebius API key no longer works. Update it in settings.",
    )


def unreachable() -> ApiError:
    return ApiError(
        502,
        ErrorCode.NEBIUS_UNREACHABLE,
        "Couldn't reach Nebius to check the key. Try again.",
    )


def get_nebius_http_client() -> httpx2.AsyncClient | None:
    """FastAPI dependency. None lets the SDK create its own client; tests override it."""
    return None


def make_client(
    api_key: str,
    settings: Settings,
    timeout: float = KEY_CHECK_TIMEOUT_SECONDS,
    http_client: httpx2.AsyncClient | None = None,
) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key,
        base_url=settings.nebius_base_url,
        timeout=timeout,
        max_retries=0,
        http_client=http_client,
    )


def map_nebius_error(exc: openai.OpenAIError, *, saved_key: bool) -> ApiError | None:
    """Convert an OpenAI SDK error into a spec error, or None if it has no mapping.

    saved_key=False while checking a key the user is saving (auth failure means
    the key is invalid); saved_key=True while using a stored key (auth failure
    means the saved key stopped working).
    """
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return key_rejected() if saved_key else key_invalid()
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return unreachable()
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
        return unreachable()
    return None


async def check_api_key(
    api_key: str,
    settings: Settings | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> None:
    """Raise nebius_key_invalid or nebius_unreachable unless Nebius accepts the key."""
    register_secret(api_key)
    client = make_client(api_key, settings or get_settings(), http_client=http_client)
    try:
        await client.models.list()
    except openai.OpenAIError as exc:
        mapped = map_nebius_error(exc, saved_key=False)
        if mapped is None:
            raise
        raise mapped from exc
    finally:
        await client.close()


async def load_api_key(
    session: AsyncSession, user: User, settings: Settings | None = None
) -> str:
    """Decrypt the user's saved key, or raise nebius_key_missing if none is usable."""
    settings = settings or get_settings()
    row = (
        await session.execute(select(NebiusApiKey).where(NebiusApiKey.user_id == user.id))
    ).scalar_one_or_none()
    if row is None:
        raise key_missing()
    secret = EncryptedSecret(
        ciphertext=row.ciphertext, nonce=row.nonce, key_version=row.key_version
    )
    try:
        api_key = decrypt_secret(settings.key_encryption_key, user.id, secret)
    except DecryptionError:
        # A row that won't decrypt for this user is treated as no usable key.
        raise key_missing()
    register_secret(api_key)
    return api_key


async def client_for(
    session: AsyncSession,
    user: User,
    settings: Settings | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> AsyncOpenAI:
    """A Nebius client for one request, using only this user's key."""
    settings = settings or get_settings()
    api_key = await load_api_key(session, user, settings)
    return make_client(api_key, settings, http_client=http_client)
