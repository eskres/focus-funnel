"""Provider client creation, key checks, and error mapping.

Error codes and HTTP statuses:
- provider_key_invalid (400): the provider rejected a key the user is saving.
- provider_key_missing (409): the user has no usable saved key for the provider.
- provider_key_rejected (409): the provider rejected the user's saved key during a call.
- provider_unreachable (502): the provider timed out, refused the connection, or
  returned a server error.
- provider_rate_limited (429): the provider refused the call as too many requests.
- provider_request_refused (422): any other client error, carrying the provider's
  message.
- model_unavailable (409): with a model_id, a 404, or a 400 saying that model
  is not found, which is how a provider reports a model the key can't use.

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
from app.errors import ApiError, ErrorCode, model_unavailable
from app.log_masking import register_secret
from app.models import ProviderKey, User
from app.provider_config import (
    CUSTOM_PROVIDER_ID,
    ProviderPreset,
    custom_provider,
    get_providers_config,
)

KEY_CHECK_TIMEOUT_SECONDS = 10.0
# Sent for a provider that needs no key; OpenAI-compatible servers that don't
# check auth ignore it.
PLACEHOLDER_KEY = "not-required"


def key_invalid(provider: ProviderPreset) -> ApiError:
    return ApiError(400, ErrorCode.PROVIDER_KEY_INVALID, f"{provider.label} rejected this API key.")


def key_missing(provider: ProviderPreset) -> ApiError:
    return ApiError(
        409,
        ErrorCode.PROVIDER_KEY_MISSING,
        f"Add your {provider.label} API key in settings to use this feature.",
    )


def key_rejected(provider: ProviderPreset) -> ApiError:
    return ApiError(
        409,
        ErrorCode.PROVIDER_KEY_REJECTED,
        f"Your saved {provider.label} API key no longer works. Update it in settings.",
    )


def unreachable(provider: ProviderPreset) -> ApiError:
    return ApiError(
        502,
        ErrorCode.PROVIDER_UNREACHABLE,
        f"Couldn't reach {provider.label}. Try again.",
    )


def rate_limited(provider: ProviderPreset) -> ApiError:
    return ApiError(
        429,
        ErrorCode.PROVIDER_RATE_LIMITED,
        f"{provider.label} is rate limiting requests. Wait and try again.",
    )


def request_refused(provider: ProviderPreset, message: str) -> ApiError:
    return ApiError(422, ErrorCode.PROVIDER_REQUEST_REFUSED, f"{provider.label}: {message}")


def get_provider_http_client() -> httpx2.AsyncClient | None:
    """FastAPI dependency. None lets the SDK create its own client; tests override it."""
    return None


def make_client(
    provider: ProviderPreset,
    api_key: str,
    timeout: float = KEY_CHECK_TIMEOUT_SECONDS,
    http_client: httpx2.AsyncClient | None = None,
    max_retries: int = 0,
) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key,
        base_url=provider.base_url,
        timeout=timeout,
        max_retries=max_retries,
        http_client=http_client,
    )


def _names_model(exc: openai.APIStatusError, model_id: str) -> bool:
    """True when a refusal is about the model: a 404, or an error naming it.

    A 404 on a chat call can only mean the model; a 400 has many causes, so
    it counts only when its message names the model.
    """
    if exc.status_code == 404:
        return True
    text = str(exc).lower()
    return model_id.lower() in text and any(
        phrase in text for phrase in ("not found", "does not exist", "not available")
    )


def map_provider_error(
    exc: openai.OpenAIError,
    provider: ProviderPreset,
    *,
    saved_key: bool,
    model_id: str | None = None,
) -> ApiError | None:
    """Convert an OpenAI SDK error into a spec error, or None if it has no mapping.

    saved_key=False while checking a key the user is saving (auth failure means
    the key is invalid); saved_key=True while using a stored key (auth failure
    means the saved key stopped working).
    """
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return key_rejected(provider) if saved_key else key_invalid(provider)
    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError)):
        return unreachable(provider)
    if isinstance(exc, openai.APIStatusError):
        if model_id is not None and exc.status_code in (400, 404) and _names_model(exc, model_id):
            return model_unavailable(model_id)
        if exc.status_code == 429:
            return rate_limited(provider)
        if exc.status_code >= 500:
            return unreachable(provider)
        return request_refused(provider, str(exc))
    return None


async def check_provider_key(
    provider: ProviderPreset,
    api_key: str,
    http_client: httpx2.AsyncClient | None = None,
) -> None:
    """Raise provider_key_invalid or provider_unreachable unless the provider accepts the key.

    Lists models unless the provider has a key_check_url, for a provider whose
    model list needs no key and so accepts any key.
    """
    register_secret(api_key)
    client = make_client(provider, api_key, http_client=http_client)
    try:
        if provider.key_check_url:
            await client.get(provider.key_check_url, cast_to=object)
        else:
            await client.models.list()
    except openai.OpenAIError as exc:
        mapped = map_provider_error(exc, provider, saved_key=False)
        if mapped is None:
            raise
        raise mapped from exc
    finally:
        await client.close()


async def load_api_key(
    session: AsyncSession,
    user: User,
    provider: ProviderPreset,
    settings: Settings | None = None,
) -> str:
    """Decrypt the user's saved key for this provider.

    Raises provider_key_missing unless a usable key is found, except for a
    provider that needs no key, which gets a placeholder instead.
    """
    settings = settings or get_settings()
    row = (
        await session.execute(
            select(ProviderKey).where(
                ProviderKey.user_id == user.id, ProviderKey.provider_id == provider.id
            )
        )
    ).scalar_one_or_none()

    if row is not None and row.ciphertext is not None:
        secret = EncryptedSecret(
            ciphertext=row.ciphertext, nonce=row.nonce, key_version=row.key_version
        )
        try:
            api_key = decrypt_secret(
                settings.key_encryption_key, user.id, provider.id, secret
            )
        except DecryptionError:
            # A row that won't decrypt for this user/provider is treated as no usable key.
            pass
        else:
            register_secret(api_key)
            return api_key

    if not provider.key_required:
        return PLACEHOLDER_KEY
    raise key_missing(provider)


async def client_for(
    session: AsyncSession,
    user: User,
    provider: ProviderPreset,
    settings: Settings | None = None,
    http_client: httpx2.AsyncClient | None = None,
    *,
    timeout: float = KEY_CHECK_TIMEOUT_SECONDS,
    max_retries: int = 0,
) -> AsyncOpenAI:
    """A client for one request to this provider, using only this user's key."""
    settings = settings or get_settings()
    api_key = await load_api_key(session, user, provider, settings)
    return make_client(
        provider, api_key, timeout=timeout, http_client=http_client, max_retries=max_retries
    )


def provider_not_found() -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND, "No such provider.")


async def find_key_row(session: AsyncSession, user: User, provider_id: str) -> ProviderKey | None:
    return (
        await session.execute(
            select(ProviderKey).where(
                ProviderKey.user_id == user.id, ProviderKey.provider_id == provider_id
            )
        )
    ).scalar_one_or_none()


def resolve_provider(
    provider_id: str, settings: Settings, saved_row: ProviderKey | None = None
) -> ProviderPreset:
    """Look up a preset, or build the custom provider from the user's saved row.

    The custom provider's base URL comes only from saved_row, never from a
    request body.
    """
    if provider_id == CUSTOM_PROVIDER_ID:
        if not settings.allow_custom_provider:
            raise ApiError(
                422, ErrorCode.VALIDATION_ERROR, "Custom providers are turned off on this server."
            )
        base_url = saved_row.base_url if saved_row is not None else None
        if not base_url:
            raise provider_not_found()
        return custom_provider(base_url)

    preset = get_providers_config().get(provider_id)
    if preset is None:
        raise provider_not_found()
    return preset


async def provider_for_user(
    session: AsyncSession, user: User, provider_id: str, settings: Settings
) -> ProviderPreset:
    """The provider as this user has it configured."""
    return resolve_provider(provider_id, settings, await find_key_row(session, user, provider_id))
