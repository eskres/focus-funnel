"""GET /api/thoughts: the Library list over HTTP (thought-library tasks 1.2 to 1.4).

The tag filter is ARRAY @>, which SQLite has not, so these run on Postgres.
"""

import base64
import logging
import uuid
from datetime import UTC, date, datetime, time, timedelta

import pytest

import app.chat.model_call
import app.chat.model_info
import app.provider_models
import app.providers
import app.thoughts.embeddings
import app.thoughts.indexing
from app.errors import ApiError
from app.models import User
from app.models.thought import THOUGHT_STATUSES
from app.thoughts.store import check_status, set_status
from tests.chat_helpers import error_code, run_db, user_id_for
from tests.library_helpers import FILED, all_pages, newest_first, seed, seed_many
from tests.thought_helpers import counted_queries

pytestmark = pytest.mark.postgres

ROW_KEYS = {"id", "title", "category", "tags", "status", "created_at", "when"}
SOME_ID = "6f1c2f0e-8f7a-4f53-9d43-0e2f3c4b5a69"


def get_list(client, headers, params=None, *, url="/api/thoughts"):
    response = client.get(url, headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def ids_of(answer) -> list[str]:
    return [item["id"] for item in answer["items"]]


def titles_of(answer) -> list[str]:
    return [item["title"] for item in answer["items"]]


def api_fetch(client, headers, **filters):
    def fetch(limit, cursor):
        params = {"limit": limit, **filters}
        if cursor:
            params["cursor"] = cursor
        return get_list(client, headers, params)

    return fetch


def b64(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode()).rstrip(b"=").decode()


@pytest.fixture
def quiet_errors(caplog):
    """Fails the test when anything is logged as an unhandled error."""
    caplog.set_level(logging.DEBUG, logger="app.errors")
    yield
    logged = [record for record in caplog.records if record.name == "app.errors"]
    assert logged == [], [record.getMessage() for record in logged]
    assert "Traceback" not in caplog.text
    assert "internal_error" not in caplog.text


# ------------------------------------------------------------ shape


def test_the_answer_and_its_items(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    seed(test_database_url, user_id, {"title": "Fix the gate", "category": "task", "tags": ["home"], "created_at": FILED})
    answer = get_list(client, alice)
    assert set(answer) == {"items", "next_cursor"}
    assert answer["next_cursor"] is None
    (item,) = answer["items"]
    assert set(item) == ROW_KEYS
    assert (item["title"], item["category"], item["tags"], item["status"], item["when"]) == (
        "Fix the gate",
        "task",
        ["home"],
        "open",
        None,
    )


def test_items_match_the_detail_view(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    timed, day_only, undated = seed(
        test_database_url,
        user_id,
        {
            "title": "Planning meeting",
            "category": "event",
            "tags": ["work"],
            "status": "done",
            "starts_on": date(2026, 11, 4),
            "starts_at": time(9, 0),
            "ends_on": date(2026, 11, 4),
            "ends_at": time(10, 0),
            "time_zone": "Europe/Oslo",
            "created_at": FILED,
        },
        {
            "title": "Bin day",
            "category": "task",
            "tags": ["home"],
            "starts_on": date(2026, 11, 6),
            "time_zone": "Europe/Oslo",
            "created_at": FILED + timedelta(minutes=1),
        },
        {"title": "An idea", "tags": [], "created_at": FILED + timedelta(minutes=2)},
    )
    listed = {item["id"]: item for item in get_list(client, alice)["items"]}
    assert set(listed) == {timed, day_only, undated}
    for thought_id in (timed, day_only, undated):
        detail = client.get(f"/api/thoughts/{thought_id}", headers=alice).json()
        for key in ("status", "when", "created_at", "category", "tags", "title"):
            assert listed[thought_id][key] == detail[key], key
    assert listed[timed]["when"] == {
        "start": "2026-11-04T09:00",
        "end": "2026-11-04T10:00",
        "time_zone": "Europe/Oslo",
    }
    assert listed[timed]["status"] == "done"
    assert listed[undated]["when"] is None


def test_the_page_size_is_50_with_no_limit(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    seed_many(test_database_url, user_id, 60)
    answer = get_list(client, alice)
    assert len(answer["items"]) == 50
    assert answer["next_cursor"] is not None


# ------------------------------------------------------------ paging


def test_paging_stays_stable_while_thoughts_change(client, alice, test_database_url, fake_llm):
    user_id = user_id_for(client, alice)
    ids = newest_first(seed_many(test_database_url, user_id, 120))
    first = get_list(client, alice, {"limit": 50})
    assert ids_of(first) == ids[:50]

    # A thought filed after the first page, the 50th deleted, and the 60th
    # given a new title and marked done.
    (filed_later,) = seed(test_database_url, user_id, {"title": "Filed later", "created_at": datetime.now(UTC)})
    assert client.delete(f"/api/thoughts/{ids[49]}", headers=alice).status_code == 204
    renamed = client.patch(f"/api/thoughts/{ids[59]}", headers=alice, json={"title": "Renamed"})
    assert renamed.status_code == 200, renamed.text

    async def mark_done(session):
        user = await session.get(User, uuid.UUID(user_id))
        await set_status(session, user, uuid.UUID(ids[59]), "done")
        await session.commit()

    run_db(test_database_url, mark_done)

    second = get_list(client, alice, {"limit": 50, "cursor": first["next_cursor"]})
    assert ids_of(second) == ids[50:100]
    assert filed_later not in ids_of(second)
    sixtieth = [item for item in second["items"] if item["id"] == ids[59]]
    assert len(sixtieth) == 1
    assert (sixtieth[0]["title"], sixtieth[0]["status"]) == ("Renamed", "done")

    fresh = get_list(client, alice, {"limit": 50})
    assert ids_of(fresh)[0] == filed_later


def test_another_users_cursor_lists_only_your_own(client, alice, bob, test_database_url):
    alice_id = user_id_for(client, alice)
    bob_id = user_id_for(client, bob)
    alices = seed_many(test_database_url, alice_id, 30, start=FILED + timedelta(seconds=30))
    seed_many(test_database_url, bob_id, 120)
    bobs_first = get_list(client, bob, {"limit": 50})
    bobs_second = get_list(client, bob, {"limit": 50, "cursor": bobs_first["next_cursor"]})
    assert bobs_second["next_cursor"] is not None

    answer = get_list(client, alice, {"limit": 50, "cursor": bobs_second["next_cursor"]})
    assert answer["items"]
    assert set(ids_of(answer)) <= set(alices)


# ------------------------------------------------------------ checks


def status_message() -> str:
    choices = ", ".join(THOUGHT_STATUSES[:-1]) + " or " + THOUGHT_STATUSES[-1]
    return f"status: must be {choices}"


@pytest.mark.parametrize(
    "query, prefix",
    [
        ("limit=0", "query.limit: "),
        ("limit=101", "query.limit: "),
        ("limit=500", "query.limit: "),
        ("limit=abc", "query.limit: "),
        ("limit=1.5", "query.limit: "),
        ("limit=%C2%B2", "query.limit: "),
        ("filed_from=2026-02-30", "query.filed_from: "),
        ("filed_to=9999-12-31", "query.filed_to: "),
        ("filed_from=0001-01-01&time_zone=Asia/Tokyo", "query.filed_from: "),
    ],
)
def test_a_typed_parameter_out_of_range_is_refused(client, alice, quiet_errors, query, prefix):
    user_id_for(client, alice)
    response = client.get(f"/api/thoughts?{query}", headers=alice)
    assert response.status_code == 422, response.text
    assert set(response.json()) == {"error"}
    assert set(response.json()["error"]) >= {"code", "message"}
    assert error_code(response) == "validation_error"
    assert response.json()["error"]["message"].startswith(prefix)


@pytest.mark.parametrize(
    "query, message",
    [
        ("status=pending", None),
        ("cursor=abc", "cursor: not a valid cursor"),
        (f"cursor={b64(f'0001-01-01T00:00:00+05:00|{SOME_ID}')}", "cursor: not a valid cursor"),
    ],
    ids=["status", "cursor-abc", "cursor-out-of-range"],
)
def test_status_and_cursor_are_refused_with_the_projects_message(
    client, alice, quiet_errors, query, message
):
    user_id_for(client, alice)
    response = client.get(f"/api/thoughts?{query}", headers=alice)
    assert response.status_code == 422, response.text
    assert error_code(response) == "validation_error"
    if message is None:
        with pytest.raises(ApiError) as refused:
            check_status("pending")
        message = refused.value.message
        assert message == status_message()
        assert message.startswith("status: must be ")
        assert all(status in message for status in THOUGHT_STATUSES)
    assert response.json()["error"]["message"] == message


@pytest.mark.parametrize(
    "query",
    [
        "filed_from=1900-01-01&time_zone=Pacific/Kiritimati",
        "filed_to=9998-12-31&time_zone=Etc/GMT%2B12",
    ],
)
def test_the_edges_of_the_filed_day_range_answer(client, alice, quiet_errors, query):
    user_id_for(client, alice)
    response = client.get(f"/api/thoughts?{query}", headers=alice)
    assert response.status_code == 200, response.text


EMPTY_PARAMETERS = [
    "limit=",
    "cursor=",
    "status=",
    "category=",
    "tag=",
    "filed_from=",
    "filed_to=",
    "time_zone=",
    "status=&filed_from=",
]


def test_an_empty_parameter_is_read_as_absent(client, alice, test_database_url, quiet_errors):
    user_id = user_id_for(client, alice)
    seed_many(test_database_url, user_id, 60, tags=["home"], category="task")
    plain = get_list(client, alice)
    assert len(plain["items"]) == 50
    assert plain["next_cursor"] is not None
    for query in EMPTY_PARAMETERS:
        answer = get_list(client, alice, url=f"/api/thoughts?{query}")
        assert answer == plain, query


# ------------------------------------------------------------ unknown values


def filed_both_sides(url, user_id):
    """One thought at 04:00 UTC on 2 November, one at 23:00 UTC on 1 November."""
    return seed(
        url,
        user_id,
        {"title": "Early on the 2nd", "created_at": datetime(2026, 11, 2, 4, tzinfo=UTC)},
        {"title": "Late on the 1st", "created_at": datetime(2026, 11, 1, 23, tzinfo=UTC)},
    )


def test_no_time_zone_reads_the_days_in_utc(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    filed_both_sides(test_database_url, user_id)
    answer = get_list(client, alice, {"filed_from": "2026-11-02", "filed_to": "2026-11-02"})
    assert titles_of(answer) == ["Early on the 2nd"]
    # Read in Tokyo, both are on 2 November: the zone does take effect.
    tokyo = get_list(
        client, alice, {"filed_from": "2026-11-02", "filed_to": "2026-11-02", "time_zone": "Asia/Tokyo"}
    )
    assert titles_of(tokyo) == ["Early on the 2nd", "Late on the 1st"]


@pytest.mark.parametrize(
    "zone",
    ["Mars/Base", "/etc/localtime", "../../etc/passwd", "a\x00b", "a" * 256, "a/" * 300 + "x", "utc"],
    ids=["mars", "etc-localtime", "dot-dot", "nul", "256-letters", "nested-300", "lowercase-utc"],
)
def test_a_time_zone_that_is_not_a_zone_name_reads_as_utc(
    client, alice, test_database_url, quiet_errors, zone
):
    user_id = user_id_for(client, alice)
    filed_both_sides(test_database_url, user_id)
    days = {"filed_from": "2026-11-02", "filed_to": "2026-11-02"}
    in_utc = get_list(client, alice, {**days, "time_zone": "UTC"})
    answer = get_list(client, alice, {**days, "time_zone": zone})
    assert answer == in_utc
    assert titles_of(answer) == ["Early on the 2nd"]
    assert titles_of(get_list(client, alice, {"filed_from": "2026-11-02", "time_zone": zone})) == [
        "Early on the 2nd"
    ]


@pytest.mark.parametrize(
    "params",
    [{"tag": "x" * 60}, {"tag": "\x00x"}, {"category": "a\x00b"}],
    ids=["tag-of-60", "nul-tag", "nul-category"],
)
def test_a_value_no_thought_has_lists_nothing(client, alice, test_database_url, quiet_errors, params):
    user_id = user_id_for(client, alice)
    seed_many(test_database_url, user_id, 3, tags=["x" * 50], category="a")
    assert get_list(client, alice, params) == {"items": [], "next_cursor": None}


def test_an_encoded_tag_is_one_value(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    done, _ = seed(
        test_database_url,
        user_id,
        {"title": "Odd tag", "tags": ["home & status=done"], "status": "done", "created_at": FILED},
        {"title": "Home", "tags": ["home"], "created_at": FILED + timedelta(minutes=1)},
    )
    answer = get_list(client, alice, url="/api/thoughts?tag=%23home%20%26%20status%3Ddone")
    assert ids_of(answer) == [done]


# ------------------------------------------------------------ owners


TWO_USER_CASES = {
    "none": {},
    "tag": {"tag": "home"},
    "category": {"category": "task"},
    "open": {"status": "open"},
    "done": {"status": "done"},
    "filed-days": {"filed_from": "2026-10-01", "filed_to": "2026-11-30"},
    "all": {
        "tag": "home",
        "category": "task",
        "status": "open",
        "filed_from": "2026-10-01",
        "filed_to": "2026-11-30",
    },
}


def seed_interleaved(url, alice_id, bob_id):
    """Each user gets 60 thoughts that match every case (status aside) and 60
    done ones; on one timeline bob's rows sit between alice's, before and after."""
    start = datetime(2026, 10, 20, 12, tzinfo=UTC)
    rows = {alice_id: [], bob_id: []}
    for index in range(240):
        owner = alice_id if index % 2 else bob_id
        rows[owner].append(
            {
                "title": f"Thought {index}",
                "category": "task",
                "tags": ["home"],
                "status": "done" if index % 4 >= 2 else "open",
                "created_at": start + timedelta(minutes=index * 7, microseconds=index + 1),
            }
        )
    # Bob also has rows filed before and after all of alice's.
    rows[bob_id].append({"title": "Bob first", "category": "task", "tags": ["home"], "created_at": start - timedelta(days=1)})
    rows[bob_id].append({"title": "Bob last", "category": "task", "tags": ["home"], "created_at": start + timedelta(days=5)})
    return seed(url, alice_id, *rows[alice_id]), rows[alice_id], seed(url, bob_id, *rows[bob_id])


def matches(row, params) -> bool:
    status = params.get("status")
    return status is None or row["status"] == status


@pytest.mark.parametrize("case", list(TWO_USER_CASES), ids=list(TWO_USER_CASES))
def test_two_users(client, alice, bob, test_database_url, case):
    params = TWO_USER_CASES[case]
    alice_id = user_id_for(client, alice)
    bob_id = user_id_for(client, bob)
    alice_ids, alice_rows, bob_ids = seed_interleaved(test_database_url, alice_id, bob_id)
    expected = newest_first(
        [thought_id for thought_id, row in zip(alice_ids, alice_rows, strict=True) if matches(row, params)]
    )
    assert len(expected) >= 60

    first = get_list(client, alice, {"limit": 50, **params})
    assert first["next_cursor"] is not None
    second = get_list(client, alice, {"limit": 50, "cursor": first["next_cursor"], **params})
    listed = ids_of(first) + ids_of(second)
    assert not set(listed) & set(bob_ids)
    assert set(listed) <= set(alice_ids)
    pages = all_pages(api_fetch(client, alice, **params))
    every = [item_id for page in pages for item_id in ids_of(page)]
    assert every == expected
    assert every[: len(listed)] == listed


def test_no_token_is_401(client):
    assert client.get("/api/thoughts").status_code == 401


def test_the_detail_and_upcoming_routes_answer_as_before(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    (thought_id,) = seed(
        test_database_url,
        user_id,
        {"title": "Bin day", "starts_on": date(2026, 11, 6), "time_zone": "UTC", "created_at": FILED},
    )
    detail = client.get(f"/api/thoughts/{thought_id}", headers=alice)
    assert detail.status_code == 200
    assert detail.json()["title"] == "Bin day"
    upcoming = client.get("/api/thoughts/upcoming", headers=alice, params={"from": "2026-11-01"})
    assert upcoming.status_code == 200
    assert [item["id"] for item in upcoming.json()["items"]] == [thought_id]
    assert client.get(f"/api/thoughts/{uuid.uuid4()}", headers=alice).status_code == 404


# ------------------------------------------------------------ no provider, and cost


LIST_REQUESTS = [
    {},
    {"tag": "home"},
    {"category": "task"},
    {"status": "open"},
    {"status": "done"},
    {"filed_from": "2026-10-01", "filed_to": "2026-11-30", "time_zone": "Europe/Oslo"},
    {"limit": 5},
]


def test_listing_needs_no_provider(client, alice, test_database_url, fake_llm, monkeypatch):
    user_id = user_id_for(client, alice)
    seed_many(test_database_url, user_id, 20, tags=["home"], category="task")

    def refuse(*args, **kwargs):
        raise AssertionError("the list called a provider")

    for module in (
        app.providers,
        app.chat.model_info,
        app.chat.model_call,
        app.provider_models,
        app.thoughts.embeddings,
    ):
        monkeypatch.setattr(module, "client_for", refuse)
    monkeypatch.setattr(app.providers, "make_client", refuse)
    for module in (app.thoughts.embeddings, app.thoughts.indexing):
        monkeypatch.setattr(module, "embed_texts", refuse)

    async def no_index(session):
        from sqlalchemy import func, select

        from app.models import ProviderKey, SearchIndex

        keys = (await session.execute(select(func.count()).select_from(ProviderKey))).scalar_one()
        indexes = (await session.execute(select(func.count()).select_from(SearchIndex))).scalar_one()
        return keys, indexes

    assert run_db(test_database_url, no_index) == (0, 0)
    for params in LIST_REQUESTS:
        answer = get_list(client, alice, params)
        if params.get("status") != "done":
            assert answer["items"], params
    assert fake_llm.requests == []


def test_a_page_of_100_runs_as_many_statements_as_a_page_of_1(client, alice, test_database_url):
    user_id = user_id_for(client, alice)
    seed_many(
        test_database_url,
        user_id,
        150,
        tags=["home"],
        status="done",
        starts_on=date(2026, 11, 6),
        time_zone="Europe/Oslo",
    )
    get_list(client, alice, {"limit": 1})  # warm up
    with counted_queries() as one:
        assert len(get_list(client, alice, {"limit": 1})["items"]) == 1
    with counted_queries() as hundred:
        assert len(get_list(client, alice, {"limit": 100})["items"]) == 100
    assert len(hundred) == len(one)
