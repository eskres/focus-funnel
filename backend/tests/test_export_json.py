"""The JSON writer (thought-export task 2.2, design decision 4)."""

import json
import uuid
from datetime import UTC, datetime

from app.routers.thoughts import ThoughtOut
from app.thoughts.export import json_chunks

EXPORTED = datetime(2026, 11, 5, 14, 3, 0, tzinfo=UTC)


def thought(title: str) -> ThoughtOut:
    return ThoughtOut(
        id=uuid.uuid4(),
        title=title,
        summary=f"About {title}.",
        tags=["a"],
        category=None,
        raw_text="line one\nline two",
        when=None,
        created_at=datetime(2026, 10, 1, 9, 12, tzinfo=UTC),
        updated_at=datetime(2026, 10, 1, 9, 12, tzinfo=UTC),
        status="open",
        status_changed_at=None,
        origin=None,
        additions=[],
    )


async def batches_of(*batches):
    for batch in batches:
        yield batch


async def written(*batches) -> str:
    return "".join(
        [chunk async for chunk in json_chunks(batches_of(*batches), EXPORTED)]
    )


def thought_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith('{"id"')]


async def test_one_document_with_the_thoughts_in_order_and_the_count():
    t1, t2, t3 = thought("one"), thought("two"), thought("three")
    text = await written([t1, t2], [t3])
    document = json.loads(text)
    assert document["format"] == "focus-funnel-thoughts"
    assert document["version"] == 1
    assert document["exported_at"] == "2026-11-05T14:03:00Z"
    assert [item["id"] for item in document["thoughts"]] == [
        str(t.id) for t in (t1, t2, t3)
    ]
    assert document["thoughts"][0] == json.loads(t1.model_dump_json())
    assert document["count"] == 3
    assert list(document) == ["format", "version", "exported_at", "thoughts", "count"]
    # Each thought sits on its own line.
    lines = thought_lines(text)
    assert len(lines) == 3
    for line, item in zip(lines, (t1, t2, t3), strict=True):
        assert json.loads(line.rstrip(",")) == json.loads(item.model_dump_json())


async def test_empty_batches_write_nothing():
    t1, t2, t3 = thought("one"), thought("two"), thought("three")
    document = json.loads(await written([t1, t2], [], [t3], []))
    assert [item["title"] for item in document["thoughts"]] == ["one", "two", "three"]
    assert document["count"] == 3
    text = await written([], [t1])
    document = json.loads(text)
    assert [item["title"] for item in document["thoughts"]] == ["one"]
    assert document["count"] == 1
    assert len(thought_lines(text)) == 1


async def test_no_batches():
    text = await written()
    assert '"thoughts":[]' in text
    assert '"count":0' in text
    assert json.loads(text)["thoughts"] == []


async def test_the_opening_line_comes_before_the_first_batch_is_asked_for():
    asked: list[str] = []

    async def recording():
        asked.append("asked")
        yield [thought("one")]

    chunks = json_chunks(recording(), EXPORTED)
    first = await anext(chunks)
    assert asked == []
    assert first.startswith('{"format":"focus-funnel-thoughts","version":1,')
    rest = [chunk async for chunk in chunks]
    assert asked == ["asked"]
    assert json.loads(first + "".join(rest))["count"] == 1
