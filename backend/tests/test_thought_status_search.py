"""Search by status and category (thought-status task 2.1).

Every scenario the `thought-search` delta of this change adds, on Postgres:
the filtered CTE for a search with a query, and the list with no query.
"""

from datetime import UTC, date, datetime

import pytest

from app.chat.config import get_chat_config
from app.errors import ApiError
from app.thoughts.store import set_status
from tests.chat_helpers import MODEL_LIST, FakeLLM, api_error, save_key, user_id_for
from tests.test_thought_search import search, set_created, store, titles
from tests.thought_helpers import EMBED_MODEL, entries, models_with_embedding, run_as

pytestmark = pytest.mark.postgres

LIMIT = get_chat_config().search.limit


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def alice_id(client, alice, fake):
    save_key(client, alice)
    return user_id_for(client, alice)


@pytest.fixture
def bob_id(client, bob, fake):
    save_key(client, bob, key="nb-bob-key-2222")
    return user_id_for(client, bob)


def mark_done(url, user_id, fake, thought_id):
    async def work(session, user, settings, http_client):
        await set_status(session, user, thought_id, "done")
        await session.commit()

    run_as(url, user_id, fake, work)


def task(url, user_id, fake, title, *, done=False, filed=None, **fields):
    fields.setdefault("category", "task")
    thought_id = store(url, user_id, fake, title, f"{title}.", **fields)
    if filed is not None:
        set_created(url, thought_id, filed)
    if done:
        mark_done(url, user_id, fake, thought_id)
    return thought_id


def calls(fake) -> int:
    return len(fake.embed_requests) + len(fake.chat_requests)


def plumber_and_milk(url, user_id, fake):
    """The delta's tasks: an open and a done plumber task, a done oat milk task,
    an open idea, and a plumber note."""
    task(url, user_id, fake, "Call the plumber", filed=datetime(2026, 11, 1, 9, tzinfo=UTC))
    task(url, user_id, fake, "Pay the plumber", done=True,
         filed=datetime(2026, 11, 2, 9, tzinfo=UTC))
    task(url, user_id, fake, "Buy oat milk", done=True, filed=datetime(2026, 11, 3, 9, tzinfo=UTC))
    task(url, user_id, fake, "Podcast about maps", category="idea",
         filed=datetime(2026, 11, 4, 9, tzinfo=UTC))
    task(url, user_id, fake, "The plumber said the boiler is old", category="note",
         filed=datetime(2026, 11, 5, 9, tzinfo=UTC))


# ------------------------------------------------------------- with a query


def test_open_only(test_database_url, fake, alice_id):
    plumber_and_milk(test_database_url, alice_id, fake)
    result = search(test_database_url, alice_id, fake, "plumber", status="open")
    assert "Call the plumber" in titles(result)
    assert "Pay the plumber" not in titles(result)
    assert all(hit.thought.status == "open" for hit in result.hits)


def test_done_thoughts_still_found(test_database_url, fake, alice_id):
    plumber_and_milk(test_database_url, alice_id, fake)
    result = search(test_database_url, alice_id, fake, "oat milk")
    [milk] = [hit for hit in result.hits if hit.thought.title == "Buy oat milk"]
    assert milk.thought.status == "done"
    assert milk.thought.status_changed_at is not None
    # And with no status, the plumber search holds both plumber tasks.
    both = titles(search(test_database_url, alice_id, fake, "plumber"))
    assert {"Call the plumber", "Pay the plumber"} <= set(both)


def test_category_filter(test_database_url, fake, alice_id):
    plumber_and_milk(test_database_url, alice_id, fake)
    result = search(test_database_url, alice_id, fake, "plumber", category="task")
    assert set(titles(result)) == {"Call the plumber", "Pay the plumber"}
    assert all(hit.thought.category == "task" for hit in result.hits)
    # Without the category, the note matches too.
    assert "The plumber said the boiler is old" in titles(
        search(test_database_url, alice_id, fake, "plumber")
    )


# ---------------------------------------------------------------- no query


def test_open_tasks(test_database_url, fake, alice_id):
    plumber_and_milk(test_database_url, alice_id, fake)
    before = calls(fake)
    result = search(test_database_url, alice_id, fake, None, status="open", category="task")
    assert titles(result) == ["Call the plumber"]
    assert result.total == 1
    assert result.words_only is None
    assert calls(fake) == before


def test_newest_filed_first(test_database_url, fake, alice_id):
    url = test_database_url
    task(url, alice_id, fake, "Filed on the first", filed=datetime(2026, 11, 1, 9, tzinfo=UTC))
    task(url, alice_id, fake, "Filed on the third", filed=datetime(2026, 11, 3, 9, tzinfo=UTC))
    task(url, alice_id, fake, "Filed on the second", category="idea",
         filed=datetime(2026, 11, 2, 9, tzinfo=UTC))
    result = search(url, alice_id, fake, None, status="open")
    assert titles(result) == ["Filed on the third", "Filed on the second", "Filed on the first"]
    tasks = search(url, alice_id, fake, None, category="task")
    assert titles(tasks) == ["Filed on the third", "Filed on the first"]


def test_more_than_the_limit(test_database_url, fake, alice_id):
    url = test_database_url
    count = LIMIT + 3
    for day in range(1, count + 1):
        task(url, alice_id, fake, f"Task {day}", filed=datetime(2026, 10, day, 9, tzinfo=UTC))
    task(url, alice_id, fake, "Done task", done=True)
    result = search(url, alice_id, fake, None, status="open", category="task")
    assert len(result.hits) == LIMIT
    assert result.total == count
    assert titles(result) == [f"Task {day}" for day in range(count, count - LIMIT, -1)]


def test_only_the_users_thoughts(test_database_url, fake, alice_id, bob_id):
    url = test_database_url
    task(url, alice_id, fake, "Fix the gate", filed=datetime(2026, 11, 1, 9, tzinfo=UTC))
    task(url, alice_id, fake, "Book the dentist", filed=datetime(2026, 11, 2, 9, tzinfo=UTC))
    # Bob has more matching thoughts than Alice, so a total that counted
    # both would differ.
    task(url, bob_id, fake, "Call the plumber")
    for n in range(4):
        task(url, bob_id, fake, f"Bob task {n}")
    before = calls(fake)

    tasks = search(url, alice_id, fake, None, status="open", category="task")
    assert titles(tasks) == ["Book the dentist", "Fix the gate"]
    assert tasks.total == 2
    assert all(str(hit.thought.user_id) == str(alice_id) for hit in tasks.hits)

    only_open = search(url, alice_id, fake, None, status="open")
    assert titles(only_open) == ["Book the dentist", "Fix the gate"]
    assert only_open.total == 2
    assert calls(fake) == before


def test_no_query_and_no_filter_is_refused_naming_query(test_database_url, fake, alice_id):
    plumber_and_milk(test_database_url, alice_id, fake)
    before = calls(fake)
    for query in (None, "", "  "):
        for options in ({}, {"tags": ["work"]}, {"since": date(2026, 9, 1)},
                        {"status": None, "category": None}, {"status": "", "category": ""}):
            with pytest.raises(ApiError) as refused:
                search(test_database_url, alice_id, fake, query, **options)
            assert refused.value.code == "validation_error"
            assert refused.value.message.startswith("query: ")
    assert calls(fake) == before


# ------------------------------------------------------ filters together


def test_status_category_tags_and_dates_together(test_database_url, fake, alice_id):
    url = test_database_url
    when = {"start": "2026-11-10", "time_zone": "Europe/Oslo"}
    later = {"start": "2026-12-10", "time_zone": "Europe/Oslo"}
    task(url, alice_id, fake, "Plumber visit", tags=["home"], when=when)
    task(url, alice_id, fake, "Plumber bill", tags=["home"], when=when, done=True)
    task(url, alice_id, fake, "Plumber at work", tags=["work"], when=when)
    task(url, alice_id, fake, "Plumber idea", category="idea", tags=["home"], when=when)
    task(url, alice_id, fake, "Plumber in December", tags=["home"], when=later)
    task(url, alice_id, fake, "Plumber undated", tags=["home"])
    options = {
        "status": "open",
        "category": "task",
        "tags": ["home"],
        "dated_from": date(2026, 11, 9),
        "dated_to": date(2026, 11, 15),
    }

    with_query = search(url, alice_id, fake, "plumber", **options)
    assert titles(with_query) == ["Plumber visit"]

    before = calls(fake)
    no_query = search(url, alice_id, fake, None, **options)
    assert titles(no_query) == ["Plumber visit"]
    assert no_query.total == 1
    assert calls(fake) == before


def test_no_query_with_dates_and_a_status_is_in_date_order(test_database_url, fake, alice_id):
    url = test_database_url

    def on(start):
        return {"start": start, "time_zone": "Europe/Oslo"}

    # Filed in the opposite order of their dates.
    task(url, alice_id, fake, "Evening", when=on("2026-11-12T19:00"),
         filed=datetime(2026, 11, 1, tzinfo=UTC))
    task(url, alice_id, fake, "Morning", when=on("2026-11-12T08:30"),
         filed=datetime(2026, 11, 2, tzinfo=UTC))
    task(url, alice_id, fake, "All day", when=on("2026-11-12"),
         filed=datetime(2026, 11, 3, tzinfo=UTC))
    task(url, alice_id, fake, "Day before", when=on("2026-11-11T23:00"),
         filed=datetime(2026, 11, 4, tzinfo=UTC))
    task(url, alice_id, fake, "Done that day", when=on("2026-11-12T10:00"), done=True)
    task(url, alice_id, fake, "Not dated")

    result = search(
        url, alice_id, fake, None, status="open",
        dated_from=date(2026, 11, 11), dated_to=date(2026, 11, 12),
    )

    assert titles(result) == ["Day before", "All day", "Morning", "Evening"]
    assert result.total == 4


def test_no_query_makes_no_provider_call_and_no_backfill(test_database_url, fake, alice_id):
    url = test_database_url
    # The provider fails while storing, so the thought has no entries yet.
    fake.embed_replies.append(api_error(503))
    thought_id = task(url, alice_id, fake, "Call the plumber")
    assert entries(url, thought_id) == {}
    before = calls(fake)

    for options in ({"status": "open"}, {"category": "task"},
                    {"status": "open", "category": "task"}):
        result = search(url, alice_id, fake, None, **options)
        assert titles(result) == ["Call the plumber"]

    assert calls(fake) == before
    assert entries(url, thought_id) == {}
