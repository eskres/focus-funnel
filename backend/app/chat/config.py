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
class SimilarityRule:
    match: str
    value: float


@dataclass(frozen=True)
class InstructionRule:
    match: str
    text: str


@dataclass(frozen=True)
class SearchConfig:
    """Thought search tuning. See openspec thought-storage design decision 8."""

    limit: int
    candidates: int
    rrf_k: int
    min_similarity: float
    similarity_rules: tuple[SimilarityRule, ...]
    min_word_share: float
    backfill_batch: int
    budget_chars: int
    summary_chars: int
    excerpt_chars: int
    query_instructions: tuple[InstructionRule, ...] = ()

    def min_similarity_for(self, model: str) -> float:
        """The cut-off for a model: the first rule matching its id, else the default."""
        for rule in self.similarity_rules:
            if fnmatchcase(model.lower(), rule.match.lower()):
                return rule.value
        return self.min_similarity

    def query_instruction_for(self, model: str) -> str:
        """The text put before a query for a model: the first rule matching its id, else none."""
        for rule in self.query_instructions:
            if fnmatchcase(model.lower(), rule.match.lower()):
                return rule.text
        return ""


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
    search: SearchConfig

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


def _positive_int(raw: dict, name: str, where: str = "") -> int:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ChatConfigError(f"'{where}{name}' must be a whole number of at least 1")
    return value


def _similarity(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ChatConfigError(f"'{where}' must be a number from 0 to 1")
    return float(value)


def _parse_search(raw: object) -> SearchConfig:
    if not isinstance(raw, dict):
        raise ChatConfigError("'search' must be a mapping of search settings")
    ints = {
        name: _positive_int(raw, name, "search.")
        for name in (
            "limit",
            "candidates",
            "rrf_k",
            "backfill_batch",
            "budget_chars",
            "summary_chars",
            "excerpt_chars",
        )
    }
    if ints["candidates"] < ints["limit"]:
        raise ChatConfigError("'search.candidates' must not be below 'search.limit'")
    similarity = raw.get("min_similarity")
    if not isinstance(similarity, dict):
        raise ChatConfigError("'search.min_similarity' must be a mapping with default and models")
    default = _similarity(similarity.get("default"), "search.min_similarity.default")
    rules_raw = similarity.get("models", [])
    if not isinstance(rules_raw, list):
        raise ChatConfigError("'search.min_similarity.models' must be a list")
    rules = []
    for index, rule in enumerate(rules_raw):
        where = f"search.min_similarity.models[{index}]"
        if not isinstance(rule, dict) or not isinstance(rule.get("match"), str) or not rule["match"]:
            raise ChatConfigError(f"'{where}' needs a 'match' model id")
        rules.append(SimilarityRule(match=rule["match"], value=_similarity(rule.get("value"), f"{where}.value")))
    word_share = _similarity(raw.get("min_word_share"), "search.min_word_share")
    instructions_raw = raw.get("query_instruction", [])
    if not isinstance(instructions_raw, list):
        raise ChatConfigError("'search.query_instruction' must be a list")
    instructions = []
    for index, rule in enumerate(instructions_raw):
        where = f"search.query_instruction[{index}]"
        if not isinstance(rule, dict) or not isinstance(rule.get("match"), str) or not rule["match"]:
            raise ChatConfigError(f"'{where}' needs a 'match' model id")
        if not isinstance(rule.get("text"), str) or not rule["text"].strip():
            raise ChatConfigError(f"'{where}.text' must be a non-empty string")
        instructions.append(InstructionRule(match=rule["match"], text=rule["text"]))
    return SearchConfig(
        min_similarity=default,
        similarity_rules=tuple(rules),
        min_word_share=word_share,
        query_instructions=tuple(instructions),
        **ints,
    )


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
        search=_parse_search(raw.get("search")),
    )


@lru_cache
def get_chat_config() -> ChatConfig:
    return load_chat_config()
