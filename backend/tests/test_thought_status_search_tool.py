"""The search tool's status and category filters (thought-status task 2.2).

The schema, parse, and format tests need no database. The list with no
query, its no-match text, and the chat summaries run on SQLite: a search
with no query is a plain select, and a query search for a user with no
thoughts returns before any Postgres-only SQL.
"""

import json
import uuid
from datetime import UTC, datetime

import pytest

from app.chat.config import get_chat_config
from app.chat.prompt import SEARCH_TOOL_SCHEMA
from app.chat.tools import (
    NO_DATED_MATCH,
    NO_FILTERED_MATCH,
    ToolArgumentError,
    format_search_result,
    parse_search,
    search_tool_result,
)
from app.config import get_settings
from app.models import Thought
from app.thoughts.search import Hit, SearchResult
from app.thoughts.store import set_status
from tests.chat_helpers import (
    FakeLLM,
    chat,
    ready_user,
    text_chunks,
    tool_call_chunks,
    user_id_for,
)
from tests.sse_helpers import parse_events
from tests.test_thought_refs import seed_thought
from tests.thought_helpers import run_as


def thought(title, *, status=None, changed=None, created=datetime(2026, 11, 1, 8, tzinfo=UTC)):
    return Thought(
        id=uuid.uuid4(),
        title=title,
        summary=f"About {title.lower()}.",
        tags=["home"],
        category="task",
        created_at=created,
        status=status,
        status_changed_at=changed,
    )


def hits(*thoughts) -> list[Hit]:
    return [Hit(thought=t, similarity=None, keyword_rank=None, chunk=None) for t in thoughts]


@pytest.fixture
def env(settings_env):
    return get_chat_config().search, get_settings()


# -------------------------------------------------------------------- schema


def test_the_schema_offers_only_the_open_status_and_a_category():
    properties = SEARCH_TOOL_SCHEMA["function"]["parameters"]["properties"]
    assert properties["status"]["enum"] == ["open"]
    assert properties["category"]["type"] == "string"
    assert "query" not in SEARCH_TOOL_SCHEMA["function"]["parameters"].get("required", [])


# ------------------------------------------------------------------ parse_search


@pytest.mark.parametrize("status", ["done", "archived"])
def test_parse_refuses_any_status_but_open_naming_status(status):
    with pytest.raises(ToolArgumentError) as refused:
        parse_search({"status": status, "category": "task"})
    assert str(refused.value).startswith("status ")


def test_parse_reads_open_and_cleans_the_category():
    parsed = parse_search({"status": "open", "category": " Task"})
    assert parsed.status == "open"
    assert parsed.category == "task"
    assert parsed.query is None
    assert parsed.listed
    assert not parsed.by_date_only
    assert parse_search({"category": " Task"}).category == "task"


@pytest.mark.parametrize(
    "arguments",
    [{}, {"query": ""}, {"query": "  "}, {"tags": ["home"]}, {"since": "2026-11-01"},
     {"category": ""}, {"category": "  "}],
)
def test_parse_refuses_no_query_and_no_filter_naming_query(arguments):
    with pytest.raises(ToolArgumentError) as refused:
        parse_search(arguments)
    assert str(refused.value).startswith("query ")


# ------------------------------------------------------------ format_search_result


def test_a_done_hit_is_marked_right_after_its_filed_date_and_an_open_hit_is_not(env):
    config, settings = env
    done = thought("Buy oat milk", status="done", changed=datetime(2026, 11, 5, 10, tzinfo=UTC))
    still_open = thought("Call the plumber", status="open")
    text = format_search_result(
        SearchResult(hits=hits(done, still_open), total=2), config, settings
    ).text
    assert "1. Buy oat milk · filed 2026-11-01 · done 2026-11-05 · #home\n" in text
    assert "2. Call the plumber · filed 2026-11-01 · #home\n" in text
    assert text.count("done") == 1
    assert "open" not in text.split("\n", 1)[1]


def test_a_transient_thought_with_no_status_read_gets_no_mark(env):
    config, settings = env
    text = format_search_result(
        SearchResult(hits=hits(thought("Call the plumber")), total=1), config, settings
    ).text
    assert "1. Call the plumber · filed 2026-11-01 · #home" in text


def test_the_done_day_is_the_users_local_day(env):
    from zoneinfo import ZoneInfo

    config, settings = env
    done = thought(
        "Buy oat milk",
        status="done",
        changed=datetime(2026, 11, 5, 23, 30, tzinfo=UTC),
        created=datetime(2026, 11, 1, 12, tzinfo=UTC),
    )
    text = format_search_result(
        SearchResult(hits=hits(done), total=1), config, settings, zone=ZoneInfo("Europe/Oslo")
    ).text
    assert "filed 2026-11-01 · done 2026-11-06" in text


# ------------------------------------------------- the list with no query (SQLite)


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    return FakeLLM().install()


@pytest.fixture
def alice_id(client, alice, fake):
    ready_user(client, alice)
    return user_id_for(client, alice)


def tool_text(url, user_id, fake, arguments) -> str:
    async def work(session, user, settings, http_client):
        result = await search_tool_result(
            session,
            user,
            parse_search(arguments),
            settings=settings,
            config=get_chat_config().search,
            http_client=http_client,
        )
        return result.text

    return run_as(url, user_id, fake, work)


def mark_done(url, user_id, fake, thought_id):
    async def work(session, user, settings, http_client):
        await set_status(session, user, uuid.UUID(thought_id), "done")
        await session.commit()

    run_as(url, user_id, fake, work)


def test_a_list_with_no_query_and_no_date_filter_says_newest_first(
    test_database_url, fake, alice_id
):
    url = test_database_url
    seed_thought(url, alice_id, "Call the plumber", category="task", days_ago=2)
    seed_thought(url, alice_id, "Fix the gate", category="task", days_ago=1)
    milk = seed_thought(url, alice_id, "Buy oat milk", category="task")
    mark_done(url, alice_id, fake, milk)
    seed_thought(url, alice_id, "Podcast about maps", category="idea")

    text = tool_text(url, alice_id, fake, {"status": "open", "category": "task"})

    lines = text.splitlines()
    assert lines[0] == "2 of your thoughts match (newest first):"
    assert lines[1].startswith("1. Fix the gate · filed ")
    assert lines[3].startswith("2. Call the plumber · filed ")
    assert "Buy oat milk" not in text
    assert "Podcast about maps" not in text
    assert fake.embed_requests == []

    # With no status, the done task is listed too, marked done.
    everything = tool_text(url, alice_id, fake, {"category": "task"})
    assert everything.startswith("3 of your thoughts match (newest first):")
    [milk_line] = [line for line in everything.splitlines() if ". Buy oat milk · " in line]
    assert " · done " in milk_line


def test_no_matching_thoughts_says_no_filed_thoughts_match_those_filters(
    test_database_url, fake, alice_id
):
    url = test_database_url
    # Thoughts the filters leave out, so the list itself runs and finds none.
    milk = seed_thought(url, alice_id, "Buy oat milk", category="task")
    mark_done(url, alice_id, fake, milk)
    seed_thought(url, alice_id, "Podcast about maps", category="idea")

    text = tool_text(url, alice_id, fake, {"status": "open", "category": "task"})

    assert text == NO_FILTERED_MATCH
    assert "no filed thoughts match those filters" in text.lower()
    assert NO_DATED_MATCH not in text
    assert "dated" not in text


# ------------------------------------------------------------- the chat summary


def summaries(response) -> list[str]:
    return [
        data["summary"]
        for event, data in parse_events(response.text)
        if event == "tool" and data["phase"] == "end"
    ]


@pytest.mark.parametrize(
    ("arguments", "summary"),
    [
        ({"status": "open", "category": "task"}, "Listed your open thoughts in task"),
        ({"dated_from": "2026-11-09", "dated_to": "2026-11-15"}, "Listed your thoughts"),
        ({"query": "plumber"}, "Searched your thoughts for “plumber”"),
        ({"status": "open"}, "Listed your open thoughts"),
        ({"category": " Task"}, "Listed your thoughts in task"),
    ],
)
def test_the_tool_end_summary_names_the_filters_or_the_query(
    client, alice, fake_llm, arguments, summary
):
    ready_user(client, alice)
    fake_llm.queue(
        tool_call_chunks("search_thoughts", json.dumps(arguments)),
        text_chunks("Here is what I found."),
    )

    response = chat(client, alice, "what is open?")

    assert response.status_code == 200, response.text
    [end] = summaries(response)
    assert end == summary
    for wrong in ("“”", "None", "done"):
        assert wrong not in end
