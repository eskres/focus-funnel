import base64
import os

import pytest

from app.config import get_settings
from app.db import get_engine, get_sessionmaker

REQUIRED_ENV = {
    "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
    "AUTH0_DOMAIN": "test-tenant.example.com",
    "AUTH0_AUDIENCE": "https://api.focus-funnel.test",
}


@pytest.fixture(autouse=True)
def clear_settings_cache():
    for cached in (get_settings, get_engine, get_sessionmaker):
        cached.cache_clear()
    yield
    for cached in (get_settings, get_engine, get_sessionmaker):
        cached.cache_clear()


@pytest.fixture
def settings_env(monkeypatch):
    """Set a complete, valid backend environment."""
    for name, value in REQUIRED_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("KEY_ENCRYPTION_KEY", base64.b64encode(os.urandom(32)).decode())
    return monkeypatch
