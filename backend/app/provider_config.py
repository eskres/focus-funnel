"""Provider preset configuration: `providers.yaml`, loaded once at startup.

Validation is field by field so a bad preset fails at startup with a message
naming which preset and what's wrong, not a stack trace on first use. Set
PROVIDERS_CONFIG_PATH to point tests, or an operator's override, at a
different file.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml

StreamUsage = Literal["final_chunk", "incremental", "none"]
_STREAM_USAGE_VALUES = {"final_chunk", "incremental", "none"}


class ProviderConfigError(ValueError):
    """The provider configuration file is missing, malformed, or invalid."""


@dataclass(frozen=True)
class ModelListCapabilities:
    prices: bool
    context_length: bool
    features: bool


@dataclass(frozen=True)
class ProviderCapabilities:
    model_list: ModelListCapabilities
    stream_usage: StreamUsage


@dataclass(frozen=True)
class ProviderPreset:
    id: str
    label: str
    base_url: str
    key_url: str
    notice: str
    key_required: bool
    capabilities: ProviderCapabilities
    # An authenticated URL that answers 401 or 403 to a wrong key. Needed when
    # the provider serves its model list without a key, so listing models
    # cannot tell a wrong key from a right one. None means "list models".
    key_check_url: str | None = None
    # Where the user sees their balance and spend, when the provider has such
    # a page. The app cannot read the balance through an API key.
    console_url: str | None = None


@dataclass(frozen=True)
class ProvidersConfig:
    providers: dict[str, ProviderPreset]

    def get(self, provider_id: str) -> ProviderPreset | None:
        return self.providers.get(provider_id)


CUSTOM_PROVIDER_ID = "custom"

# The custom provider isn't a preset: its base URL comes from the user, so
# nothing about it has been probed. Its capabilities are the most cautious
# set - nothing reported, usage read from a final chunk when present.
CUSTOM_PROVIDER_CAPABILITIES = ProviderCapabilities(
    model_list=ModelListCapabilities(prices=False, context_length=False, features=False),
    stream_usage="final_chunk",
)


def custom_provider(base_url: str) -> ProviderPreset:
    """Build the custom provider's descriptor from a user-supplied base URL.

    key_required is False: a local model server such as Ollama often needs no
    key, and the user's own key (if their endpoint needs one) is still
    checked and used normally when they supply one.
    """
    return ProviderPreset(
        id=CUSTOM_PROVIDER_ID,
        label="Custom provider",
        base_url=base_url,
        key_url="",
        notice=(
            "This is a custom endpoint you supplied. Focus Funnel has no information "
            "about how it handles your prompts."
        ),
        key_required=False,
        capabilities=CUSTOM_PROVIDER_CAPABILITIES,
    )


class _DuplicateKeyCheckingLoader(yaml.SafeLoader):
    """A SafeLoader that refuses a mapping with the same key twice.

    PyYAML's default loader silently keeps the last value for a repeated
    mapping key, which would hide a duplicate provider id instead of
    refusing to start.
    """


def _construct_mapping_no_duplicates(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict:
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in mapping:
            raise ProviderConfigError(f"Duplicate provider id '{key}' in configuration")
        mapping[key] = loader.construct_object(value_node, deep=True)
    return mapping


_DuplicateKeyCheckingLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping_no_duplicates
)


def get_config_path() -> Path:
    env_path = os.environ.get("PROVIDERS_CONFIG_PATH")
    if env_path and env_path.strip():
        return Path(env_path.strip())
    return Path(__file__).parent / "providers.yaml"


def _require_str(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderConfigError(f"{where} must be a non-empty string")
    return value


def _parse_capabilities(preset_id: str, raw: object) -> ProviderCapabilities:
    if not isinstance(raw, dict):
        raise ProviderConfigError(f"Provider '{preset_id}' is missing 'capabilities'")

    model_list_raw = raw.get("model_list")
    if not isinstance(model_list_raw, dict):
        raise ProviderConfigError(f"Provider '{preset_id}' is missing capability 'model_list'")
    for field in ("prices", "context_length", "features"):
        value = model_list_raw.get(field)
        if not isinstance(value, bool):
            raise ProviderConfigError(
                f"Provider '{preset_id}' is missing capability 'model_list.{field}'"
            )

    if "stream_usage" not in raw:
        raise ProviderConfigError(f"Provider '{preset_id}' is missing capability 'stream_usage'")
    stream_usage = raw["stream_usage"]
    if stream_usage not in _STREAM_USAGE_VALUES:
        raise ProviderConfigError(
            f"Provider '{preset_id}' has an unknown 'stream_usage' value: {stream_usage!r}"
        )

    return ProviderCapabilities(
        model_list=ModelListCapabilities(
            prices=model_list_raw["prices"],
            context_length=model_list_raw["context_length"],
            features=model_list_raw["features"],
        ),
        stream_usage=stream_usage,
    )


def _parse_preset(preset_id: str, raw: object) -> ProviderPreset:
    if not isinstance(raw, dict):
        raise ProviderConfigError(f"Provider '{preset_id}' configuration must be a mapping")

    base_url = raw.get("base_url")
    if not isinstance(base_url, str) or not base_url.strip():
        raise ProviderConfigError(f"Provider '{preset_id}' is missing 'base_url'")

    label = _require_str(raw.get("label"), f"Provider '{preset_id}' 'label'")
    key_url = _require_str(raw.get("key_url"), f"Provider '{preset_id}' 'key_url'")
    notice = _require_str(raw.get("notice"), f"Provider '{preset_id}' 'notice'")

    key_required = raw.get("key_required")
    if not isinstance(key_required, bool):
        raise ProviderConfigError(f"Provider '{preset_id}' is missing 'key_required'")

    capabilities = _parse_capabilities(preset_id, raw.get("capabilities"))

    key_check_url = raw.get("key_check_url")
    if key_check_url is not None and (
        not isinstance(key_check_url, str) or urlparse(key_check_url).scheme not in ("http", "https")
    ):
        raise ProviderConfigError(
            f"Provider '{preset_id}' 'key_check_url' must be an http or https URL"
        )

    console_url = raw.get("console_url")
    if console_url is not None and (
        not isinstance(console_url, str) or urlparse(console_url).scheme not in ("http", "https")
    ):
        raise ProviderConfigError(
            f"Provider '{preset_id}' 'console_url' must be an http or https URL"
        )

    return ProviderPreset(
        id=preset_id,
        label=label,
        base_url=base_url,
        key_url=key_url,
        notice=notice,
        key_required=key_required,
        capabilities=capabilities,
        key_check_url=key_check_url,
        console_url=console_url,
    )


def load_providers_config(path: str | Path | None = None) -> ProvidersConfig:
    target_path = Path(path) if path is not None else get_config_path()

    if not target_path.exists():
        raise ProviderConfigError(f"Provider configuration file not found: {target_path}")

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            raw = yaml.load(f, Loader=_DuplicateKeyCheckingLoader)
    except ProviderConfigError:
        raise
    except yaml.YAMLError as exc:
        raise ProviderConfigError(f"Failed to parse provider configuration YAML: {exc}") from exc

    if not isinstance(raw, dict) or "providers" not in raw:
        raise ProviderConfigError("Provider configuration is missing 'providers' mapping")

    providers_raw = raw["providers"]
    if not isinstance(providers_raw, dict):
        raise ProviderConfigError(
            "'providers' must be a mapping of provider id to configuration"
        )

    if CUSTOM_PROVIDER_ID in providers_raw:
        raise ProviderConfigError(
            f"Provider id '{CUSTOM_PROVIDER_ID}' is reserved for the custom provider"
        )

    providers = {
        preset_id: _parse_preset(preset_id, preset_raw)
        for preset_id, preset_raw in providers_raw.items()
    }
    if not providers:
        raise ProviderConfigError("Provider configuration has no providers")

    return ProvidersConfig(providers=providers)


@lru_cache
def get_providers_config() -> ProvidersConfig:
    return load_providers_config()
