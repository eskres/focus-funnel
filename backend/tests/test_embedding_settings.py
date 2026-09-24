"""Embedding settings (thought-storage task 3.1)."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import app
from app.models import User
from app.thoughts.embeddings import EmbeddingConfigError, resolve_embedding_model


def test_defaults_load(settings_env):
    settings = Settings()
    assert settings.embedding_provider == "nebius"
    assert settings.embedding_model
    assert settings.embedding_dimensions is None


def test_values_are_read(settings_env):
    settings_env.setenv("EMBEDDING_PROVIDER", "openrouter")
    settings_env.setenv("EMBEDDING_MODEL", "some/embedding-model")
    settings_env.setenv("EMBEDDING_DIMENSIONS", "512")
    settings = Settings()
    assert (settings.embedding_provider, settings.embedding_model) == (
        "openrouter",
        "some/embedding-model",
    )
    assert settings.embedding_dimensions == 512


def test_custom_provider_is_refused(settings_env):
    settings_env.setenv("EMBEDDING_PROVIDER", "custom")
    with pytest.raises(ValidationError, match="EMBEDDING_PROVIDER"):
        Settings()


def test_empty_model_is_refused(settings_env):
    settings_env.setenv("EMBEDDING_MODEL", "   ")
    with pytest.raises(ValidationError, match="EMBEDDING_MODEL"):
        Settings()


@pytest.mark.parametrize("value", ["0", "-3"])
def test_dimension_below_one_is_refused(settings_env, value):
    settings_env.setenv("EMBEDDING_DIMENSIONS", value)
    with pytest.raises(ValidationError, match="embedding_dimensions"):
        Settings()


def test_unknown_provider_stops_startup(settings_env):
    settings_env.setenv("EMBEDDING_PROVIDER", "no-such-provider")
    with pytest.raises(EmbeddingConfigError, match="EMBEDDING_PROVIDER 'no-such-provider'"):
        with TestClient(app):
            pass


def test_resolver_gives_every_user_the_instance_setting(settings_env):
    settings_env.setenv("EMBEDDING_DIMENSIONS", "256")
    settings = Settings()
    choices = {
        resolve_embedding_model(User(issuer="a", subject=subject), settings)
        for subject in ("one", "two")
    }
    assert len(choices) == 1
    choice = choices.pop()
    assert (choice.provider_id, choice.model, choice.dimensions) == (
        "nebius",
        settings.embedding_model,
        256,
    )
