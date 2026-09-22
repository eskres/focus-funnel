import base64
import os

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import app


def test_valid_environment_loads(settings_env):
    settings = Settings()
    assert len(settings.key_encryption_key) == 32


def test_allow_custom_provider_defaults_on(settings_env):
    assert Settings().allow_custom_provider is True


def test_allow_custom_provider_can_be_turned_off(settings_env):
    settings_env.setenv("ALLOW_CUSTOM_PROVIDER", "false")
    assert Settings().allow_custom_provider is False


@pytest.mark.parametrize(
    "name", ["DATABASE_URL", "KEY_ENCRYPTION_KEY", "AUTH0_DOMAIN", "AUTH0_AUDIENCE"]
)
def test_missing_required_variable_fails(settings_env, name):
    settings_env.delenv(name)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize(
    "name", ["DATABASE_URL", "KEY_ENCRYPTION_KEY", "AUTH0_DOMAIN", "AUTH0_AUDIENCE"]
)
def test_empty_required_variable_fails(settings_env, name):
    settings_env.setenv(name, "  " if name == "KEY_ENCRYPTION_KEY" else "")
    with pytest.raises(ValidationError):
        Settings()


def test_key_that_is_not_base64_fails(settings_env):
    settings_env.setenv("KEY_ENCRYPTION_KEY", "not base64 at all!")
    with pytest.raises(ValidationError, match="base64"):
        Settings()


def test_key_with_wrong_length_fails(settings_env):
    settings_env.setenv("KEY_ENCRYPTION_KEY", base64.b64encode(os.urandom(16)).decode())
    with pytest.raises(ValidationError, match="32 bytes"):
        Settings()


def test_app_startup_fails_without_settings(settings_env):
    settings_env.delenv("KEY_ENCRYPTION_KEY")
    with pytest.raises(ValidationError):
        with TestClient(app):
            pass


def test_app_starts_with_valid_settings(settings_env):
    with TestClient(app):
        pass
