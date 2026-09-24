"""Demo mode: provider keys held by the visitor's browser.

The frontend server sends the held keys with each request in the
X-Provider-Keys header. The backend uses them for that request only: they go
into a context variable, never into the database, and are masked in logs.
"""

import base64
import binascii
import json
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Request

from app.config import Settings
from app.log_masking import register_secret

# base64url JSON of {provider_id: {"key": ..., "expires_at": ...}}.
PROVIDER_KEYS_HEADER = "X-Provider-Keys"


@dataclass(frozen=True)
class HeldKey:
    key: str
    expires_at: datetime | None


_held_keys: ContextVar[dict[str, HeldKey] | None] = ContextVar("demo_held_keys", default=None)


def parse_provider_keys(header: str | None) -> dict[str, HeldKey]:
    """Read the X-Provider-Keys header. A malformed header holds no keys."""
    if not header:
        return {}
    try:
        padded = header + "=" * (-len(header) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    keys = {}
    for provider_id, entry in data.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str) or not entry["key"]:
            continue
        register_secret(entry["key"])
        expires_at = None
        if isinstance(entry.get("expires_at"), str):
            try:
                expires_at = _as_utc(datetime.fromisoformat(entry["expires_at"]))
            except ValueError:
                pass
        keys[str(provider_id)] = HeldKey(key=entry["key"], expires_at=expires_at)
    return keys


def use_request_keys(request: Request, settings: Settings) -> None:
    """Make this request's held keys available to the key lookup, in demo mode only."""
    if settings.auth_mode == "demo":
        _held_keys.set(parse_provider_keys(request.headers.get(PROVIDER_KEYS_HEADER)))
    else:
        _held_keys.set(None)


def held_keys() -> dict[str, HeldKey]:
    """The keys sent with the current request; empty outside demo mode."""
    return _held_keys.get() or {}


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
