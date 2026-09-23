import base64
import binascii
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Backend settings, read from environment variables."""

    database_url: str = Field(min_length=1)
    key_encryption_key: bytes
    auth0_domain: str = Field(min_length=1)
    auth0_audience: str = Field(min_length=1)
    chroma_url: str = "http://chroma:8000"
    # Lets an operator turn off the custom provider (an arbitrary base URL),
    # which auth-modes sets to false in demo mode on a public instance.
    allow_custom_provider: bool = True

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
