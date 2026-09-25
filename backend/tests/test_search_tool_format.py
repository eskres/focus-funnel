"""The search tool's compact result (thought-storage task 6.2, no database)."""

import uuid
from datetime import UTC, date, datetime

import pytest

from app.chat.config import get_chat_config
from app.chat.tools import (
    NO_MATCH,
    ToolArgumentError,
    format_search_result,
    parse_search,
)
from app.config import get_settings
from app.errors import embedding_mismatch, model_unavailable
from app.models import Thought
from app.providers import key_missing, rate_limited
from app.provider_config import get_providers_config
from app.thoughts.search import Hit, SearchResult


def thought(title="Oat milk", summary="Buy oat milk on the way home.", tags=("groceries",)):
    return Thought(
        id=uuid.uuid4(),
        title=title,
        summary=summary,
        tags=list(tags),
        created_at=datetime(2026, 9, 20, 8, tzinfo=UTC),
    )


def hit(t=None, excerpt=None) -> Hit:
    return Hit(thought=t or thought(), similarity=0.8, keyword_rank=None, chunk=0, excerpt=excerpt)


@pytest.fixture
def env(settings_env):
    return get_chat_config().search, get_settings()


def test_the_documented_form_without_ids(env):
    config, settings = env
    t = thought()
    result = format_search_result(SearchResult(hits=[hit(t)], total=1), config, settings)
    assert result.text == (
        "1 of your thoughts match (best first):\n"
        "1. Oat milk · 2026-09-20 · #groceries\n"
        "   Buy oat milk on the way home."
    )
    assert str(t.id) not in result.text
    assert result.sources == [
        {"id": str(t.id), "title": "Oat milk", "created_at": "2026-09-20T08:00:00+00:00", "tags": ["groceries"]}
    ]


def test_no_tags_and_an_excerpt(env):
    config, settings = env
    t = thought(title="Lisbon trip", summary="A long weekend.", tags=())
    text = format_search_result(
        SearchResult(hits=[hit(t, excerpt="…the flat near Alfama…")], total=1), config, settings
    ).text
    assert text.splitlines()[1:] == [
        "1. Lisbon trip · 2026-09-20",
        "   A long weekend.",
        '   > "…the flat near Alfama…"',
    ]


def test_long_summaries_are_cut_at_a_word(env):
    config, settings = env
    long_summary = "word " * 200
    text = format_search_result(
        SearchResult(hits=[hit(thought(summary=long_summary))], total=1), config, settings
    ).text
    summary_line = text.splitlines()[2].strip()
    assert summary_line.endswith("…") and len(summary_line) <= config.summary_chars + 1
    assert summary_line.startswith("word word")


def test_the_budget_stops_early_and_says_more_matched(env):
    config, settings = env
    hits = [hit(thought(title=f"Thought {n}", summary="x " * 190)) for n in range(10)]
    result = format_search_result(SearchResult(hits=hits, total=14), config, settings)
    assert len(result.text) <= config.budget_chars + 200
    shown = len(result.sources)
    assert [source["title"] for source in result.sources] == [f"Thought {n}" for n in range(shown)]
    assert 1 <= shown < 10
    assert result.text.startswith(f"{shown} of your thoughts match")
    assert f"{14 - shown} more matched. Add tags or a start date" in result.text


def test_no_match(env):
    config, settings = env
    result = format_search_result(SearchResult(), config, settings)
    assert result.text == NO_MATCH
    assert result.sources == []
    assert "Say so plainly" in NO_MATCH


def test_words_only_names_the_provider_for_a_missing_key(env):
    config, settings = env
    provider = get_providers_config().get(settings.embedding_provider)
    result = SearchResult(hits=[hit()], total=1, words_only=key_missing(provider))
    last = format_search_result(result, config, settings).text.splitlines()[-1]
    assert last == (
        f"Searched by words only: add your {provider.label} API key in settings to also "
        "search by meaning. Tell the user."
    )


def test_words_only_names_the_provider_of_the_users_index(env):
    config, settings = env
    provider = get_providers_config().get("openrouter")
    result = SearchResult(words_only=key_missing(provider), embedding_provider="openrouter")
    assert "add your OpenRouter API key" in format_search_result(result, config, settings).text


def test_words_only_for_other_reasons(env):
    config, settings = env
    provider = get_providers_config().get(settings.embedding_provider)
    result = SearchResult(words_only=rate_limited(provider))
    text = format_search_result(result, config, settings).text
    assert text.startswith(NO_MATCH + "\nSearched by words only: ")
    assert "rate limiting" in text


@pytest.mark.parametrize(
    "error", [model_unavailable("vendor/embed-old"), embedding_mismatch("vendor/embed-old, 4 dimensions")]
)
def test_words_only_asks_for_a_rebuild_when_the_model_is_gone(env, error):
    config, settings = env
    text = format_search_result(SearchResult(words_only=error), config, settings).text
    assert text.endswith("the operator needs to rebuild it. Tell the user.")
    assert "model settings" not in text


def test_parse_search_arguments():
    parsed = parse_search({"query": "  plans ", "tags": ["work"], "since": "2026-09-01"})
    assert (parsed.query, parsed.tags, parsed.since) == ("plans", ["work"], date(2026, 9, 1))
    assert parse_search({"query": "x"}).tags is None


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"query": " "},
        {"query": "x", "tags": "work"},
        {"query": "x", "tags": [1]},
        {"query": "x", "since": "last week"},
        {"query": "x", "since": 20260901},
    ],
)
def test_malformed_arguments(arguments):
    with pytest.raises(ToolArgumentError):
        parse_search(arguments)

