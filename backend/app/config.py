import base64
import binascii
import os
from functools import lru_cache
from typing import Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AUTH_MODES = ("oidc", "firebase", "demo")

# Settings each mode needs on the backend. The client secret and the Firebase
# web config are used only by the frontend server, which checks them itself.
_REQUIRED_BY_MODE = {
    "oidc": ("oidc_issuer", "oidc_client_id"),
    "firebase": ("firebase_project_id",),
    "demo": (),
}
# Demo mode refuses to start while any login setting is present.
_LOGIN_SETTING_PREFIXES = ("OIDC_", "FIREBASE_")


class Settings(BaseSettings):
    """Backend settings, read from environment variables."""

    # An empty value in .env means unset, as .env.example leaves them.
    model_config = SettingsConfigDict(env_ignore_empty=True)

    database_url: str = Field(min_length=1)
    key_encryption_key: bytes
    # Lets an operator turn off the custom provider (an arbitrary base URL).
    # Demo mode forces it off.
    allow_custom_provider: bool = True

    # The embedding model that builds new search indexes, called with each
    # user's own key for this provider. An existing index keeps the model it
    # was built with until the operator rebuilds it (python -m app.reembed).
    embedding_provider: str = "nebius"
    # Provisional until the embedding probe (thought-storage task 1.1).
    embedding_model: str = "Qwen/Qwen3-Embedding-8B"
    # Sent as `dimensions` to models that can shorten their vectors.
    embedding_dimensions: int | None = Field(default=None, gt=0)

    auth_mode: str | None = None
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    # Replaces the issuer's origin for server-to-server calls, for an issuer
    # whose public address the container cannot reach.
    oidc_internal_url: str | None = None
    firebase_project_id: str | None = None
    # Comma-separated addresses and @domain entries. Unset lets in anyone the
    # provider logs in.
    auth_allowed_emails: str | None = None
    demo_session_ttl_hours: float = Field(default=24, gt=0)
    demo_max_sessions: int = Field(default=500, gt=0)

    @field_validator("key_encryption_key", mode="before")
    @classmethod
    def decode_key_encryption_key(cls, value: object) -> bytes:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("KEY_ENCRYPTION_KEY is required")
        try:
            key = base64.b64decode(value.strip(), validate=True)
        except binascii.Error as exc:
            raise ValueError("KEY_ENCRYPTION_KEY must be base64") from exc
        if len(key) != 32:
            raise ValueError("KEY_ENCRYPTION_KEY must decode to 32 bytes")
        return key

    @field_validator(
        "auth_mode",
        "oidc_issuer",
        "oidc_client_id",
        "oidc_internal_url",
        "firebase_project_id",
        "auth_allowed_emails",
        mode="before",
    )
    @classmethod
    def empty_is_unset(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("embedding_provider", "embedding_model")
    @classmethod
    def embedding_setting_required(cls, value: str, info) -> str:
        value = value.strip()
        if not value:
            raise ValueError(f"{info.field_name.upper()} must not be empty")
        return value

    @field_validator("embedding_provider")
    @classmethod
    def embedding_provider_not_custom(cls, value: str) -> str:
        if value.lower() == "custom":
            raise ValueError(
                "EMBEDDING_PROVIDER cannot be custom: its address differs per user. "
                "Choose a preset from providers.yaml"
            )
        return value

    @model_validator(mode="after")
    def check_auth_mode(self) -> Self:
        if self.auth_mode is None:
            raise ValueError("AUTH_MODE is required: set it to oidc, firebase, or demo")
        mode = self.auth_mode.lower()
        if mode not in AUTH_MODES:
            raise ValueError(
                f"AUTH_MODE '{self.auth_mode}' is not valid: set it to oidc, firebase, or demo"
            )
        self.auth_mode = mode

        for field in _REQUIRED_BY_MODE[mode]:
            if getattr(self, field) is None:
                raise ValueError(f"{field.upper()} is required when AUTH_MODE is {mode}")

        if mode == "demo":
            for name, value in sorted(os.environ.items()):
                if name.upper().startswith(_LOGIN_SETTING_PREFIXES) and value.strip():
                    raise ValueError(f"Remove {name.upper()}: demo mode does not use login settings")
            if "allow_custom_provider" in self.model_fields_set and self.allow_custom_provider:
                raise ValueError(
                    "Remove ALLOW_CUSTOM_PROVIDER=true: demo mode turns the custom provider off"
                )
            self.allow_custom_provider = False
        return self

    @property
    def allowed_emails(self) -> frozenset[str] | None:
        """The allow-list entries, lowercased, or None when no list is set."""
        if self.auth_allowed_emails is None:
            return None
        entries = (entry.strip().lower() for entry in self.auth_allowed_emails.split(","))
        return frozenset(entry for entry in entries if entry)


@lru_cache
def get_settings() -> Settings:
    return Settings()
