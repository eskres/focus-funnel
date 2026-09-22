from pathlib import Path

import pytest

from app.provider_config import (
    CUSTOM_PROVIDER_ID,
    ProviderConfigError,
    custom_provider,
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
    assert "nebius" in config.providers


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
