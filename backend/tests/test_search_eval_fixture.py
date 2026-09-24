"""The search evaluation set is well-formed (thought-storage task 1.2)."""

from datetime import date

from tests.search_eval import load_eval_set

KINDS = {"exact", "code", "paraphrase", "raw", "filter", "nothing"}


def test_ids_are_unique_and_expected_thoughts_exist():
    thoughts, queries = load_eval_set()
    thought_ids = [thought["id"] for thought in thoughts]
    assert len(thought_ids) == len(set(thought_ids))
    assert len({query["id"] for query in queries}) == len(queries)
    for query in queries:
        assert set(query["expect"]) <= set(thought_ids), query["id"]


def test_every_kind_is_covered():
    _, queries = load_eval_set()
    assert {query["kind"] for query in queries} == KINDS
    assert sum(query["kind"] == "nothing" for query in queries) >= 4


def test_expected_thoughts_pass_their_query_filters():
    thoughts, queries = load_eval_set()
    by_id = {thought["id"]: thought for thought in thoughts}
    for query in queries:
        for expected in query["expect"]:
            thought = by_id[expected]
            if query.get("tags"):
                assert set(query["tags"]) & set(thought["tags"]), query["id"]
            if query.get("since"):
                assert thought["created"] >= query["since"], query["id"]


def test_raw_queries_point_at_thoughts_with_raw_text():
    thoughts, queries = load_eval_set()
    by_id = {thought["id"]: thought for thought in thoughts}
    for query in queries:
        if query["kind"] == "raw":
            assert all(by_id[expected].get("raw_text") for expected in query["expect"])


def test_dates_parse():
    thoughts, _ = load_eval_set()
    assert all(isinstance(thought["created"], date) for thought in thoughts)
