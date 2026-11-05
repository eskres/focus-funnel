"""GET /api/thoughts/upcoming: dated thoughts from the browser's today on (thought-dates task 5.4).

The query is plain SQL with no search columns, so these run on SQLite in the
default suite.
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from app.models import Thought
from tests.chat_helpers import error_code, run_db, user_id_for

# Wednesday 30 September 2026, the browser's local today in the spec's scenarios.
TODAY = "2026-09-30"


def add_thoughts(url, user_id, *rows: dict) -> list[str]:
    """Store thoughts with these fields; each is filed a minute after the one before."""
    filed = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    async def work(session):
        thoughts = [
            Thought(
                user_id=uuid.UUID(user_id),
                summary=f"About {row['title']}.",
                tags=[],
                created_at=filed + timedelta(minutes=index),
                **row,
            )
            for index, row in enumerate(rows)
        ]
        session.add_all(thoughts)
        await session.commit()
        return [str(thought.id) for thought in thoughts]

    return run_db(url, work)


def upcoming(client, headers, day=TODAY):
    response = client.get("/api/thoughts/upcoming", headers=headers, params={"from": day})
    assert response.status_code == 200, response.text
    return response.json()


def titles(answer) -> list[str]:
    return [item["title"] for item in answer["items"]]


def test_mixed_dates_list_from_today_on_in_date_order(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    add_thoughts(
        test_database_url,
        user_id,
        dict(title="Last Monday", starts_on=date(2026, 9, 28), time_zone="Europe/Oslo"),
        # Filed before the plumber call, but it has a time, so it comes after it.
        dict(
            title="Dinner with Sam",
            category="task",
            starts_on=date(2026, 10, 2),
            starts_at=time(19, 0),
            time_zone="Europe/Oslo",
        ),
        dict(title="Call the plumber", starts_on=date(2026, 10, 2), time_zone="Europe/Oslo"),
        dict(
            title="Trip",
            starts_on=date(2026, 9, 29),
            ends_on=date(2026, 10, 2),
            time_zone="Europe/Oslo",
        ),
        dict(title="An idea with no date"),
    )

    answer = upcoming(client, alice)

    assert titles(answer) == ["Trip", "Call the plumber", "Dinner with Sam"]
    assert answer["more"] is False
    dinner = answer["items"][2]
    assert set(dinner) == {"id", "title", "category", "when"}
    assert dinner["category"] == "task"
    assert dinner["when"] == {"start": "2026-10-02T19:00", "end": None, "time_zone": "Europe/Oslo"}
    assert answer["items"][0]["when"] == {
        "start": "2026-09-29",
        "end": "2026-10-02",
        "time_zone": "Europe/Oslo",
    }


def test_the_same_start_breaks_ties_by_filing_time(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    add_thoughts(
        test_database_url,
        user_id,
        dict(title="First filed", starts_on=date(2026, 10, 1), starts_at=time(9, 0)),
        dict(title="Second filed", starts_on=date(2026, 10, 1), starts_at=time(9, 0)),
        dict(title="Earlier time", starts_on=date(2026, 10, 1), starts_at=time(8, 0)),
    )

    assert titles(upcoming(client, alice)) == ["Earlier time", "First filed", "Second filed"]


def test_nothing_coming_up(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    add_thoughts(
        test_database_url,
        user_id,
        dict(title="Yesterday", starts_on=date(2026, 9, 29)),
        dict(title="No date"),
    )

    assert upcoming(client, alice) == {"items": [], "more": False}


def test_250_dated_thoughts_give_the_first_200_and_more(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    first = date(2026, 9, 30)
    add_thoughts(
        test_database_url,
        user_id,
        *(dict(title=f"Day {n:03d}", starts_on=first + timedelta(days=n)) for n in range(250)),
    )

    answer = upcoming(client, alice)

    assert len(answer["items"]) == 200
    assert answer["more"] is True
    assert titles(answer) == [f"Day {n:03d}" for n in range(200)]


def test_exactly_200_have_no_more(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    add_thoughts(
        test_database_url,
        user_id,
        *(dict(title=f"Day {n}", starts_on=date(2026, 10, 1)) for n in range(200)),
    )

    answer = upcoming(client, alice)

    assert len(answer["items"]) == 200
    assert answer["more"] is False


def test_another_users_thoughts_are_never_listed(client, alice, bob, test_database_url):
    tomorrow = date(2026, 10, 1)
    add_thoughts(test_database_url, user_id_for(client, alice), dict(title="Alice's", starts_on=tomorrow))
    add_thoughts(test_database_url, user_id_for(client, bob), dict(title="Bob's", starts_on=tomorrow))

    assert titles(upcoming(client, alice)) == ["Alice's"]
    assert titles(upcoming(client, bob)) == ["Bob's"]


def test_from_is_required_and_must_be_a_day(client, alice):
    user_id_for(client, alice)
    for params in ({}, {"from": "next Friday"}, {"from": "2026-02-30"}):
        response = client.get("/api/thoughts/upcoming", headers=alice, params=params)
        assert response.status_code == 422, params
        assert error_code(response) == "validation_error"
        assert "from" in response.json()["error"]["message"]


def test_upcoming_is_not_read_as_a_thought_id(client, alice, test_database_url):
    """The route sits before /{thought_id}, so it never answers not_found or an id error."""
    user_id_for(client, alice)
    response = client.get("/api/thoughts/upcoming?from=2026-09-30", headers=alice)
    assert response.status_code == 200


def test_signed_out_is_refused(client):
    response = client.get("/api/thoughts/upcoming", params={"from": TODAY})
    assert response.status_code == 401
