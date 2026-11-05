"""The setup status for the logged-in operator, and finishing setup.

The user items (search_key, chat_model) read the caller's saved key rows and
default model. A saved key is decrypted here only to learn whether the
current KEY_ENCRYPTION_KEY can still read it; the value is dropped at once,
never registered for log masking, and never returned. Building the status
makes no outbound call (openspec self-hosting-setup design decision 7).
"""

import sys
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.loadout import get_default_model
from app.config import Settings
from app.crypto import DecryptionError, EncryptedSecret, decrypt_secret
from app.db import get_engine
from app.errors import ApiError, setup_incomplete
from app.models import ProviderKey, User
from app.ownership import not_found
from app.provider_config import CUSTOM_PROVIDER_ID, ProviderPreset, get_providers_config
from app.providers import find_key_row, provider_for_user
from app.setup.checks import (
    Connect,
    SetupItem,
    allow_list_item,
    connectors_item,
    custom_provider_item,
    database_item,
    encryption_key_item,
    login_item,
)
from app.setup.state import get_setup_state, is_open

UNREADABLE = (
    "cannot be read with the current KEY_ENCRYPTION_KEY; save it again in the provider step."
)


class SetupStatus(BaseModel):
    auth_mode: str
    ready: bool
    items: list[SetupItem]

    def first_missing(self) -> SetupItem | None:
        return next((item for item in self.items if item.required and item.state != "ok"), None)


def _saved_key_state(settings: Settings, user: User, row: ProviderKey | None) -> str:
    """"none" (no saved key), "readable", or "unreadable" with the current key."""
    if row is None or row.ciphertext is None:
        return "none"
    secret = EncryptedSecret(
        ciphertext=row.ciphertext, nonce=row.nonce, key_version=row.key_version
    )
    try:
        decrypt_secret(settings.key_encryption_key, user.id, row.provider_id, secret)
    except DecryptionError:
        return "unreadable"
    return "readable"


def _key_usable(provider: ProviderPreset, key_state: str) -> str:
    """"ok", "missing", or "failed", following load_api_key: a provider that
    needs no key works without one, even when a saved key cannot be read."""
    if key_state == "readable" or not provider.key_required:
        return "ok"
    return "failed" if key_state == "unreadable" else "missing"


async def search_key_item(session: AsyncSession, user: User, settings: Settings) -> SetupItem:
    def item(state, message):
        return SetupItem(
            id="search_key",
            state=state,
            required=True,
            message=message,
            settings=["EMBEDDING_PROVIDER", "EMBEDDING_MODEL"],
        )

    provider = get_providers_config().get(settings.embedding_provider)
    if provider is None:
        # The server refuses to start on this, so it is seen only if the
        # providers file changed under a running server.
        return item(
            "missing",
            f"Search uses '{settings.embedding_provider}', which is not a provider preset.",
        )
    key_state = _saved_key_state(settings, user, await find_key_row(session, user, provider.id))
    state = _key_usable(provider, key_state)
    if state == "ok":
        how = "your key for it is saved." if key_state == "readable" else "it needs no key."
        return item("ok", f"Search uses {provider.label}, and {how}")
    if state == "failed":
        return item("failed", f"Search uses {provider.label}. The saved key {UNREADABLE}")
    return item("missing", f"Search uses {provider.label}. Save a key for it in the provider step.")


async def chat_model_item(session: AsyncSession, user: User, settings: Settings) -> SetupItem:
    def item(state, message):
        return SetupItem(id="chat_model", state=state, required=True, message=message, settings=[])

    default = await get_default_model(session, user)
    if default is None:
        return item("missing", "Choose a default model in the model step.")
    try:
        provider = await provider_for_user(session, user, default.provider_id, settings)
    except ApiError:
        if default.provider_id == CUSTOM_PROVIDER_ID:
            gone = (
                "the custom provider ('custom'), and custom providers are turned off "
                "on this server"
                if not settings.allow_custom_provider
                else "the custom provider ('custom'), which has no saved address"
            )
        else:
            gone = f"the provider '{default.provider_id}', which this server no longer offers"
        return item(
            "missing",
            f"Your default model {default.model} uses {gone}. "
            "Choose another default model in the model step.",
        )
    row = await find_key_row(session, user, provider.id)
    state = _key_usable(provider, _saved_key_state(settings, user, row))
    if state == "ok":
        return item("ok", f"Your default model is {default.model} from {provider.label}.")
    if state == "failed":
        return item(
            "failed",
            f"Your default model {default.model} uses {provider.label}, and the saved key "
            f"{UNREADABLE}",
        )
    return item(
        "missing",
        f"Your default model {default.model} needs a {provider.label} key. "
        "Save one in the provider step.",
    )


async def build_status(
    session: AsyncSession, user: User, settings: Settings, connect: Connect | None = None
) -> SetupStatus:
    """The status for this caller, in the order of design decision 7's table."""
    providers = get_providers_config()
    items = [
        await database_item(connect or get_engine().connect),
        encryption_key_item(),
        login_item(settings),
        allow_list_item(settings),
        await search_key_item(session, user, settings),
        await chat_model_item(session, user, settings),
        custom_provider_item(settings, providers),
        connectors_item(settings),
    ]
    ready = all(item.state == "ok" for item in items if item.required)
    return SetupStatus(auth_mode=settings.auth_mode or "", ready=ready, items=items)


async def complete_setup(
    session: AsyncSession, user: User, settings: Settings, connect: Connect | None = None
) -> None:
    """Close setup for good when the caller's status is ready.

    The row is locked, so a second, concurrent request waits and then finds
    setup closed (404). Raises setup_incomplete (409) with the first missing
    required item's message, leaving setup open.
    """
    row = await get_setup_state(session, for_update=True)
    if not is_open(settings, row):
        raise not_found()
    status = await build_status(session, user, settings, connect)
    missing = status.first_missing()
    if missing is not None:
        raise setup_incomplete(missing.message)
    row.completed_at = datetime.now(UTC)
    row.token_hash = None
    await session.commit()
    print("Setup is complete.", file=sys.stderr, flush=True)
