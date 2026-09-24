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
    "name", ["DATABASE_URL", "KEY_ENCRYPTION_KEY", "AUTH_MODE", "OIDC_ISSUER", "OIDC_CLIENT_ID"]
)
def test_missing_required_variable_fails(settings_env, name):
    settings_env.delenv(name)
    with pytest.raises(ValidationError, match=name if name.startswith(("AUTH", "OIDC")) else None):
        Settings()


@pytest.mark.parametrize(
    "name", ["DATABASE_URL", "KEY_ENCRYPTION_KEY", "AUTH_MODE", "OIDC_ISSUER", "OIDC_CLIENT_ID"]
)
def test_empty_required_variable_fails(settings_env, name):
    settings_env.setenv(name, "  " if name == "KEY_ENCRYPTION_KEY" else "")
    with pytest.raises(ValidationError):
        Settings()


def use_mode(env, mode: str) -> None:
    """Switch the valid oidc test environment to another mode."""
    env.setenv("AUTH_MODE", mode)
    for name in ("OIDC_ISSUER", "OIDC_CLIENT_ID"):
        env.delenv(name)


def test_missing_mode_names_the_setting_and_its_values(settings_env):
    settings_env.delenv("AUTH_MODE")
    with pytest.raises(ValidationError) as error:
        Settings()
    message = str(error.value)
    assert "AUTH_MODE" in message
    for mode in ("oidc", "firebase", "demo"):
        assert mode in message


def test_unknown_mode_names_the_refused_value(settings_env):
    settings_env.setenv("AUTH_MODE", "auth0")
    with pytest.raises(ValidationError, match="AUTH_MODE 'auth0'"):
        Settings()


def test_oidc_mode_loads(settings_env):
    settings = Settings()
    assert settings.auth_mode == "oidc"
    assert settings.oidc_internal_url is None
    assert settings.allow_custom_provider is True


def test_firebase_mode_needs_the_project_id(settings_env):
    use_mode(settings_env, "firebase")
    with pytest.raises(ValidationError, match="FIREBASE_PROJECT_ID"):
        Settings()

    settings_env.setenv("FIREBASE_PROJECT_ID", "focus-funnel")
    assert Settings().firebase_project_id == "focus-funnel"


def test_demo_mode_loads_and_turns_the_custom_provider_off(settings_env):
    use_mode(settings_env, "demo")
    settings = Settings()
    assert settings.auth_mode == "demo"
    assert settings.allow_custom_provider is False
    assert settings.demo_session_ttl_hours == 24
    assert settings.demo_max_sessions == 500


@pytest.mark.parametrize(
    "name",
    ["OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_SCOPES", "OIDC_INTERNAL_URL",
     "FIREBASE_PROJECT_ID", "FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN"],
)
def test_demo_mode_refuses_login_settings(settings_env, name):
    use_mode(settings_env, "demo")
    settings_env.setenv(name, "some-value")
    with pytest.raises(ValidationError, match=f"Remove {name}"):
        Settings()


def test_demo_mode_ignores_empty_login_settings(settings_env):
    use_mode(settings_env, "demo")
    settings_env.setenv("OIDC_ISSUER", "")
    assert Settings().auth_mode == "demo"


def test_demo_mode_refuses_an_explicit_custom_provider(settings_env):
    use_mode(settings_env, "demo")
    settings_env.setenv("ALLOW_CUSTOM_PROVIDER", "true")
    with pytest.raises(ValidationError, match="ALLOW_CUSTOM_PROVIDER"):
        Settings()


def test_demo_mode_accepts_the_custom_provider_turned_off(settings_env):
    use_mode(settings_env, "demo")
    settings_env.setenv("ALLOW_CUSTOM_PROVIDER", "false")
    assert Settings().allow_custom_provider is False


def test_empty_values_count_as_unset(settings_env):
    settings_env.setenv("ALLOW_CUSTOM_PROVIDER", "")
    settings_env.setenv("OIDC_INTERNAL_URL", "")
    settings = Settings()
    assert settings.allow_custom_provider is True
    assert settings.oidc_internal_url is None


def test_allow_list_is_parsed_lowercase(settings_env):
    settings_env.setenv("AUTH_ALLOWED_EMAILS", " Ana@Example.org, @Team.example ,,")
    assert Settings().allowed_emails == frozenset({"ana@example.org", "@team.example"})


def test_no_allow_list_by_default(settings_env):
    assert Settings().allowed_emails is None


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
