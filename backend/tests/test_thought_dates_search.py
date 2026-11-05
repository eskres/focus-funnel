"""Search by the thought's own date (thought-dates task 3.1).

Every scenario of the `thought-search` delta. The tag, since, and newest-first
scenarios are also covered, unchanged, in test_thought_search.py.
"""

from datetime import UTC, date, datetime

import pytest

from app.errors import ApiError
from tests.chat_helpers import MODEL_LIST, FakeLLM, api_error, save_key, user_id_for
from tests.test_thought_search import search, set_created, store, titles
from tests.thought_helpers import EMBED_MODEL, entries, models_with_embedding

pytestmark = pytest.mark.postgres


@pytest.fixture
def fake(settings_env) -> FakeLLM:
    settings_env.setenv("EMBEDDING_MODEL", EMBED_MODEL)
    return FakeLLM(models=models_with_embedding(MODEL_LIST)).install()


@pytest.fixture
def alice_id(client, alice, fake):
    save_key(client, alice)
    return user_id_for(client, alice)


def dated(url, user_id, fake, title, summary, start, end=None, **fields):
    when = {"start": start, "end": end, "time_zone": "Europe/Oslo"}
    return store(url, user_id, fake, title, summary, when=when, **fields)


def week(url, user_id, fake):
    """The thought-search delta's week: a trip, a dinner, and a dentist visit later."""
    dated(url, user_id, fake, "Dentist", "Check-up at the dentist.", "2026-10-12T09:00")
    dated(url, user_id, fake, "Dinner with Sam", "Dinner at Sam's place.", "2026-10-02T19:00")
    dated(url, user_id, fake, "Trip to Oslo", "A long weekend away.", "2026-09-30", "2026-10-03")
    store(url, user_id, fake, "Oat milk", "Buy oat milk on the way home.")


def test_tag_filter(test_database_url, fake, alice_id):
    store(test_database_url, alice_id, fake, "Q4 plans", "Ship offline mode first.", tags=["work"])
    store(test_database_url, alice_id, fake, "Holiday plans", "Plans for the trip.", tags=["travel"])
    result = search(test_database_url, alice_id, fake, "plans", tags=["work"])
    assert titles(result) and all("work" in hit.thought.tags for hit in result.hits)


def test_tag_nobody_uses(test_database_url, fake, alice_id):
    week(test_database_url, alice_id, fake)
    fake.embed_requests.clear()
    result = search(
        test_database_url, alice_id, fake, None, tags=["astronomy"],
        dated_from=date(2026, 9, 28), dated_to=date(2026, 10, 4),
    )
    assert result.hits == []
    assert fake.embed_requests == []


def test_since_a_date(test_database_url, fake, alice_id):
    old = store(test_database_url, alice_id, fake, "Old ideas", "Ideas for the garden.")
    new = store(test_database_url, alice_id, fake, "New ideas", "Ideas for the kitchen.")
    set_created(test_database_url, old, datetime(2026, 8, 20, tzinfo=UTC))
    set_created(test_database_url, new, datetime(2026, 9, 3, tzinfo=UTC))
    result = search(test_database_url, alice_id, fake, "ideas", since=date(2026, 9, 1))
    assert titles(result) == ["New ideas"]


def test_newest_first(test_database_url, fake, alice_id):
    ids = [
        store(test_database_url, alice_id, fake, f"Milk {n}", "Buy oat milk " + "milk " * n)
        for n in range(3)
    ]
    for day, thought_id in zip((5, 1, 9), ids):
        set_created(test_database_url, thought_id, datetime(2026, 9, day, tzinfo=UTC))
    result = search(test_database_url, alice_id, fake, "milk", newest_first=True)
    assert titles(result) == ["Milk 2", "Milk 0", "Milk 1"]


def test_what_is_on_this_week(test_database_url, fake, alice_id):
    week(test_database_url, alice_id, fake)
    fake.embed_requests.clear()

    result = search(
        test_database_url, alice_id, fake, None,
        dated_from=date(2026, 9, 28), dated_to=date(2026, 10, 4),
    )

    assert titles(result) == ["Trip to Oslo", "Dinner with Sam"]
    assert result.total == 2
    assert result.words_only is None
    assert fake.embed_requests == []


def test_an_empty_query_with_days_is_the_same_as_none(test_database_url, fake, alice_id):
    week(test_database_url, alice_id, fake)
    fake.embed_requests.clear()
    result = search(
        test_database_url, alice_id, fake, "  ",
        dated_from=date(2026, 9, 28), dated_to=date(2026, 10, 4),
    )
    assert titles(result) == ["Trip to Oslo", "Dinner with Sam"]
    assert fake.embed_requests == []


def test_filed_date_and_thought_date_are_separate(test_database_url, fake, alice_id):
    thought_id = dated(
        test_database_url, alice_id, fake, "Dinner with Sam", "Dinner at Sam's place.",
        "2026-10-02T19:00",
    )
    set_created(test_database_url, thought_id, datetime(2026, 9, 1, 12, tzinfo=UTC))

    by_date = search(
        test_database_url, alice_id, fake, None,
        dated_from=date(2026, 10, 1), dated_to=date(2026, 10, 7),
    )
    assert titles(by_date) == ["Dinner with Sam"]
    filed = search(test_database_url, alice_id, fake, "dinner", since=date(2026, 10, 1))
    assert filed.hits == []
    # Both filters together: filed in September and dated in October.
    both = search(
        test_database_url, alice_id, fake, "dinner", since=date(2026, 9, 1),
        dated_from=date(2026, 10, 1), dated_to=date(2026, 10, 7),
    )
    assert titles(both) == ["Dinner with Sam"]


def test_thought_date_with_a_query(test_database_url, fake, alice_id):
    url = test_database_url
    dated(url, alice_id, fake, "Dinner with Sam", "Dinner at Sam's place.", "2026-10-02T19:00")
    dated(url, alice_id, fake, "Dinner with Ana", "Dinner in town.", "2026-10-20T19:00")
    dated(url, alice_id, fake, "Lunch with Bo", "Lunch at the office.", "2026-10-03T12:00")
    store(url, alice_id, fake, "Dinner ideas", "Try a new pasta dish.")

    result = search(
        url, alice_id, fake, "dinner", dated_from=date(2026, 10, 1), dated_to=date(2026, 10, 7)
    )

    assert titles(result) == ["Dinner with Sam"]
    for hit in result.hits:
        assert "dinner" in hit.thought.title.lower()
        assert date(2026, 10, 1) <= hit.thought.starts_on <= date(2026, 10, 7)


def test_no_query_and_no_thought_date_is_refused_naming_the_query(
    test_database_url, fake, alice_id
):
    week(test_database_url, alice_id, fake)
    fake.embed_requests.clear()
    for query in (None, "", "  "):
        with pytest.raises(ApiError) as refused:
            search(test_database_url, alice_id, fake, query, since=date(2026, 9, 1))
        assert refused.value.code == "validation_error"
        assert refused.value.message.startswith("query: ")
    assert fake.embed_requests == []


def test_only_dated_to(test_database_url, fake, alice_id):
    week(test_database_url, alice_id, fake)
    result = search(test_database_url, alice_id, fake, None, dated_to=date(2026, 10, 2))
    assert titles(result) == ["Trip to Oslo", "Dinner with Sam"]


def test_only_dated_from(test_database_url, fake, alice_id):
    week(test_database_url, alice_id, fake)
    # The trip ends on 3 October, so it overlaps a range that starts that day.
    result = search(test_database_url, alice_id, fake, None, dated_from=date(2026, 10, 3))
    assert titles(result) == ["Trip to Oslo", "Dentist"]


def test_date_order_puts_a_day_with_no_time_first(test_database_url, fake, alice_id):
    url = test_database_url
    dated(url, alice_id, fake, "Evening", "Evening plans.", "2026-10-02T19:00")
    dated(url, alice_id, fake, "Morning", "Morning plans.", "2026-10-02T08:30")
    dated(url, alice_id, fake, "All day", "Plans for the day.", "2026-10-02")
    dated(url, alice_id, fake, "Day before", "Plans the day before.", "2026-10-01T23:00")

    result = search(
        url, alice_id, fake, None, dated_from=date(2026, 10, 1), dated_to=date(2026, 10, 2)
    )

    assert titles(result) == ["Day before", "All day", "Morning", "Evening"]


def test_date_only_search_keeps_the_limit_and_counts_the_rest(test_database_url, fake, alice_id):
    for day in range(1, 13):
        dated(test_database_url, alice_id, fake, f"Day {day}", "Plans.", f"2026-10-{day:02d}")
    result = search(
        test_database_url, alice_id, fake, None,
        dated_from=date(2026, 10, 1), dated_to=date(2026, 10, 31),
    )
    assert titles(result) == [f"Day {day}" for day in range(1, 9)]
    assert result.total == 12


def test_date_only_search_keeps_tags_and_owner(client, test_database_url, fake, alice_id, bob):
    save_key(client, bob, key="nb-bob-key-2222")
    bob_id = user_id_for(client, bob)
    url = test_database_url
    dated(url, alice_id, fake, "Work dinner", "With the team.", "2026-10-02", tags=["work"])
    dated(url, alice_id, fake, "Home dinner", "With family.", "2026-10-02", tags=["home"])
    dated(url, bob_id, fake, "Bob dinner", "With Bob's team.", "2026-10-02", tags=["work"])

    result = search(url, alice_id, fake, None, tags=["work"], dated_from=date(2026, 10, 1))

    assert titles(result) == ["Work dinner"]


def test_date_only_search_makes_no_embedding_call_and_no_backfill(
    test_database_url, fake, alice_id
):
    url = test_database_url
    # The provider fails while storing, so the thought has no entries yet.
    fake.embed_replies.append(api_error(503))
    thought_id = dated(url, alice_id, fake, "Dinner with Sam", "At Sam's.", "2026-10-02T19:00")
    assert entries(url, thought_id) == {}
    fake.embed_requests.clear()

    result = search(url, alice_id, fake, None, dated_from=date(2026, 10, 1))

    assert titles(result) == ["Dinner with Sam"]
    assert fake.embed_requests == []
    assert entries(url, thought_id) == {}
    # A search with a query still fills the entries in, as before.
    search(url, alice_id, fake, "dinner")
    assert entries(url, thought_id) != {}
