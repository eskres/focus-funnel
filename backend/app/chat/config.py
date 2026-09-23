"""Chat configuration: `chat.yaml`, loaded once at startup.

Each value is checked by name so a bad file fails at startup with a message
naming what is wrong. Set CHAT_CONFIG_PATH to point tests at a fixture.
"""

import os
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import lru_cache
from pathlib import Path

import yaml


class ChatConfigError(ValueError):
    """The chat configuration file is missing, malformed, or invalid."""


@dataclass(frozen=True)
class TemperatureConfig:
    default: float
    min: float
    max: float


@dataclass(frozen=True)
class EffortRule:
    match: str
    efforts: tuple[str, ...]


@dataclass(frozen=True)
class ChatConfig:
    temperature: TemperatureConfig
    reply_max_tokens: int
    tool_rounds: int
    compact_suggest_share: float
    compact_keep_recent: int
    model_hint: str
    documented_efforts: tuple[str, ...]
    unsupported_efforts: tuple[EffortRule, ...]

    def efforts_for(self, model: str) -> list[str]:
        """The efforts offered for a model: every documented one it is not known to refuse."""
        refused: set[str] = set()
        for rule in self.unsupported_efforts:
            if fnmatchcase(model.lower(), rule.match.lower()):
                refused.update(rule.efforts)
        return [effort for effort in self.documented_efforts if effort not in refused]


def get_config_path() -> Path:
    env_path = os.environ.get("CHAT_CONFIG_PATH")
    if env_path and env_path.strip():
        return Path(env_path.strip())
    return Path(__file__).parent / "chat.yaml"


def _number(raw: dict, name: str, where: str = "") -> float:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ChatConfigError(f"'{where}{name}' must be a number")
    return float(value)


def _positive_int(raw: dict, name: str) -> int:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ChatConfigError(f"'{name}' must be a whole number of at least 1")
    return value


def _parse_temperature(raw: object) -> TemperatureConfig:
    if not isinstance(raw, dict):
        raise ChatConfigError("'temperature' must be a mapping with default, min, and max")
    low = _number(raw, "min", "temperature.")
    high = _number(raw, "max", "temperature.")
    default = _number(raw, "default", "temperature.")
    if low > high:
        raise ChatConfigError("'temperature.min' must not be above 'temperature.max'")
    if not low <= default <= high:
        raise ChatConfigError("'temperature.default' must be within min and max")
    return TemperatureConfig(default=default, min=low, max=high)


def _parse_efforts(raw: object) -> tuple[tuple[str, ...], tuple[EffortRule, ...]]:
    if not isinstance(raw, dict):
        raise ChatConfigError("'efforts' must be a mapping with documented and unsupported")
    documented = raw.get("documented")
    if (
        not isinstance(documented, list)
        or not documented
        or not all(isinstance(item, str) and item for item in documented)
    ):
        raise ChatConfigError("'efforts.documented' must be a list of effort names")
    rules_raw = raw.get("unsupported", [])
    if not isinstance(rules_raw, list):
        raise ChatConfigError("'efforts.unsupported' must be a list")
    rules = []
    for index, rule in enumerate(rules_raw):
        where = f"'efforts.unsupported[{index}]'"
        if not isinstance(rule, dict) or not isinstance(rule.get("match"), str) or not rule["match"]:
            raise ChatConfigError(f"{where} needs a 'match' model id")
        efforts = rule.get("efforts")
        if not isinstance(efforts, list) or not efforts:
            raise ChatConfigError(f"{where} needs a list of 'efforts'")
        unknown = [effort for effort in efforts if effort not in documented]
        if unknown:
            raise ChatConfigError(f"{where} names an effort that is not documented: {unknown[0]}")
        rules.append(EffortRule(match=rule["match"], efforts=tuple(efforts)))
    return tuple(documented), tuple(rules)


def load_chat_config(path: str | Path | None = None) -> ChatConfig:
    target_path = Path(path) if path is not None else get_config_path()
    if not target_path.exists():
        raise ChatConfigError(f"Chat configuration file not found: {target_path}")
    try:
        with open(target_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        raise ChatConfigError(f"Failed to parse chat configuration YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ChatConfigError("Chat configuration must be a mapping")

    share = _number(raw, "compact_suggest_share")
    if not 0 < share < 1:
        raise ChatConfigError("'compact_suggest_share' must be between 0 and 1")
    hint = raw.get("model_hint")
    if not isinstance(hint, str) or not hint.strip():
        raise ChatConfigError("'model_hint' must be a non-empty string")
    documented, rules = _parse_efforts(raw.get("efforts"))

    return ChatConfig(
        temperature=_parse_temperature(raw.get("temperature")),
        reply_max_tokens=_positive_int(raw, "reply_max_tokens"),
        tool_rounds=_positive_int(raw, "tool_rounds"),
        compact_suggest_share=share,
        compact_keep_recent=_positive_int(raw, "compact_keep_recent"),
        model_hint=hint.strip(),
        documented_efforts=documented,
        unsupported_efforts=rules,
    )


@lru_cache
def get_chat_config() -> ChatConfig:
    return load_chat_config()
