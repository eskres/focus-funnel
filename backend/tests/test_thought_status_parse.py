"""Marks on propose_thought: the schema and parse_proposal() (thought-status task 3.1)."""

import pytest

from app.chat.prompt import (
    ADD_TO_DESCRIPTION,
    CATEGORY_DESCRIPTION,
    DATE_SCHEMA,
    MAX_PARTS,
    NEW_DESCRIPTION,
    TAGS_DESCRIPTION,
    WHEN_CHOICES_DESCRIPTION,
    WHEN_DESCRIPTION,
    propose_tool_schema,
    tools_for,
)
from app.chat.tools import ProposalPart, ToolArgumentError, parse_proposal
from app.thoughts.categories import FIXED_CATEGORIES

CATEGORIES = list(FIXED_CATEGORIES)
NEW = {"title": "Oat milk", "summary": "Buy oat milk.", "tags": ["groceries"], "category": "task"}
MARK_ONLY = "marks[0]: a mark only names a ref; send an addition as its own entry in thoughts"

# The new-thought part as the schema had it before this change.
PART_BEFORE = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "A short title."},
        "summary": {
            "type": "string",
            "description": (
                "A short summary of the key findings or the item, with the points "
                "the user agreed with."
            ),
        },
        "tags": {"type": "array", "items": {"type": "string"}, "description": TAGS_DESCRIPTION},
        "category": {"type": "string", "enum": CATEGORIES, "description": CATEGORY_DESCRIPTION},
        "when": {**DATE_SCHEMA, "description": WHEN_DESCRIPTION},
        "when_choices": {
            "type": "array",
            "items": DATE_SCHEMA,
            "minItems": 2,
            "maxItems": 2,
            "description": WHEN_CHOICES_DESCRIPTION,
        },
        "add_to": {"type": "string", "description": ADD_TO_DESCRIPTION},
        "new": {"type": "boolean", "description": NEW_DESCRIPTION},
    },
    "required": ["title", "summary", "tags", "category"],
}


def parse(arguments, **options):
    return parse_proposal(arguments, CATEGORIES, **options)


def mark(ref: str) -> ProposalPart:
    return ProposalPart(title="", summary="", tags=[], category=None, mark=ref)


def refused(arguments, **options) -> str:
    with pytest.raises(ToolArgumentError) as error:
        parse(arguments, **options)
    return str(error.value)


# --- the schema ---


def test_the_part_object_is_as_before_and_thoughts_is_still_required():
    parameters = propose_tool_schema(CATEGORIES, [])["function"]["parameters"]
    thoughts = parameters["properties"]["thoughts"]
    assert thoughts["items"] == PART_BEFORE
    assert thoughts["items"]["required"] == ["title", "summary", "tags", "category"]
    assert parameters["required"] == ["thoughts"]
    assert "minItems" not in thoughts
    assert thoughts["maxItems"] == MAX_PARTS
    marks = parameters["properties"]["marks"]
    assert marks["items"]["properties"] == {"ref": marks["items"]["properties"]["ref"]}
    assert marks["items"]["required"] == ["ref"]


def test_the_schema_without_marks_is_the_full_schema_less_marks():
    full = propose_tool_schema(CATEGORIES, ["work"])
    offered = propose_tool_schema(CATEGORIES, ["work"], marks=False)
    assert "marks" not in offered["function"]["parameters"]["properties"]
    assert offered["function"]["parameters"]["properties"] == {
        key: value
        for key, value in full["function"]["parameters"]["properties"].items()
        if key != "marks"
    }
    assert offered["function"]["parameters"]["required"] == full["function"]["parameters"]["required"]
    assert offered["function"]["name"] == full["function"]["name"]
    assert tools_for(CATEGORIES, [], marks=False)[1] == propose_tool_schema(CATEGORIES, [], marks=False)


# --- parse_proposal in a turn ---


def test_an_empty_thoughts_list_and_one_mark_is_one_mark():
    assert parse({"thoughts": [], "marks": [{"ref": "T3"}]}) == [mark("T3")]


def test_marks_with_no_thoughts_key_parse_as_the_same_mark():
    assert parse({"marks": [{"ref": "T3"}]}) == [mark("T3")]


def test_the_same_ref_twice_is_one_mark_and_not_refused():
    assert parse({"marks": [{"ref": "T3"}, {"ref": "T3"}]}) == [mark("T3")]
    assert parse({"marks": [{"ref": "T3"}, {"ref": " t3 "}]}) == [mark("T3")]


def test_a_mark_is_stored_by_its_ref_until_resolved():
    assert mark("T3").as_dict() == {"mark_ref": "T3"}


def test_a_top_level_title_still_parses_as_one_new_part():
    [part] = parse(NEW)
    assert (part.title, part.mark) == ("Oat milk", None)


def test_new_parts_come_first_then_the_marks():
    parts = parse({"marks": [{"ref": "T2"}], "thoughts": [NEW]})
    assert [(part.title, part.mark) for part in parts] == [("Oat milk", None), ("", "T2")]


@pytest.mark.parametrize("arguments", [{"thoughts": [], "marks": []}, {"thoughts": []}, {}])
def test_a_call_with_no_entry_is_refused(arguments):
    assert refused(arguments) == "propose_thought needs at least one entry in thoughts or marks"


def test_more_than_max_parts_in_both_together_is_refused():
    thoughts = [{**NEW, "title": f"Thing {n}"} for n in range(MAX_PARTS)]
    assert len(parse({"thoughts": thoughts})) == MAX_PARTS
    message = refused({"thoughts": thoughts, "marks": [{"ref": "T1"}]})
    assert str(MAX_PARTS) in message and "thoughts and marks" in message
    marks = [{"ref": f"T{n}"} for n in range(1, MAX_PARTS + 2)]
    assert "thoughts and marks" in refused({"marks": marks})


@pytest.mark.parametrize("item", [{}, {"ref": ""}, {"ref": 3}])
def test_a_mark_with_no_ref_is_refused_naming_it(item):
    assert refused({"thoughts": [], "marks": [item]}).startswith("marks[0].ref")


@pytest.mark.parametrize(
    "item",
    [
        {"ref": "T1", "add_to": "T1"},
        {"ref": "T1", "new": True},
        {"ref": "T1", "summary": "He came on Tuesday."},
        {"ref": "T1", "when": {"start": "2026-11-10"}},
        {"ref": "T1", "when_choices": [{"start": "2026-11-10"}, {"start": "2026-11-17"}]},
    ],
)
def test_a_mark_that_carries_more_than_a_ref_is_refused(item):
    assert refused({"thoughts": [], "marks": [item]}) == MARK_ONLY


def test_an_entry_in_thoughts_with_no_summary_is_still_refused():
    message = refused({"thoughts": [{"title": "Oat milk", "tags": []}], "marks": [{"ref": "T1"}]})
    assert message.startswith("thoughts[0].summary")


# --- parse_proposal in the offer ---


@pytest.mark.parametrize(
    "marks",
    [
        [{"ref": "T1", "summary": "Called him."}],
        [{"summary": "no ref at all"}],
        "not even a list",
    ],
)
def test_the_offer_reads_the_new_thoughts_and_ignores_any_mark(marks):
    parts = parse({"thoughts": [NEW], "marks": marks}, offered=True)
    assert [(part.title, part.mark) for part in parts] == [("Oat milk", None)]


def test_the_offer_ignores_marks_past_max_parts():
    thoughts = [{**NEW, "title": f"Thing {n}"} for n in range(MAX_PARTS)]
    parts = parse({"thoughts": thoughts, "marks": [{"ref": "T1"}]}, offered=True)
    assert len(parts) == MAX_PARTS and all(part.mark is None for part in parts)


def test_the_offer_with_only_a_mark_gives_no_part():
    assert parse({"thoughts": [], "marks": [{"ref": "T1"}]}, offered=True) == []
    assert parse({"marks": [{"ref": "T1"}]}, offered=True) == []
