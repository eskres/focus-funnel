"""The model and the date (thought-dates tasks 2.1 and 2.3): the user's local
date in the prompt, and dates on proposal parts. SQLite: no search runs."""

import json
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.chat.prompt import TOOLS, held_proposal_note, system_prompt
from app.chat.tools import parse_proposal
from app.models import Proposal
from app.thoughts import dates
from app.thoughts.categories import FIXED_CATEGORIES
from tests.chat_helpers import (
    chat,
    completion,
    part,
    ready_user,
    run_db,
    seed_conversation,
    seed_proposal,
    text_chunks,
    tool_call,
    tool_call_chunks,
    usage_chunk,
)
from tests.sse_helpers import parse_events

CATEGORIES = list(FIXED_CATEGORIES)
DINNER = {"title": "Dinner with Sam", "summary": "Dinner with Sam.", "tags": ["sam"], "category": "task"}


def at(*args) -> datetime:
    """A moment in UTC."""
    return datetime(*args, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch):
    def set_now(moment: datetime) -> None:
        monkeypatch.setattr(dates, "utc_now", lambda: moment)

    return set_now


def prompt_of(fake_llm, index: int = 0) -> str:
    return fake_llm.chat_requests[index]["messages"][0]["content"]


def proposal_event(response) -> dict:
    [event] = [data for name, data in parse_events(response.text) if name == "proposal"]
    return event


def stored_parts(url, proposal_id: str) -> list[dict]:
    async def work(session):
        row = await session.get(Proposal, uuid.UUID(proposal_id))
        return row.parts

    return run_db(url, work)


def propose(fake_llm, *parts: dict) -> None:
    fake_llm.queue(
        tool_call_chunks("propose_thought", json.dumps({"thoughts": list(parts)})) + [usage_chunk()],
        text_chunks("Ready to check.") + [usage_chunk()],
    )


# --- 2.1: the model knows the user's local date ---


def test_the_prompt_says_weeks_start_on_monday():
    assert system_prompt().endswith(". Weeks start on Monday.")


@pytest.mark.parametrize(
    "moment, zone, today",
    [
        # Late evening west of UTC: 22:00 on Wednesday 30 September in Los
        # Angeles is Thursday 1 October in UTC.
        (at(2026, 10, 1, 5, 0), "America/Los_Angeles", "Wednesday 2026-09-30"),
        # Early morning east of UTC: 06:00 on Thursday 1 October in Tokyo is
        # Wednesday 30 September in UTC.
        (at(2026, 9, 30, 21, 0), "Asia/Tokyo", "Thursday 2026-10-01"),
    ],
)
def test_the_model_is_told_the_local_date(client, alice, fake_llm, clock, moment, zone, today):
    clock(moment)
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi.") + [usage_chunk()])

    response = chat(client, alice, "hello", time_zone=zone)

    assert response.status_code == 200, response.text
    assert prompt_of(fake_llm).endswith(f"\n\nToday is {today}. Weeks start on Monday.")


@pytest.mark.parametrize("extra", [{}, {"time_zone": None}, {"time_zone": "Mars/Base"}, {"time_zone": ""}])
def test_no_or_an_unknown_zone_runs_the_turn_with_the_utc_date(client, alice, fake_llm, clock, extra):
    clock(at(2026, 10, 1, 5, 0))
    ready_user(client, alice)
    fake_llm.queue(text_chunks("Hi.") + [usage_chunk()])

    response = chat(client, alice, "hello", **extra)

    assert response.status_code == 200, response.text
    assert [name for name, _ in parse_events(response.text)][-1] == "done"
    assert prompt_of(fake_llm).endswith("\n\nToday is Thursday 2026-10-01. Weeks start on Monday.")


def offer(client, headers, conversation_id, body=None):
    return client.post(
        f"/api/conversations/{conversation_id}/proposal", headers=headers, json=body
    )


@pytest.mark.parametrize(
    "body, today",
    [
        ({"time_zone": "America/Los_Angeles"}, "Wednesday 2026-09-30"),
        ({"time_zone": "Mars/Base"}, "Thursday 2026-10-01"),
        ({}, "Thursday 2026-10-01"),
        # An older frontend posts no body at all.
        (None, "Thursday 2026-10-01"),
    ],
)
def test_the_offer_before_archive_and_compact_uses_the_local_date(
    client, alice, fake_llm, clock, test_database_url, body, today
):
    clock(at(2026, 10, 1, 5, 0))
    ready_user(client, alice)
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=("dinner with Sam Friday at 7", "Nice.")
    )
    fake_llm.queue(completion(None, tool_calls=[tool_call("propose_thought", {"thoughts": [DINNER]})]))

    response = offer(client, alice, conversation_id, body)

    assert response.status_code == 200, response.text
    assert prompt_of(fake_llm).endswith(f"\n\nToday is {today}. Weeks start on Monday.")


# --- 2.3: dates on proposal parts ---


def test_the_tool_offers_a_date_and_two_choices_with_no_zone():
    properties = TOOLS[1]["function"]["parameters"]["properties"]["thoughts"]["items"]["properties"]
    assert set(properties["when"]["properties"]) == {"start", "end"}
    assert properties["when_choices"]["items"]["required"] == ["start"]
    assert properties["when_choices"]["maxItems"] == 2
    description = properties["when"]["description"]
    assert "only when the thought is about a set date or time" in description
    assert "soonest such day after today" in description
    assert "today's weekday" in properties["when_choices"]["description"]
    assert "'Next' with a weekday" in properties["when_choices"]["description"]


def test_a_valid_date_reaches_the_event_the_stored_part_and_the_conversation_with_the_turns_zone(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    propose(fake_llm, {**DINNER, "when": {"start": "2026-10-02T19:00"}})

    response = chat(client, alice, "/push dinner with Sam Friday at 7", time_zone="Europe/Oslo")

    when = {"start": "2026-10-02T19:00", "end": None, "time_zone": "Europe/Oslo"}
    event = proposal_event(response)
    assert event["parts"][0]["when"] == when
    assert event["parts"][0]["when_choices"] is None
    assert stored_parts(test_database_url, event["id"])[0]["when"] == when
    conversation_id = client.get("/api/conversations", headers=alice).json()["conversations"][0]["id"]
    body = client.get(f"/api/conversations/{conversation_id}", headers=alice).json()
    assert body["proposals"][0]["parts"][0]["when"] == when


def test_the_model_cannot_name_the_zone(client, alice, fake_llm):
    ready_user(client, alice)
    propose(
        fake_llm,
        {**DINNER, "when": {"start": "2026-11-03", "end": "2026-11-06", "time_zone": "Asia/Tokyo"}},
    )

    response = chat(client, alice, "/push trip", time_zone="America/Los_Angeles")

    assert proposal_event(response)["parts"][0]["when"] == {
        "start": "2026-11-03", "end": "2026-11-06", "time_zone": "America/Los_Angeles",
    }


def test_a_date_that_is_not_valid_is_dropped_and_the_part_kept(client, alice, fake_llm):
    ready_user(client, alice)
    propose(fake_llm, {**DINNER, "when": {"start": "2026-02-30"}})

    response = chat(client, alice, "/push dinner", time_zone="Europe/Oslo")

    [stored] = proposal_event(response)["parts"]
    assert (stored["title"], stored["summary"], stored["tags"], stored["category"]) == (
        "Dinner with Sam", "Dinner with Sam.", ["sam"], "task",
    )
    assert stored["when"] is None and stored["when_choices"] is None


def test_two_choices_are_kept_and_win_over_a_date(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    propose(
        fake_llm,
        {
            **DINNER,
            "when": {"start": "2026-10-02T19:00"},
            "when_choices": [{"start": "2026-10-02T19:00"}, {"start": "2026-10-09T19:00"}],
        },
    )

    response = chat(client, alice, "/push dinner with Sam Friday at 7", time_zone="Europe/Oslo")

    event = proposal_event(response)
    choices = [
        {"start": "2026-10-02T19:00", "end": None, "time_zone": "Europe/Oslo"},
        {"start": "2026-10-09T19:00", "end": None, "time_zone": "Europe/Oslo"},
    ]
    assert event["parts"][0]["when_choices"] == choices
    assert event["parts"][0]["when"] is None
    assert stored_parts(test_database_url, event["id"])[0]["when_choices"] == choices


def test_one_valid_choice_becomes_the_date(client, alice, fake_llm):
    ready_user(client, alice)
    propose(fake_llm, {**DINNER, "when_choices": [{"start": "2026-10-02"}, {"start": "2026-02-30"}]})

    response = chat(client, alice, "/push call the plumber", time_zone="Europe/Oslo")

    [stored] = proposal_event(response)["parts"]
    assert stored["when"] == {"start": "2026-10-02", "end": None, "time_zone": "Europe/Oslo"}
    assert stored["when_choices"] is None


@pytest.mark.parametrize(
    "fields, when, choices",
    [
        # No date at all.
        ({}, None, None),
        ({"when": None}, None, None),
        # Not an object, or a time on one side only.
        ({"when": "Friday"}, None, None),
        ({"when": {"start": "2026-10-02T19:00", "end": "2026-10-02"}}, None, None),
        # Every choice fails: no date, even with a valid single date given.
        ({"when": {"start": "2026-10-02"}, "when_choices": [{"start": "x"}, {"start": "y"}]}, None, None),
        # An empty list of choices is no choices.
        ({"when": {"start": "2026-10-02"}, "when_choices": []}, "2026-10-02", None),
        # More than two: the first two are kept.
        (
            {"when_choices": [{"start": "2026-10-02"}, {"start": "2026-10-09"}, {"start": "2026-10-16"}]},
            None,
            ["2026-10-02", "2026-10-09"],
        ),
        # The same date twice is one date.
        ({"when_choices": [{"start": "2026-10-02"}, {"start": "2026-10-02"}]}, "2026-10-02", None),
    ],
)
def test_the_choice_rules(fields, when, choices):
    [parsed] = parse_proposal({"thoughts": [{**DINNER, **fields}]}, CATEGORIES, ZoneInfo("Europe/Oslo"))
    assert (parsed.when or {}).get("start") == when
    starts = [c["start"] for c in parsed.when_choices] if parsed.when_choices else None
    assert starts == choices
    assert parsed.title == "Dinner with Sam"


def test_with_no_zone_a_date_is_stamped_utc():
    [parsed] = parse_proposal({"thoughts": [{**DINNER, "when": {"start": "2026-10-02"}}]}, CATEGORIES)
    assert parsed.when == {"start": "2026-10-02", "end": None, "time_zone": "UTC"}


def test_the_offer_stamps_its_dates_with_the_zone(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(
        test_database_url, client, alice, messages=("dinner with Sam Friday at 7", "Nice.")
    )
    dated = {**DINNER, "when": {"start": "2026-10-02T19:00"}}
    fake_llm.queue(completion(None, tool_calls=[tool_call("propose_thought", {"thoughts": [dated]})]))

    response = offer(client, alice, conversation_id, {"time_zone": "Asia/Tokyo"})

    assert response.json()["proposal"]["parts"][0]["when"] == {
        "start": "2026-10-02T19:00", "end": None, "time_zone": "Asia/Tokyo",
    }


# --- the held-proposal note ---

ONE_DATE = {**part(title="Dinner with Sam"), "when": {"start": "2026-10-02T19:00", "end": None, "time_zone": "UTC"}}
DAYS = {**part(title="Trip to Oslo"), "when": {"start": "2026-11-03", "end": "2026-11-06", "time_zone": "UTC"}}
CHOICES = {
    **part(title="Call the plumber"),
    "when": None,
    "when_choices": [
        {"start": "2026-10-02", "end": None, "time_zone": "UTC"},
        {"start": "2026-10-09", "end": None, "time_zone": "UTC"},
    ],
}


def test_the_held_note_has_a_date_line_for_each_part():
    note = held_proposal_note([ONE_DATE, DAYS, CHOICES, part(title="Oat milk")])
    assert "Title: Dinner with Sam\nSummary: Buy oat milk tomorrow.\nTags: shopping\nCategory: task\nDate: 2026-10-02T19:00\n" in note
    assert "Category: task\nDate: 2026-11-03 to 2026-11-06\n" in note
    assert "Date: 2026-10-02 or 2026-10-09 (not picked yet)" in note
    assert "Title: Oat milk\nSummary: Buy oat milk tomorrow.\nTags: shopping\nCategory: task\nDate: none\n" in note


def test_a_held_dated_proposal_reaches_the_model_with_its_date(
    client, alice, fake_llm, test_database_url
):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    seed_proposal(test_database_url, conversation_id, [ONE_DATE, CHOICES])
    fake_llm.queue(text_chunks("Sure.") + [usage_chunk()])

    chat(client, alice, "and bring wine", conversation_id)

    notes = [m["content"] for m in fake_llm.chat_requests[0]["messages"] if m["role"] == "system"]
    assert notes[-1] == held_proposal_note([ONE_DATE, CHOICES])
    assert "Date: 2026-10-02T19:00" in notes[-1]
    assert "Date: 2026-10-02 or 2026-10-09 (not picked yet)" in notes[-1]


def test_the_held_note_is_dropped_once_the_turn_proposes(client, alice, fake_llm, test_database_url):
    ready_user(client, alice)
    conversation_id = seed_conversation(test_database_url, client, alice)
    seed_proposal(test_database_url, conversation_id, [ONE_DATE])
    propose(fake_llm, {**DINNER, "when": {"start": "2026-10-02T19:30"}})

    chat(client, alice, "unrelated: taxes", conversation_id)

    second = fake_llm.chat_requests[1]["messages"]
    assert held_proposal_note([ONE_DATE]) not in [m["content"] for m in second if m["role"] == "system"]
