"""The `when` parser and its reverse (thought-dates task 1.2). No database."""

from datetime import UTC, date, datetime, time

import pytest

from app.errors import ApiError
from app.thoughts import dates
from app.thoughts.dates import (
    NO_DATE,
    DateColumns,
    parse_when,
    today_in,
    when_of,
    zone_from,
)


def test_a_timed_start_with_a_zone_round_trips():
    columns = parse_when({"start": "2026-10-02T19:00", "end": None, "time_zone": "Europe/Oslo"})
    assert columns == DateColumns(
        starts_on=date(2026, 10, 2), starts_at=time(19, 0), time_zone="Europe/Oslo"
    )
    assert when_of(columns) == {"start": "2026-10-02T19:00", "end": None, "time_zone": "Europe/Oslo"}


def test_days_with_an_end_round_trip():
    when = {"start": "2026-11-03", "end": "2026-11-06", "time_zone": "Europe/Oslo"}
    columns = parse_when(when)
    assert (columns.starts_on, columns.starts_at, columns.ends_on, columns.ends_at) == (
        date(2026, 11, 3), None, date(2026, 11, 6), None,
    )
    assert when_of(columns) == when


def test_a_timed_range_round_trips():
    when = {"start": "2026-10-06T10:00", "end": "2026-10-06T11:30", "time_zone": "Asia/Tokyo"}
    assert when_of(parse_when(when)) == when


def test_null_is_no_date():
    assert parse_when(None) == NO_DATE
    assert when_of(NO_DATE) is None
    assert set(NO_DATE.values()) == {"starts_on", "starts_at", "ends_on", "ends_at", "time_zone"}
    assert all(value is None for value in NO_DATE.values().values())


@pytest.mark.parametrize("end", ["2026-11-06", "2026-11-06T00:00"])
def test_the_end_may_equal_the_start(end):
    start = end
    assert parse_when({"start": start, "end": end}).ends_on == date(2026, 11, 6)


@pytest.mark.parametrize(
    "when",
    [
        # End before start.
        {"start": "2026-11-06", "end": "2026-11-03"},
        {"start": "2026-10-06T10:00", "end": "2026-10-06T09:59"},
        # Time on one side only.
        {"start": "2026-10-06T10:00", "end": "2026-10-06"},
        {"start": "2026-10-06", "end": "2026-10-07T10:00"},
        # Not a date.
        {"start": "next Friday"},
        {"start": "2026-02-30"},
        {"start": "2026-10-02T24:00"},
        {"start": "2026-10-02T19:60"},
        {"start": "2026-10-02T19:00:00"},
        {"start": "2026-10-02T19:00+02:00"},
        {"start": "20261002"},
        {"start": "2026-W40-5"},
        {"start": ""},
        {"start": 20261002},
        {"start": "2026-10-02", "end": "soon"},
        # No start.
        {},
        {"start": None, "end": "2026-10-02"},
        {"end": "2026-10-02"},
        # Not an object.
        "2026-10-02",
        ["2026-10-02"],
    ],
)
def test_a_bad_date_is_refused_naming_when(when):
    with pytest.raises(ApiError) as caught:
        parse_when(when)
    assert caught.value.status_code == 422
    assert caught.value.code == "validation_error"
    assert caught.value.message.startswith("when: ")


@pytest.mark.parametrize(
    "zone, stored",
    [
        ("Mars/Base", "UTC"),
        (None, "UTC"),
        ("", "UTC"),
        ("   ", "UTC"),
        ("/etc/passwd", "UTC"),
        ("../../etc/passwd", "UTC"),
        ("America", "UTC"),
        (42, "UTC"),
        ("America/Los_Angeles", "America/Los_Angeles"),
    ],
)
def test_a_missing_or_unknown_zone_is_stored_as_utc(zone, stored):
    assert parse_when({"start": "2026-10-02", "time_zone": zone}).time_zone == stored
    assert zone_from(zone).key == stored


def test_a_missing_zone_key_is_stored_as_utc():
    assert parse_when({"start": "2026-10-02"}).time_zone == "UTC"


def test_today_is_the_local_date(monkeypatch):
    # 06:30 UTC on Friday 2 October is still Thursday in Los Angeles, and
    # 15:30 in Tokyo.
    monkeypatch.setattr(dates, "utc_now", lambda: datetime(2026, 10, 2, 6, 30, tzinfo=UTC))
    assert today_in(zone_from("America/Los_Angeles")) == date(2026, 10, 1)
    assert today_in(zone_from("Asia/Tokyo")) == date(2026, 10, 2)
    assert today_in(zone_from("Mars/Base")) == date(2026, 10, 2)
