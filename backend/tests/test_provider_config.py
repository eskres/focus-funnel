from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.provider_config import (
    CUSTOM_PROVIDER_ID,
    ProviderConfigError,
    custom_provider,
    get_providers_config,
    load_providers_config,
)

FIXTURES = Path(__file__).parent / "fixtures" / "providers"


def test_valid_file_loads():
    config = load_providers_config(FIXTURES / "valid.yaml")

    nebius = config.get("nebius")
    assert nebius is not None
    assert nebius.base_url == "https://api.tokenfactory.nebius.com/v1/"
    assert nebius.key_required is True
    assert nebius.capabilities.model_list.prices is True
    assert nebius.capabilities.stream_usage == "final_chunk"

    local = config.get("local")
    assert local is not None
    assert local.key_required is False
    assert local.capabilities.model_list.prices is False
    assert local.capabilities.stream_usage == "none"


def test_missing_file_fails():
    with pytest.raises(ProviderConfigError, match="not found"):
        load_providers_config(FIXTURES / "does_not_exist.yaml")


def test_missing_base_url_fails_naming_the_preset():
    with pytest.raises(ProviderConfigError, match="nebius.*base_url"):
        load_providers_config(FIXTURES / "missing_base_url.yaml")


def test_unknown_stream_usage_fails_naming_the_preset():
    with pytest.raises(ProviderConfigError, match="nebius.*stream_usage"):
        load_providers_config(FIXTURES / "bad_stream_usage.yaml")


def test_missing_capability_fails_naming_the_preset_and_capability():
    with pytest.raises(ProviderConfigError, match="nebius.*model_list.features"):
        load_providers_config(FIXTURES / "missing_capability.yaml")


def test_duplicate_id_fails_naming_the_preset():
    with pytest.raises(ProviderConfigError, match="nebius"):
        load_providers_config(FIXTURES / "duplicate_id.yaml")


def test_missing_key_url_fails_naming_the_preset():
    with pytest.raises(ProviderConfigError, match="nebius.*key_url"):
        load_providers_config(FIXTURES / "no_key_url.yaml")


def test_shipped_providers_yaml_loads():
    """The real config file the app starts with must itself be valid."""
    config = load_providers_config()
    assert set(config.providers) == {"nebius", "nvidia", "openrouter"}


def test_shipped_nvidia_and_openrouter_have_probed_capabilities():
    config = load_providers_config()

    nvidia = config.get("nvidia")
    assert nvidia.capabilities.model_list.prices is False
    assert nvidia.capabilities.model_list.context_length is False
    assert nvidia.capabilities.model_list.features is False
    assert nvidia.capabilities.stream_usage == "final_chunk"

    openrouter = config.get("openrouter")
    assert openrouter.capabilities.model_list.prices is True
    assert openrouter.capabilities.model_list.context_length is True
    assert openrouter.capabilities.model_list.features is True
    assert openrouter.capabilities.stream_usage == "final_chunk"


def test_shipped_providers_yaml_holds_no_key():
    text = (Path(__file__).parent.parent / "app" / "providers.yaml").read_text()
    assert "api_key" not in text.lower()
    assert "sk-" not in text.lower()


def test_custom_provider_has_the_cautious_capability_set():
    provider = custom_provider("http://localhost:11434/v1/")

    assert provider.id == CUSTOM_PROVIDER_ID
    assert provider.base_url == "http://localhost:11434/v1/"
    assert provider.key_required is False
    assert provider.capabilities.model_list.prices is False
    assert provider.capabilities.model_list.context_length is False
    assert provider.capabilities.model_list.features is False
    assert provider.capabilities.stream_usage == "final_chunk"


def test_preset_named_custom_is_rejected():
    with pytest.raises(ProviderConfigError, match="custom"):
        load_providers_config(FIXTURES / "reserved_custom_id.yaml")


def test_app_refuses_to_start_on_an_invalid_file(settings_env):
    settings_env.setenv("PROVIDERS_CONFIG_PATH", str(FIXTURES / "missing_base_url.yaml"))
    get_providers_config.cache_clear()
    try:
        with pytest.raises(ProviderConfigError):
            with TestClient(app):
                pass
    finally:
        get_providers_config.cache_clear()


def test_key_check_url_is_optional_and_loaded():
    config = load_providers_config(FIXTURES / "key_check_url.yaml")
    assert config.get("gated").key_check_url == "https://gated.test/v1/auth/key"
    assert load_providers_config(FIXTURES / "valid.yaml").get("nebius").key_check_url is None


def test_key_check_url_must_be_a_web_address_naming_the_preset():
    with pytest.raises(ProviderConfigError, match="gated.*key_check_url"):
        load_providers_config(FIXTURES / "bad_key_check_url.yaml")


def test_shipped_providers_whose_model_list_is_public_check_keys_elsewhere():
    # NVIDIA and OpenRouter serve /models without authentication (probed
    # 2026-09-23), so listing models cannot tell a wrong key from a right one.
    config = load_providers_config()
    assert config.get("nebius").key_check_url is None
    assert config.get("nvidia").key_check_url
    assert config.get("openrouter").key_check_url
