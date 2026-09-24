from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.chat.config import ChatConfigError, get_chat_config, load_chat_config
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures" / "chat"
VALID = yaml.safe_load((FIXTURES / "valid.yaml").read_text())


def write(tmp_path, data) -> Path:
    path = tmp_path / "chat.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def without(key: str) -> dict:
    data = {**VALID}
    data.pop(key)
    return data


def test_a_valid_file_loads():
    config = load_chat_config(FIXTURES / "valid.yaml")
    assert config.temperature.default == 0.3
    assert (config.temperature.min, config.temperature.max) == (0.0, 2.0)
    assert config.reply_max_tokens == 8192
    assert config.tool_rounds == 3
    assert config.compact_suggest_share == 0.7
    assert config.compact_keep_recent == 6
    assert config.model_hint
    assert config.documented_efforts == ("none", "minimal", "low", "medium", "high")
    assert config.filing.known_tags == 40


def test_the_shipped_file_loads():
    load_chat_config(Path(__file__).parent.parent / "app" / "chat" / "chat.yaml")


@pytest.mark.parametrize(
    "key",
    [
        "temperature",
        "reply_max_tokens",
        "tool_rounds",
        "compact_suggest_share",
        "compact_keep_recent",
        "model_hint",
        "efforts",
        "search",
        "filing",
    ],
)
def test_a_missing_value_fails_naming_it(tmp_path, key):
    with pytest.raises(ChatConfigError, match=key):
        load_chat_config(write(tmp_path, without(key)))


@pytest.mark.parametrize(
    "change, name",
    [
        ({"temperature": {"default": 3.0, "min": 0.0, "max": 2.0}}, "temperature.default"),
        ({"temperature": {"default": 0.3, "min": 1.0, "max": 0.5}}, "temperature.min"),
        ({"temperature": {"default": "warm", "min": 0.0, "max": 2.0}}, "temperature.default"),
        ({"reply_max_tokens": 0}, "reply_max_tokens"),
        ({"tool_rounds": -1}, "tool_rounds"),
        ({"tool_rounds": 2.5}, "tool_rounds"),
        ({"compact_suggest_share": 1.5}, "compact_suggest_share"),
        ({"compact_keep_recent": 0}, "compact_keep_recent"),
        ({"model_hint": "  "}, "model_hint"),
        ({"efforts": {"documented": []}}, "efforts.documented"),
        (
            {"efforts": {"documented": ["low"], "unsupported": [{"match": "m", "efforts": ["max"]}]}},
            "efforts.unsupported",
        ),
        ({"filing": {"known_tags": 0}}, "filing.known_tags"),
        ({"filing": 40}, "filing"),
    ],
)
def test_an_out_of_range_value_fails_naming_it(tmp_path, change, name):
    with pytest.raises(ChatConfigError, match=name):
        load_chat_config(write(tmp_path, {**VALID, **change}))


def search_with(**change) -> dict:
    return {**VALID, "search": {**VALID["search"], **change}}


def test_search_settings_load():
    search = load_chat_config(FIXTURES / "valid.yaml").search
    assert (search.limit, search.candidates, search.rrf_k) == (8, 50, 60)
    assert (search.budget_chars, search.summary_chars, search.excerpt_chars) == (2400, 400, 240)
    assert search.backfill_batch == 16
    assert search.min_word_share == 0.6


def test_min_similarity_is_picked_per_model():
    search = load_chat_config(FIXTURES / "valid.yaml").search
    assert search.min_similarity_for("vendor/embed-large") == 0.6
    assert search.min_similarity_for("Vendor/Embed-small") == 0.6
    assert search.min_similarity_for("other/model") == 0.35


def test_query_instruction_is_picked_per_model():
    search = load_chat_config(FIXTURES / "valid.yaml").search
    assert search.query_instruction_for("Vendor/Embed-large") == "Instruct: find notes\nQuery:"
    assert search.query_instruction_for("other/model") == ""


@pytest.mark.parametrize(
    "change, name",
    [
        ({"limit": 0}, "search.limit"),
        ({"candidates": 4}, "search.candidates"),
        ({"budget_chars": -1}, "search.budget_chars"),
        ({"backfill_batch": 1.5}, "search.backfill_batch"),
        ({"min_similarity": {"default": 1.5}}, "search.min_similarity.default"),
        ({"min_similarity": 0.3}, "search.min_similarity"),
        ({"min_similarity": {"default": 0.3, "models": [{"match": "m", "value": -0.1}]}}, "models"),
        ({"min_similarity": {"default": 0.3, "models": [{"value": 0.5}]}}, "match"),
        ({"min_word_share": -1}, "search.min_word_share"),
        ({"min_word_share": 1.5}, "search.min_word_share"),
        ({"query_instruction": "Query:"}, "search.query_instruction"),
        ({"query_instruction": [{"text": "Query:"}]}, "match"),
        ({"query_instruction": [{"match": "m", "text": " "}]}, "text"),
    ],
)
def test_an_invalid_search_value_fails_naming_it(tmp_path, change, name):
    with pytest.raises(ChatConfigError, match=name):
        load_chat_config(write(tmp_path, search_with(**change)))


def test_a_missing_search_value_fails_naming_it(tmp_path):
    search = {**VALID["search"]}
    search.pop("excerpt_chars")
    with pytest.raises(ChatConfigError, match="search.excerpt_chars"):
        load_chat_config(write(tmp_path, {**VALID, "search": search}))


def test_the_file_chooses_no_model():
    for path in (FIXTURES / "valid.yaml", Path(__file__).parent.parent / "app" / "chat" / "chat.yaml"):
        raw = yaml.safe_load(path.read_text())
        assert not {"model", "default_model", "models"} & set(raw)


def test_app_refuses_to_start_on_an_invalid_file(settings_env, tmp_path):
    settings_env.setenv("CHAT_CONFIG_PATH", str(write(tmp_path, without("tool_rounds"))))
    get_chat_config.cache_clear()
    with pytest.raises(ChatConfigError):
        with TestClient(app):
            pass
