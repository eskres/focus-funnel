"""The Library list in the store: list_thoughts(), its filters and its cursor
(thought-library tasks 1.1 and 1.2).

The tag filter is ARRAY @>, which SQLite has not, so these run on Postgres.
"""

import base64
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, text

from app.errors import ApiError
from app.models import Thought, User, UserCategory
from app.models.thought import THOUGHT_STATUSES
from app.thoughts.library import decode_cursor, encode_cursor
from app.thoughts.store import MAX_TAG, check_status, clean_tag, clean_tags, set_status
from tests.chat_helpers import run_db
from tests.library_helpers import (
    FILED,
    all_pages,
    ids_of,
    listing,
    make_user,
    newest_first,
    seed,
    seed_many,
    titles_of,
)

pytestmark = pytest.mark.postgres

LA = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def alice(test_database_url) -> str:
    return make_user(test_database_url, "alice")


def nov(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 11, day, hour, 0, tzinfo=UTC)


def three_days(url, user_id):
    """The spec's three thoughts, filed out of title order on 1 to 3 November."""
    return seed(
        url,
        user_id,
        {"title": "Buy oat milk", "created_at": nov(1)},
        {"title": "Podcast about maps", "created_at": nov(3)},
        {"title": "Call the plumber", "created_at": nov(2)},
    )


def tasks(url, user_id):
    """An open task and a done one, as in the status scenarios."""
    return seed(
        url,
        user_id,
        {"title": "Call the plumber", "category": "task", "created_at": nov(2)},
        {"title": "Buy oat milk", "category": "task", "status": "done", "created_at": nov(1)},
    )


def refusal(error: ApiError) -> tuple[int, str, str]:
    return error.status_code, error.code, error.message


# ------------------------------------------------------------ order and filters


def test_newest_first(test_database_url, alice):
    three_days(test_database_url, alice)
    answer = listing(test_database_url, alice)
    assert titles_of(answer) == ["Podcast about maps", "Call the plumber", "Buy oat milk"]
    assert answer["next_cursor"] is None


def test_category(test_database_url, alice):
    seed(
        test_database_url,
        alice,
        {"title": "Call the plumber", "category": "task", "created_at": nov(1)},
        {"title": "Podcast about maps", "category": "idea", "created_at": nov(2)},
        {"title": "Loose note", "created_at": nov(3)},
        {"title": "Fix the gate", "category": "task", "created_at": nov(4)},
    )
    answer = listing(test_database_url, alice, category="task")
    assert titles_of(answer) == ["Fix the gate", "Call the plumber"]
    assert {item["category"] for item in answer["items"]} == {"task"}
    # The category is cleaned as categories are stored.
    assert titles_of(listing(test_database_url, alice, category="  Task ")) == titles_of(answer)


@pytest.mark.parametrize("tag", [" Home", "#home", "HOME", "  #Home  "])
def test_tag_is_cleaned_before_matching(test_database_url, alice, tag):
    seed(
        test_database_url,
        alice,
        {"title": "Fix the gate", "tags": ["home", "diy"], "created_at": nov(1)},
        {"title": "Podcast about maps", "tags": ["maps"], "created_at": nov(2)},
        {"title": "Paint the hall", "tags": ["home"], "created_at": nov(3)},
    )
    answer = listing(test_database_url, alice, tag=tag)
    assert titles_of(answer) == ["Paint the hall", "Fix the gate"]
    assert all("home" in item["tags"] for item in answer["items"])


def test_status_filters(test_database_url, alice):
    tasks(test_database_url, alice)
    assert titles_of(listing(test_database_url, alice, status="open")) == ["Call the plumber"]
    assert titles_of(listing(test_database_url, alice, status="done")) == ["Buy oat milk"]
    assert titles_of(listing(test_database_url, alice)) == ["Call the plumber", "Buy oat milk"]


def test_filed_days_are_local_days(test_database_url, alice):
    # 20:00 on 1 November in Los Angeles is 04:00 on 2 November in UTC.
    seed(test_database_url, alice, {"title": "Evening note", "created_at": nov(2, hour=4)})
    one_nov = listing(
        test_database_url, alice, filed_from=date(2026, 11, 1), filed_to=date(2026, 11, 1), zone=LA
    )
    two_nov = listing(
        test_database_url, alice, filed_from=date(2026, 11, 2), filed_to=date(2026, 11, 2), zone=LA
    )
    assert titles_of(one_nov) == ["Evening note"]
    assert titles_of(two_nov) == []


def test_filed_date_not_the_thoughts_date(test_database_url, alice):
    seed(
        test_database_url,
        alice,
        {
            "title": "Dentist",
            "created_at": datetime(2026, 10, 1, 12, tzinfo=UTC),
            "starts_on": date(2026, 11, 5),
            "time_zone": "UTC",
        },
    )
    answer = listing(
        test_database_url, alice, filed_from=date(2026, 11, 1), filed_to=date(2026, 11, 30)
    )
    assert answer["items"] == []


def test_filters_together(test_database_url, alice):
    match = {"category": "task", "tags": ["home"]}
    seed(
        test_database_url,
        alice,
        {"title": "Fix the gate", **match, "created_at": nov(3)},
        {"title": "Paint the hall", **match, "created_at": nov(20)},
        {"title": "Done task", **match, "status": "done", "created_at": nov(4)},
        {"title": "October task", **match, "created_at": datetime(2026, 10, 31, 12, tzinfo=UTC)},
        {"title": "December task", **match, "created_at": datetime(2026, 12, 1, 12, tzinfo=UTC)},
        {"title": "Idea at home", "category": "idea", "tags": ["home"], "created_at": nov(5)},
        {"title": "Work task", "category": "task", "tags": ["work"], "created_at": nov(6)},
    )
    answer = listing(
        test_database_url,
        alice,
        category="task",
        tag="home",
        status="open",
        filed_from=date(2026, 11, 1),
        filed_to=date(2026, 11, 30),
        zone=ZoneInfo("UTC"),
    )
    assert titles_of(answer) == ["Paint the hall", "Fix the gate"]


def test_nothing_matches(test_database_url, alice):
    three_days(test_database_url, alice)
    assert listing(test_database_url, alice, tag="nowhere") == {"items": [], "next_cursor": None}


@pytest.mark.parametrize("options", [{"tag": "   "}, {"tag": "#"}, {"category": "   "}])
def test_blank_tag_or_category_is_no_filter(test_database_url, alice, options):
    three_days(test_database_url, alice)
    assert titles_of(listing(test_database_url, alice, **options)) == titles_of(
        listing(test_database_url, alice)
    )
    assert len(listing(test_database_url, alice, **options)["items"]) == 3


def test_from_a_day_only(test_database_url, alice):
    three_days(test_database_url, alice)
    answer = listing(test_database_url, alice, filed_from=date(2026, 11, 2))
    assert titles_of(answer) == ["Podcast about maps", "Call the plumber"]


def test_to_a_day_only(test_database_url, alice):
    three_days(test_database_url, alice)
    answer = listing(test_database_url, alice, filed_to=date(2026, 11, 2))
    assert titles_of(answer) == ["Call the plumber", "Buy oat milk"]


def test_a_removed_category_still_lists_its_thoughts(test_database_url, alice):
    async def add_category(session):
        session.add(UserCategory(user_id=uuid.UUID(alice), name="garden"))
        await session.commit()

    async def remove_category(session):
        await session.execute(delete(UserCategory).where(UserCategory.name == "garden"))
        await session.commit()

    run_db(test_database_url, add_category)
    seed(test_database_url, alice, {"title": "Prune roses", "category": "garden", "created_at": nov(1)})
    run_db(test_database_url, remove_category)

    assert titles_of(listing(test_database_url, alice, category="garden")) == ["Prune roses"]


@pytest.mark.parametrize(
    "options",
    [
        {"category": "no such category"},
        {"tag": "x" * 60},
        {"filed_from": date(2026, 11, 3), "filed_to": date(2026, 11, 1)},
        {"tag": "\x00x"},
        {"category": "a\x00b"},
    ],
    ids=["unknown-category", "tag-of-60", "to-before-from", "nul-tag", "nul-category"],
)
def test_values_that_match_nothing_list_nothing(test_database_url, alice, options):
    three_days(test_database_url, alice)
    assert listing(test_database_url, alice, **options) == {"items": [], "next_cursor": None}


# ------------------------------------------------------------ statuses and tags


def test_thought_statuses_match_the_check_constraint(test_database_url):
    constraint = next(
        c for c in Thought.__table__.constraints if getattr(c, "name", None) == "ck_thoughts_status"
    )
    assert tuple(re.findall(r"'(\w+)'", str(constraint.sqltext))) == THOUGHT_STATUSES

    async def stored_definition(session):
        return (
            await session.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = 'ck_thoughts_status'"
                )
            )
        ).scalar_one()

    definition = run_db(test_database_url, stored_definition)
    assert tuple(re.findall(r"'(\w+)'", definition)) == THOUGHT_STATUSES


def expected_status_message() -> str:
    """Built from the tuple: commas, and `or` before the last."""
    choices = ", ".join(THOUGHT_STATUSES[:-1]) + " or " + THOUGHT_STATUSES[-1]
    return f"status: must be {choices}"


def test_check_status_gives_the_message_set_status_gives(test_database_url, alice):
    with pytest.raises(ApiError) as listed:
        check_status("pending")
    (thought_id,) = seed(test_database_url, alice, {"title": "Call the plumber", "created_at": nov(1)})

    async def mark_pending(session):
        user = await session.get(User, uuid.UUID(alice))
        try:
            await set_status(session, user, uuid.UUID(thought_id), "pending")
        except ApiError as error:
            return error

    stored = run_db(test_database_url, mark_pending)
    assert refusal(listed.value) == refusal(stored)
    assert refusal(listed.value) == (422, "validation_error", expected_status_message())
    message = listed.value.message
    assert message.startswith("status: must be ")
    assert all(status in message for status in THOUGHT_STATUSES)
    assert [check_status(status) for status in THOUGHT_STATUSES] == list(THOUGHT_STATUSES)


@pytest.mark.parametrize("value", [None, 1, "", "Done", ["open"]])
def test_check_status_refuses_anything_else(value):
    with pytest.raises(ApiError) as refused:
        check_status(value)
    assert refusal(refused.value) == (422, "validation_error", expected_status_message())


def test_clean_tag_has_no_length_check_and_clean_tags_keeps_its_own():
    assert clean_tag("  #Home   Office ") == "home office"
    assert clean_tag("x" * 60) == "x" * 60
    with pytest.raises(ApiError) as refused:
        clean_tags(["x" * (MAX_TAG + 1)])
    assert refusal(refused.value) == (
        422,
        "validation_error",
        f"tags: each tag must be at most {MAX_TAG} characters",
    )
    assert clean_tags([" #Home", "home", "Work  Plans"]) == ["home", "work plans"]


# ------------------------------------------------------------ the cursor


@pytest.mark.parametrize("microsecond", [0, 123456])
def test_a_cursor_round_trips(microsecond):
    moment = datetime(2026, 11, 2, 4, 5, 6, microsecond, tzinfo=ZoneInfo("Europe/Oslo"))
    thought_id = uuid.uuid4()
    cursor = encode_cursor(moment, thought_id)
    assert "=" not in cursor
    decoded = decode_cursor(cursor)
    assert (decoded.created_at, decoded.id) == (moment, thought_id)
    assert decoded.created_at.utcoffset() == timedelta(0)


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


VALID_TIME = "2026-11-02T04:00:00.000000+00:00"
SOME_ID = "6f1c2f0e-8f7a-4f53-9d43-0e2f3c4b5a69"


def padded_valid_cursor() -> str:
    """A cursor encode_cursor() wrote, with `=` padding added. (Its 69 bytes
    need none, so base64 would read it the same; the alphabet check refuses it.)"""
    cursor = encode_cursor(datetime.fromisoformat(VALID_TIME), uuid.UUID(SOME_ID))
    decode_cursor(cursor)
    return cursor + "="


@pytest.mark.parametrize(
    "cursor",
    [
        "abc",
        b64(b"\xff\xfe"),
        b64(f"{VALID_TIME}|not-a-uuid".encode()),
        b64(VALID_TIME.encode()),
        b64(b"a|b|c"),
        b64(b"|"),
        b64(f"2026-11-02T04:00:00|{SOME_ID}".encode()),
        b64(f"0001-01-01T00:00:00+05:00|{SOME_ID}".encode()),
        padded_valid_cursor(),
        "",
        "a b",
    ],
    ids=[
        "abc",
        "not-utf8",
        "not-a-uuid",
        "time-alone",
        "three-parts",
        "bar-alone",
        "no-offset",
        "out-of-range",
        "padded",
        "empty",
        "space",
    ],
)
def test_a_cursor_that_does_not_decode_is_refused(cursor):
    with pytest.raises(ApiError) as refused:
        decode_cursor(cursor)
    assert refusal(refused.value) == (422, "validation_error", "cursor: not a valid cursor")


def store_fetch(url, user_id, **filters):
    def fetch(limit, cursor):
        return listing(
            url,
            user_id,
            limit=limit,
            cursor=decode_cursor(cursor) if cursor else None,
            **filters,
        )

    return fetch


def assert_pages(pages, sizes, expected_ids):
    assert [len(page["items"]) for page in pages] == sizes
    assert all(page["next_cursor"] is not None for page in pages[:-1])
    assert pages[-1]["next_cursor"] is None
    assert [item_id for page in pages for item_id in ids_of(page)] == expected_ids


def test_120_thoughts_come_in_pages_of_50_50_and_20(test_database_url, alice):
    ids = seed_many(test_database_url, alice, 120)
    pages = all_pages(store_fetch(test_database_url, alice))
    assert_pages(pages, [50, 50, 20], newest_first(ids))


@pytest.mark.parametrize(
    "count, sizes", [(50, [50]), (51, [50, 1]), (100, [50, 50])], ids=["50", "51", "100"]
)
def test_the_extra_row_decides_whether_more_exist(test_database_url, alice, count, sizes):
    ids = seed_many(test_database_url, alice, count)
    pages = all_pages(store_fetch(test_database_url, alice))
    assert_pages(pages, sizes, newest_first(ids))


def test_whole_second_times_page_the_same_way(test_database_url, alice):
    ids = seed_many(test_database_url, alice, 120, whole_seconds=True)
    pages = all_pages(store_fetch(test_database_url, alice))
    assert_pages(pages, [50, 50, 20], newest_first(ids))


def test_show_more_keeps_the_filters(test_database_url, alice):
    # 120 tagged home and 60 not, interleaved in filed order.
    rows_tagged = []
    seeded = []
    for index in range(180):
        tagged = index % 3 != 2
        seeded.append(tagged)
        rows_tagged.append(
            {
                "title": f"Thought {index}",
                "tags": ["home", "diy"] if tagged else ["work"],
                "created_at": FILED + timedelta(minutes=index, microseconds=index + 1),
            }
        )
    ids = seed(test_database_url, alice, *rows_tagged)
    tagged_ids = [thought_id for thought_id, tagged in zip(ids, seeded, strict=True) if tagged]
    assert len(tagged_ids) == 120

    pages = all_pages(store_fetch(test_database_url, alice, tag="home"))
    assert_pages(pages, [50, 50, 20], newest_first(tagged_ids))
    assert all("home" in item["tags"] for page in pages for item in page["items"])


def test_three_thoughts_with_one_filed_time_across_a_boundary(test_database_url, alice):
    same = FILED + timedelta(microseconds=5)
    ids = seed(
        test_database_url,
        alice,
        {"title": "Older", "created_at": FILED},
        *({"title": f"Same {n}", "created_at": same} for n in range(3)),
        {"title": "Newer", "created_at": FILED + timedelta(seconds=1)},
    )
    pages = all_pages(store_fetch(test_database_url, alice), limit=2)
    listed = [item_id for page in pages for item_id in ids_of(page)]
    assert sorted(listed) == sorted(ids)
    assert len(listed) == len(set(listed)) == 5
    same_ids = sorted(ids[1:4], key=uuid.UUID, reverse=True)
    assert listed == [ids[4], *same_ids, ids[0]]
