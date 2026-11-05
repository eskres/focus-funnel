"""The search tool and the thought's date (thought-dates task 3.2).

The parse and format tests need no database; the chat test runs on Postgres.
"""

import json
import uuid
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.chat.config import get_chat_config
from app.chat.prompt import SEARCH_TOOL_SCHEMA
from app.chat.tools import (
    NO_DATED_MATCH,
    NO_MATCH,
    SearchArguments,
    ToolArgumentError,
    format_search_result,
    parse_search,
)
from app.config import get_settings
from app.models import Thought
from app.thoughts.search import Hit, SearchResult
from tests.chat_helpers import (
    chat,
    ready_user,
    text_chunks,
    tool_call_chunks,
    user_id_for,
)
from tests.sse_helpers import parse_events


def thought(title, *, starts_on=None, starts_at=None, ends_on=None, ends_at=None, tags=()):
    return Thought(
        id=uuid.uuid4(),
        title=title,
        summary=f"About {title.lower()}.",
        tags=list(tags),
        created_at=datetime(2026, 9, 28, 8, tzinfo=UTC),
        starts_on=starts_on,
        starts_at=starts_at,
        ends_on=ends_on,
        ends_at=ends_at,
        time_zone="Europe/Oslo" if starts_on else None,
    )


def hits(*thoughts) -> list[Hit]:
    return [Hit(thought=t, similarity=None, keyword_rank=None, chunk=None) for t in thoughts]


@pytest.fixture
def env(settings_env):
    return get_chat_config().search, get_settings()


# ------------------------------------------------------------------ parse_search


@pytest.mark.parametrize("arguments", [{}, {"query": ""}, {"query": "  "}, {"tags": ["work"]},
                                       {"since": "2026-09-01"}, {"query": None}])
def test_neither_a_query_nor_a_dated_field_is_refused_naming_query(arguments):
    with pytest.raises(ToolArgumentError) as refused:
        parse_search(arguments)
    assert str(refused.value).startswith("query ")


def test_dated_fields_alone_are_enough():
    parsed = parse_search({"dated_from": "2026-09-28", "dated_to": "2026-10-04"})
    assert parsed == SearchArguments(
        query=None, dated_from=date(2026, 9, 28), dated_to=date(2026, 10, 4)
    )
    assert parsed.by_date_only
    assert parsed.days_text == "2026-09-28 to 2026-10-04"
    only_to = parse_search({"dated_to": "2026-10-04", "query": " "})
    assert (only_to.query, only_to.dated_from, only_to.dated_to) == (None, None, date(2026, 10, 4))
    assert only_to.days_text == "up to 2026-10-04"
    assert parse_search({"dated_from": "2026-10-04"}).days_text == "from 2026-10-04"


def test_a_query_with_dated_fields():
    parsed = parse_search(
        {"query": " dinner ", "dated_from": "2026-10-01", "dated_to": "2026-10-31", "tags": ["x"]}
    )
    assert (parsed.query, parsed.tags, parsed.dated_from, parsed.dated_to) == (
        "dinner", ["x"], date(2026, 10, 1), date(2026, 10, 31)
    )
    assert not parsed.by_date_only


@pytest.mark.parametrize(
    "arguments, message",
    [
        ({"dated_from": "next week"}, "dated_from must be a date written YYYY-MM-DD"),
        ({"dated_from": "20261002"}, "dated_from must be a date written YYYY-MM-DD"),
        ({"dated_to": "2026-W40-5"}, "dated_to must be a date written YYYY-MM-DD"),
        ({"dated_to": "2026-02-30"}, "dated_to must be a date written YYYY-MM-DD"),
        ({"dated_to": 20261002}, "dated_to must be a date written YYYY-MM-DD"),
        ({"dated_from": "2026-10-04", "dated_to": "2026-09-28"},
         "dated_to must not be before dated_from"),
        ({"query": 3, "dated_from": "2026-10-04"}, "query must be a string"),
    ],
)
def test_malformed_dated_fields(arguments, message):
    with pytest.raises(ToolArgumentError) as refused:
        parse_search(arguments)
    assert str(refused.value) == message


def test_the_schema_makes_the_query_optional_and_has_the_thought_days():
    parameters = SEARCH_TOOL_SCHEMA["function"]["parameters"]
    assert "required" not in parameters or "query" not in parameters["required"]
    for name in ("dated_from", "dated_to"):
        assert parameters["properties"][name]["type"] == "string"
        assert "not the day it was filed" in parameters["properties"][name]["description"]
    assert "dated_from and dated_to" in SEARCH_TOOL_SCHEMA["function"]["description"]


# ------------------------------------------------------------ format_search_result


def test_dated_entries_show_their_date_and_undated_ones_do_not(env):
    config, settings = env
    dinner = thought("Dinner with Sam", starts_on=date(2026, 10, 2), starts_at=time(19), tags=["sam"])
    trip = thought("Trip to Oslo", starts_on=date(2026, 11, 3), ends_on=date(2026, 11, 6))
    call = thought("Plumber", starts_on=date(2026, 10, 9))
    meeting = thought(
        "Team meeting", starts_on=date(2026, 10, 5), starts_at=time(9, 30),
        ends_on=date(2026, 10, 5), ends_at=time(11),
    )
    milk = thought("Oat milk", tags=["groceries"])

    text = format_search_result(
        SearchResult(hits=hits(dinner, trip, call, meeting, milk), total=5), config, settings
    ).text

    assert text.startswith("5 of your thoughts match (best first):\n")
    headings = [line for line in text.splitlines() if line[:1].isdigit() and ". " in line]
    assert headings == [
        "1. Dinner with Sam · filed 2026-09-28 · on Fri 2026-10-02 19:00 · #sam",
        "2. Trip to Oslo · filed 2026-09-28 · on Tue 2026-11-03 to Fri 2026-11-06",
        "3. Plumber · filed 2026-09-28 · on Fri 2026-10-09",
        "4. Team meeting · filed 2026-09-28 · on Mon 2026-10-05 09:30 to 11:00",
        "5. Oat milk · filed 2026-09-28 · #groceries",
    ]
    assert " on " not in headings[-1]


def test_the_filed_day_is_the_users_local_day(env):
    config, settings = env
    # 03:00 UTC on 1 October: 20:00 on 30 September in Los Angeles.
    evening = thought("Evening milk")
    evening.created_at = datetime(2026, 10, 1, 3, tzinfo=UTC)
    # 23:30 UTC on 2 October: 08:30 on 3 October in Tokyo.
    morning = thought("Morning milk")
    morning.created_at = datetime(2026, 10, 2, 23, 30, tzinfo=UTC)
    result = SearchResult(hits=hits(evening, morning), total=2)

    def headings(zone):
        text = format_search_result(result, config, settings, zone=zone).text
        return [line for line in text.splitlines() if line[:1].isdigit() and ". " in line]

    assert headings(ZoneInfo("America/Los_Angeles")) == [
        "1. Evening milk · filed 2026-09-30",
        "2. Morning milk · filed 2026-10-02",
    ]
    assert headings(ZoneInfo("Asia/Tokyo")) == [
        "1. Evening milk · filed 2026-10-01",
        "2. Morning milk · filed 2026-10-03",
    ]
    # Without a zone the days are UTC, as before.
    assert headings(None) == [
        "1. Evening milk · filed 2026-10-01",
        "2. Morning milk · filed 2026-10-02",
    ]


def test_sources_never_get_the_date(env):
    config, settings = env
    dinner = thought("Dinner with Sam", starts_on=date(2026, 10, 2), starts_at=time(19))
    result = format_search_result(SearchResult(hits=hits(dinner), total=1), config, settings)
    assert result.sources == [
        {"id": str(dinner.id), "title": "Dinner with Sam",
         "created_at": "2026-09-28T08:00:00+00:00", "tags": []}
    ]


def test_a_date_only_search_has_its_own_header_footer_and_no_match(env):
    config, settings = env
    trip = thought("Trip to Oslo", starts_on=date(2026, 9, 30), ends_on=date(2026, 10, 3))
    dinner = thought("Dinner with Sam", starts_on=date(2026, 10, 2), starts_at=time(19))

    text = format_search_result(
        SearchResult(hits=hits(trip, dinner), total=5), config, settings, by_date=True
    ).text

    lines = text.splitlines()
    assert lines[0] == "2 of your thoughts are dated in those days (date order):"
    assert lines[1] == "1. Trip to Oslo · filed 2026-09-28 · on Wed 2026-09-30 to Sat 2026-10-03"
    assert lines[3] == "2. Dinner with Sam · filed 2026-09-28 · on Fri 2026-10-02 19:00"
    assert lines[-1] == "3 more are dated in those days. Narrow the days or add tags to see them."

    nothing = format_search_result(SearchResult(), config, settings, by_date=True).text
    assert nothing == NO_DATED_MATCH
    assert "No filed thoughts are dated in those days." in NO_DATED_MATCH
    assert "Say so plainly" in NO_DATED_MATCH
    # A search with a query keeps the usual note.
    assert format_search_result(SearchResult(), config, settings).text == NO_MATCH


# ------------------------------------------------------------- through the chat


@pytest.mark.postgres
def test_what_is_on_this_week_through_the_chat(client, alice, fake_llm, test_database_url):
    from tests.test_search_tool import store

    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    url = test_database_url

    def dated(title, start, end=None):
        when = {"start": start, "end": end, "time_zone": "America/Los_Angeles"}
        store(url, user_id, fake_llm, title, f"About {title.lower()}.", when=when,
              created=datetime(2026, 9, 20, 12, tzinfo=UTC))

    dated("Dentist", "2026-10-12T09:00")
    dated("Dinner with Sam", "2026-10-02T19:00")
    dated("Trip to Oslo", "2026-09-30", "2026-10-03")
    embed_calls = len(fake_llm.embed_requests)
    fake_llm.queue(
        tool_call_chunks(
            "search_thoughts", json.dumps({"dated_from": "2026-09-28", "dated_to": "2026-10-04"})
        ),
        text_chunks("A trip and a dinner."),
    )

    response = chat(client, alice, "what's on this week?", time_zone="America/Los_Angeles")

    assert response.status_code == 200, response.text
    content = fake_llm.chat_requests[-1]["messages"][-1]["content"]
    assert content == (
        "2 of your thoughts are dated in those days (date order):\n"
        # With thought-appending, each result carries its ref.
        "1. T1 · Trip to Oslo · filed 2026-09-20 · on Wed 2026-09-30 to Sat 2026-10-03\n"
        "   About trip to oslo.\n"
        "2. T2 · Dinner with Sam · filed 2026-09-20 · on Fri 2026-10-02 19:00\n"
        "   About dinner with sam."
    )
    assert len(fake_llm.embed_requests) == embed_calls
    [end] = [
        data for event, data in parse_events(response.text)
        if event == "tool" and data["phase"] == "end"
    ]
    assert end["summary"] == "Looked up your thoughts dated 2026-09-28 to 2026-10-04"
    assert [source["title"] for source in end["sources"]] == ["Trip to Oslo", "Dinner with Sam"]


@pytest.mark.postgres
def test_no_query_and_no_dates_goes_back_to_the_model(client, alice, fake_llm):
    ready_user(client, alice)
    fake_llm.queue(
        tool_call_chunks("search_thoughts", json.dumps({"since": "2026-09-01"})),
        text_chunks("Which thoughts?"),
    )
    response = chat(client, alice, "what did I file?")
    assert response.status_code == 200, response.text
    content = fake_llm.chat_requests[-1]["messages"][-1]["content"]
    assert content.startswith("Error: query must be a non-empty string, unless dated_from")
