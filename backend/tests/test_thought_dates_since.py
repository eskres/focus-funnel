"""`since` in the user's local days (thought-dates task 2.2)."""

import json
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.thoughts import dates
from app.thoughts.search import _as_end, _as_start
from tests.chat_helpers import (
    chat,
    ready_user,
    text_chunks,
    tool_call_chunks,
    user_id_for,
)
from tests.test_search_tool import store

LOS_ANGELES = ZoneInfo("America/Los_Angeles")


def test_a_start_and_an_end_date_are_local_midnights():
    assert _as_start(date(2026, 9, 30), LOS_ANGELES) == datetime(2026, 9, 30, 7, 0, tzinfo=UTC)
    assert _as_end(date(2026, 9, 30), LOS_ANGELES) == datetime(2026, 10, 1, 7, 0, tzinfo=UTC)
    tokyo = ZoneInfo("Asia/Tokyo")
    assert _as_start(date(2026, 10, 1), tokyo) == datetime(2026, 9, 30, 15, 0, tzinfo=UTC)


def test_without_a_zone_the_days_are_utc_as_before():
    assert _as_start(date(2026, 9, 30)) == datetime(2026, 9, 30, tzinfo=UTC)
    assert _as_end(date(2026, 9, 30)) == datetime(2026, 10, 1, tzinfo=UTC)
    moment = datetime(2026, 9, 30, 12, tzinfo=UTC)
    assert _as_start(moment, LOS_ANGELES) is moment


@pytest.mark.postgres
def test_filed_since_today_in_local_days(client, alice, fake_llm, test_database_url, monkeypatch):
    # 22:00 on Wednesday 30 September in Los Angeles: Thursday 1 October in UTC.
    monkeypatch.setattr(dates, "utc_now", lambda: datetime(2026, 10, 1, 5, 0, tzinfo=UTC))
    ready_user(client, alice)
    user_id = user_id_for(client, alice)
    # Filed at 20:00 local on 30 September (03:00 UTC on 1 October), and at
    # 09:00 local on 30 September (16:00 UTC the same day, before UTC's 1 October).
    store(test_database_url, user_id, fake_llm, "Evening milk", "Buy oat milk.",
          created=datetime(2026, 10, 1, 3, 0, tzinfo=UTC))
    store(test_database_url, user_id, fake_llm, "Morning milk", "Buy soy milk.",
          created=datetime(2026, 9, 30, 16, 0, tzinfo=UTC))
    # Filed at 23:30 local on 29 September: 06:30 UTC on 30 September.
    store(test_database_url, user_id, fake_llm, "Yesterday milk", "Buy rice milk.",
          created=datetime(2026, 9, 30, 6, 30, tzinfo=UTC))
    # The model searches from the day it is told is today.
    fake_llm.queue(
        tool_call_chunks("search_thoughts", json.dumps({"query": "milk", "since": "2026-09-30"})),
        text_chunks("Two things."),
    )

    response = chat(client, alice, "what did I file today?", time_zone="America/Los_Angeles")

    assert response.status_code == 200, response.text
    first, second = fake_llm.chat_requests
    assert first["messages"][0]["content"].endswith("Today is Wednesday 2026-09-30. Weeks start on Monday.")
    content = second["messages"][-1]["content"]
    assert content.startswith("2 of your thoughts match")
    assert "Evening milk" in content and "Morning milk" in content
    # The filed day is the local day too, never a day after the model's today.
    assert "Evening milk · filed 2026-09-30" in content
    assert "Morning milk · filed 2026-09-30" in content
    assert "filed 2026-10-01" not in content
    # In UTC days the search from 30 September would also list this one.
    assert "Yesterday milk" not in content
