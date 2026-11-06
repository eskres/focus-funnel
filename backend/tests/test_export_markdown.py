"""The Markdown writer (thought-export task 2.3, design decision 5).

The golden file pins three sections: the "Everything a thought has" thought,
a plain thought, and a thought whose summary holds list, rule, heading, and
indented lines. Set EXPORT_WRITE_GOLDEN=1 to write it again after a
deliberate change, then read the diff.
"""

import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.routers.thoughts import AdditionOut, OriginOut, ThoughtOut
from app.thoughts.export import markdown_chunks

GOLDEN = Path(__file__).parent / "fixtures" / "export" / "plumber.md"
EXPORTED = datetime(2026, 11, 5, 14, 3, tzinfo=UTC)

PLUMBER_ID = uuid.UUID("9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a")
WEEKEND_ID = uuid.UUID("1b2c4e6a-3f0d-4c1e-9a57-2d8b6e0f4a13")
ORIGIN_PROPOSAL = uuid.UUID("3c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f")
PLUMBER_CHAT_ID = uuid.UUID("5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9")
ADDED_PROPOSAL = uuid.UUID("7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d")
UNDONE_PROPOSAL = uuid.UUID("8b9c0d1e-2f3a-4b4c-9d5e-6f7a8b9c0d1e")
PLAIN_ID = uuid.UUID("2a3b4c5d-6e7f-4a8b-9c0d-1e2f3a4b5c6d")
LINES_ID = uuid.UUID("4c5d6e7f-8a9b-4c0d-8e1f-2a3b4c5d6e7f")

# The third thought's summary: each line would render as Markdown if written as it is.
LINES_SUMMARY = "\n".join(
    [
        "- item",
        "+ item",
        "1. step",
        "2) step",
        "---",
        "===",
        "x",
        "===",
        "   - item",
        "  1. step",
        "   ---",
        "x",
        "   ===",
        "# Other",
        "",
        "    <b>x</b>",
        "\t<b>x</b>",
        "   three spaces",
        "see https://evil.example/a?x=1_y",
    ]
)


def thought(**fields) -> ThoughtOut:
    values = {
        "id": uuid.uuid4(),
        "title": "A thought",
        "summary": "About it.",
        "tags": [],
        "category": None,
        "raw_text": None,
        "when": None,
        "created_at": datetime(2026, 10, 2, 8, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 2, 8, 0, tzinfo=UTC),
        "status": "open",
        "status_changed_at": None,
        "origin": None,
        "additions": [],
        **fields,
    }
    return ThoughtOut(**values)


def plumber(**fields) -> ThoughtOut:
    return thought(
        **{
            "id": PLUMBER_ID,
            "title": "Call the plumber",
            "summary": "Call the plumber about the leaking kitchen tap.",
            "tags": ["home", "weekend plans"],
            "category": "task",
            "raw_text": "the kitchen tap leaks again, call the plumber on monday\n\nhe comes at nine",
            "when": {"start": "2026-11-09", "end": None, "time_zone": "Europe/Oslo"},
            "created_at": datetime(2026, 10, 1, 9, 12, tzinfo=UTC),
            "updated_at": datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
            "status": "done",
            "status_changed_at": datetime(2026, 11, 4, 10, 15, tzinfo=UTC),
            "origin": OriginOut(
                conversation_id=WEEKEND_ID,
                conversation_title="Weekend plans",
                archived=True,
                proposal_id=ORIGIN_PROPOSAL,
                proposed_at=datetime(2026, 10, 1, 9, 10, tzinfo=UTC),
            ),
            "additions": [
                AdditionOut(
                    id=uuid.UUID("6f7a8b9c-0d1e-4f2a-b3c4-d5e6f7a8b9c0"),
                    added_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
                    undone=False,
                    conversation_id=PLUMBER_CHAT_ID,
                    conversation_title="Plumber chat",
                    proposal_id=ADDED_PROPOSAL,
                ),
                AdditionOut(
                    id=uuid.UUID("0d1e2f3a-4b5c-4d6e-8f7a-8b9c0d1e2f3a"),
                    added_at=datetime(2026, 10, 11, 9, 0, tzinfo=UTC),
                    undone=True,
                    conversation_id=PLUMBER_CHAT_ID,
                    conversation_title="Plumber chat",
                    proposal_id=UNDONE_PROPOSAL,
                ),
            ],
            **fields,
        }
    )


def plain() -> ThoughtOut:
    return thought(id=PLAIN_ID, title="Buy oat milk", summary="Buy oat milk tomorrow.")


def lines_thought() -> ThoughtOut:
    return thought(
        id=LINES_ID,
        title="Notes with Markdown in them",
        summary=LINES_SUMMARY,
        status="open",
        status_changed_at=datetime(2026, 11, 4, 10, 15, tzinfo=UTC),
        created_at=datetime(2026, 10, 3, 7, 30, tzinfo=UTC),
        updated_at=datetime(2026, 11, 4, 10, 15, tzinfo=UTC),
    )


async def batches_of(*batches):
    for batch in batches:
        yield batch


async def md(*batches) -> str:
    return "".join(
        [chunk async for chunk in markdown_chunks(batches_of(*batches), EXPORTED)]
    )


async def one(item: ThoughtOut) -> str:
    return await md([item])


FENCE = re.compile(r"^(`{3,})text$")


def outside_code(text: str) -> list[str]:
    """The lines outside fenced code blocks, split as line tools split them."""
    lines: list[str] = []
    fence = None
    for line in text.splitlines():
        if fence is not None:
            if line == fence:
                fence = None
            continue
        opening = FENCE.match(line)
        if opening:
            fence = opening.group(1)
            continue
        lines.append(line)
    assert fence is None, "a code block does not end"
    return lines


def section_of(text: str, title: str) -> list[str]:
    """The lines of one thought's section, from its heading to its rule."""
    lines = text.split("\n")
    start = lines.index(f"## {title}")
    end = lines.index("---", start)
    return lines[start:end]


def raw_block(text: str) -> tuple[str, str]:
    """The fence and what lies between the opening fence line and the closing
    fence, minus the last \\n."""
    opening = re.search(r"\n(`{3,})text\n", text)
    fence = opening.group(1)
    body_start = opening.end()
    close = text.index("\n" + fence + "\n", body_start - 1)
    inner = text[body_start : close + 1]
    assert inner.endswith("\n")
    return fence, inner[:-1]


def quote_lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.startswith(">")]


# The golden file.


async def test_the_golden_file():
    text = await md([plumber(), plain()], [lines_thought()])
    if os.environ.get("EXPORT_WRITE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(text, encoding="utf-8", newline="")
    assert text == GOLDEN.read_text(encoding="utf-8", newline="")


async def test_the_plumber_section():
    lines = section_of(GOLDEN.read_text(encoding="utf-8"), "Call the plumber")
    assert f"- ID: {PLUMBER_ID}" in lines
    [origin] = [line for line in lines if line.startswith("- From: ")]
    assert origin == (
        f"- From: Weekend plans (archived), proposed 2026-10-01 09:10 UTC, "
        f"conversation {WEEKEND_ID}, proposal {ORIGIN_PROPOSAL}"
    )
    assert (
        f"- 2026-10-12 09:00 UTC from Plumber chat, conversation {PLUMBER_CHAT_ID}, "
        f"proposal {ADDED_PROPOSAL}"
    ) in lines
    assert (
        f"- 2026-10-11 09:00 UTC from Plumber chat, conversation {PLUMBER_CHAT_ID}, "
        f"proposal {UNDONE_PROPOSAL} (undone)"
    ) in lines
    assert "- Tags: `#home`, `#weekend plans`" in lines
    assert "- Status: done, marked done 2026-11-04 10:15 UTC" in lines
    assert "- Date: 2026-11-09 (Europe/Oslo)" in lines
    assert "> Call the plumber about the leaking kitchen tap." in lines


async def test_the_plain_section():
    lines = section_of(GOLDEN.read_text(encoding="utf-8"), "Buy oat milk")
    assert "- Status: open" in lines
    for name in ("Category", "Tags", "Date", "From"):
        assert not any(line.startswith(f"- {name}:") for line in lines), name
    assert "### Raw text" not in lines and "### Additions" not in lines
    assert "> Buy oat milk tomorrow." in lines


async def test_a_reopened_thought():
    lines = section_of(
        GOLDEN.read_text(encoding="utf-8"), "Notes with Markdown in them"
    )
    assert "- Status: open, reopened 2026-11-04 10:15 UTC" in lines


async def test_a_comma_inside_a_tag():
    text = await one(thought(tags=["a,b", "c"]))
    assert "- Tags: `#a,b`, `#c`" in text.split("\n")


async def test_a_tag_holding_a_comma_and_a_hash_reads_as_one_tag():
    """`a, #b` is one tag and `a`, `b` are two: the lines differ, and each
    code span holds exactly one tag as stored (design decision 31)."""
    one_tag = tags_line(await one(thought(tags=["a, #b"])))
    two_tags = tags_line(await one(thought(tags=["a", "b"])))
    assert one_tag == "- Tags: `#a, #b`"
    assert two_tags == "- Tags: `#a`, `#b`"
    assert code_spans(one_tag) == ["#a, #b"]
    assert code_spans(two_tags) == ["#a", "#b"]


@pytest.mark.parametrize(
    "tag, written",
    [
        ("a`b", "``#a`b``"),
        ("a`b`", "`` #a`b` ``"),
        ("x``y", "```#x``y```"),
        ("<b>", "`#<b>`"),
        ("a\\_b", "`#a\\_b`"),
    ],
)
async def test_a_tag_is_one_code_span_whatever_it_holds(tag, written):
    line = tags_line(await one(thought(tags=[tag])))
    assert line == f"- Tags: {written}"
    assert code_spans(line) == ["#" + tag]


def tags_line(text: str) -> str:
    [line] = [line for line in text.split("\n") if line.startswith("- Tags: ")]
    return line


CODE_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")


def code_spans(line: str) -> list[str]:
    """The text a CommonMark viewer shows for each code span in the line: one
    space dropped from each end when both ends have one."""
    spans = []
    for found in CODE_SPAN.finditer(line):
        body = found.group(2)
        if body.startswith(" ") and body.endswith(" ") and body.strip(" "):
            body = body[1:-1]
        spans.append(body)
    return spans


# The raw text.


@pytest.mark.parametrize(
    "raw, fence",
    [
        ("before\n```\ninside\n```\nafter", "````"),
        ("before\n````\ninside\n````", "`````"),
    ],
)
async def test_the_fence_is_longer_than_any_run_of_backticks(raw, fence):
    found, inner = raw_block(await one(thought(raw_text=raw)))
    assert found == fence
    assert inner == raw


@pytest.mark.parametrize(
    "raw",
    [
        "before\n```\ninside\n```\nafter",
        "before\n````\ninside\n````",
        "one\r\ntwo\r\nthree",
        "one\n\ntwo",
        "one\rtwo",
        # Writer-only cases: a stored raw text is stripped.
        "ends with a newline\n",
        "ends with a crlf\r\n",
        "\nstarts with a blank line",
    ],
)
async def test_the_raw_text_comes_back_exactly(raw):
    text = await one(thought(raw_text=raw))
    _, inner = raw_block(text)
    assert inner == raw


# Data is shown, never rendered.


async def test_markdown_and_html_in_data_are_escaped():
    item = thought(
        title="<b>Hi</b>",
        summary="![x](https://evil.example/a) <img src=x>",
        tags=["<b>"],
        category="*x*",
        origin=OriginOut(
            conversation_id=WEEKEND_ID,
            conversation_title="<img src=x>",
            archived=False,
            proposal_id=ORIGIN_PROPOSAL,
            proposed_at=datetime(2026, 10, 1, 9, 10, tzinfo=UTC),
        ),
        additions=[
            AdditionOut(
                id=uuid.uuid4(),
                added_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
                undone=False,
                conversation_id=PLUMBER_CHAT_ID,
                conversation_title="[a](https://evil.example)",
                proposal_id=ADDED_PROPOSAL,
            )
        ],
    )
    text = await one(item)
    lines = text.split("\n")
    assert "## \\<b\\>Hi\\</b\\>" in lines
    assert "> \\!\\[x\\](https://evil.example/a) \\<img src=x\\>" in lines
    assert "- Tags: `#<b>`" in lines
    assert "- Category: \\*x\\*" in lines
    assert any(line.startswith("- From: \\<img src=x\\>, proposed ") for line in lines)
    assert any(
        " from \\[a\\](https://evil.example), conversation " in line for line in lines
    )
    assert_nothing_renders(text)


def assert_nothing_renders(text: str) -> None:
    """Outside code blocks and code spans, every `![`, `<img`, `<b>`, and `](`
    follows an odd run of backslashes: an even run is backslashes shown as
    text, and the marker after it would render."""
    for line in outside_code(text):
        line = CODE_SPAN.sub("", line)
        for marker in ("![", "<img", "<b>", "]("):
            for found in re.finditer(re.escape(marker), line):
                before = line[: found.start()]
                run = len(before) - len(before.rstrip("\\"))
                assert run % 2 == 1, (marker, line)


@pytest.mark.parametrize(
    "line",
    [
        "> <img src=x>",
        "> \\\\<img src=x>",
        "> \\\\\\\\![x](y)",
        "## a \\\\<b>",
        "- From: \\\\[a](https://evil.example), proposed",
    ],
)
def test_the_check_catches_a_marker_after_an_even_run_of_backslashes(line):
    with pytest.raises(AssertionError):
        assert_nothing_renders(line + "\n")


@pytest.mark.parametrize("char", list("\\`*_[]<>!#&~|"))
async def test_each_listed_character_is_escaped_outside_an_address(char):
    text = await one(thought(title=f"a{char}b", summary=f"a{char}b"))
    lines = text.split("\n")
    assert f"## a\\{char}b" in lines
    assert f"> a\\{char}b" in lines


async def test_a_backslash_in_data_is_escaped_before_markup():
    """A backslash in data is itself escaped, so it cannot escape the
    backslash the writer puts before `<`, `[`, or `!` (design decision 5)."""
    item = thought(
        title="\\<b>Hi</b>",
        summary="\\<img src=x onerror=alert(1)>\n\\[a](https://evil.example) \\![x](https://evil.example/i.png)",
        category="\\\\<b>",
        tags=["\\<b>"],
    )
    text = await one(item)
    lines = text.split("\n")
    assert "## \\\\\\<b\\>Hi\\</b\\>" in lines
    assert "> \\\\\\<img src=x onerror=alert(1)\\>" in lines
    assert (
        "> \\\\\\[a\\](https://evil.example) \\\\\\!\\[x\\](https://evil.example/i.png)"
        in lines
    )
    assert "- Category: \\\\\\\\\\<b\\>" in lines
    assert "- Tags: `#\\<b>`" in lines
    assert_nothing_renders(text)


async def test_the_golden_file_renders_nothing_from_data():
    assert_nothing_renders(GOLDEN.read_text(encoding="utf-8"))


async def test_list_rule_and_heading_lines_in_a_summary():
    quoted = quote_lines(GOLDEN.read_text(encoding="utf-8"))
    expected = [
        "> \\- item",
        "> \\+ item",
        "> 1\\. step",
        "> 2\\) step",
        "> \\---",
        "> \\===",
        "> x",
        "> \\===",
        ">    \\- item",
        ">   1\\. step",
        ">    \\---",
        "> x",
        ">    \\===",
        "> \\# Other",
        ">",
        "> &#32;   \\<b\\>x\\</b\\>",
        "> &#9;\\<b\\>x\\</b\\>",
        ">    three spaces",
        "> see https://evil.example/a?x=1_y",
    ]
    start = quoted.index("> \\- item")
    assert quoted[start : start + len(expected)] == expected


WRITER_LINE = re.compile(
    r"^- (Status|Category|Tags|Date|Filed|Changed|From|ID): "
    r"|^- \d{4}-\d\d-\d\d \d\d:\d\d UTC from "
)
UNESCAPED_START = re.compile(r"^([-+=]|\d+[.)])")


def assert_no_unescaped_line_starts(text: str) -> None:
    for line in outside_code(text):
        if line == "---" or WRITER_LINE.match(line):
            continue
        body = line[2:] if line.startswith("> ") else line
        body = body.lstrip(" \t")
        assert not UNESCAPED_START.match(body), line


async def test_no_data_line_starts_a_list_rule_or_heading():
    assert_no_unescaped_line_starts(GOLDEN.read_text(encoding="utf-8"))


async def test_a_bare_address_is_left_as_it_is():
    text = await one(thought(summary="see https://evil.example/a?x=1_y"))
    assert "> see https://evil.example/a?x=1_y" in text.split("\n")
    for marker in ("![", "<img", "]("):
        assert marker not in text


@pytest.mark.parametrize(
    "summary, line",
    [
        # Characters that are plain text in CommonMark stay bare inside an
        # address, so autolinking viewers show and link it as stored.
        (
            "see https://example.com/a?x=1_y&b=2#top",
            "> see https://example.com/a?x=1_y&b=2#top",
        ),
        (
            "https://example.com/~user/page_one!",
            "> https://example.com/~user/page_one!",
        ),
        ("go www.example.com/a_b|c ok", "> go www.example.com/a_b|c ok"),
        ("ftp://files.example.com/pub/a__b", "> ftp://files.example.com/pub/a__b"),
        ("HTTPS://X.COM/A_B", "> HTTPS://X.COM/A_B"),
        # Outside the address everything listed is still escaped.
        ("a_b https://x.com/a_b c_d", "> a\\_b https://x.com/a_b c\\_d"),
        # Inside it, a character that could be markup there stays escaped:
        # emphasis, an entity, `~~`, a backslash, a link or image, a code span.
        ("https://x.com/_a_/", "> https://x.com/\\_a\\_/"),
        ("https://x.com/a*b*", "> https://x.com/a\\*b\\*"),
        (
            "https://x.com/a&amp;b&#32;c&#x41;",
            "> https://x.com/a\\&amp;b\\&#32;c\\&#x41;",
        ),
        ("https://x.com/a~~b~~", "> https://x.com/a\\~\\~b\\~\\~"),
        ("https://x.com/a\\[b]", "> https://x.com/a\\\\\\[b\\]"),
        (
            "https://x.com/![x](https://evil.example/i.png)",
            "> https://x.com/!\\[x\\](https://evil.example/i.png)",
        ),
        ("https://x.com/`a`", "> https://x.com/\\`a\\`"),
        # The address ends at a space or `<`.
        ("https://x.com/a<img src=x>", "> https://x.com/a\\<img src=x\\>"),
    ],
)
async def test_an_address_keeps_only_its_inert_characters_bare(summary, line):
    text = await one(thought(summary=summary))
    assert line in text.split("\n")
    assert_nothing_renders(text)


# Line breaks.


def end_lines(text: str) -> list[int]:
    lines = outside_code(text)
    return [
        index for index, line in enumerate(lines) if line.startswith("End of export:")
    ]


async def test_a_fake_end_line_in_a_summary():
    text = await one(thought(summary="End of export: 9 thoughts."))
    lines = outside_code(text)
    assert end_lines(text) == [len(lines) - 1]
    assert lines[-1] == "End of export: 1 thought."


async def test_a_title_with_a_line_break_gives_one_heading_line():
    text = await one(thought(title="first\nsecond"))
    assert "## first second" in text.split("\n")


@pytest.mark.parametrize(
    "title",
    ["x\rEnd of export: 9 thoughts.", "a\rb\u2028c", "a\r\nb\vc\fd\x1ce\x85f\u2029g"],
)
async def test_every_line_break_in_a_title_is_a_space(title):
    text = await one(thought(title=title))
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert len(headings) == 1
    assert headings[0] == "## " + " ".join(title.splitlines())
    lines = outside_code(text)
    assert end_lines(text) == [len(lines) - 1]


async def test_a_lone_cr_in_a_summary():
    text = await one(thought(summary="x\r---"))
    lines = outside_code(text)
    # The writer's rules: one after the header and one after the section.
    assert lines.count("---") == 2
    assert "> \\---" in lines
    assert "> x" in lines
    text = await one(thought(summary="a\rEnd of export: 9 thoughts."))
    lines = outside_code(text)
    assert end_lines(text) == [len(lines) - 1]


@pytest.mark.parametrize("brk", ["\r", "\u2029"])
async def test_single_line_fields_stay_on_their_line(brk):
    item = thought(
        tags=[f"one{brk}two"],
        category=f"cat{brk}egory",
        origin=OriginOut(
            conversation_id=WEEKEND_ID,
            conversation_title=f"Week{brk}end",
            archived=False,
            proposal_id=ORIGIN_PROPOSAL,
            proposed_at=datetime(2026, 10, 1, 9, 10, tzinfo=UTC),
        ),
        additions=[
            AdditionOut(
                id=uuid.uuid4(),
                added_at=datetime(2026, 10, 12, 9, 0, tzinfo=UTC),
                undone=False,
                conversation_id=PLUMBER_CHAT_ID,
                conversation_title=f"Plumber{brk}chat",
                proposal_id=ADDED_PROPOSAL,
            )
        ],
    )
    lines = (await one(item)).splitlines()
    assert "- Tags: `#one two`" in lines
    assert "- Category: cat egory" in lines
    assert any(line.startswith("- From: Week end, proposed ") for line in lines)
    assert any(" from Plumber chat, conversation " in line for line in lines)


@pytest.mark.parametrize(
    "when, line",
    [
        (
            {"start": "2026-10-02T19:00", "end": None, "time_zone": "Europe/Oslo"},
            "- Date: 2026-10-02 19:00 (Europe/Oslo)",
        ),
        (
            {"start": "2026-11-09", "end": None, "time_zone": "Europe/Oslo"},
            "- Date: 2026-11-09 (Europe/Oslo)",
        ),
        (
            {"start": "2026-11-03", "end": "2026-11-06", "time_zone": "Europe/Oslo"},
            "- Date: 2026-11-03 to 2026-11-06 (Europe/Oslo)",
        ),
        (
            {
                "start": "2026-10-02T19:00",
                "end": "2026-10-02T21:00",
                "time_zone": "UTC",
            },
            "- Date: 2026-10-02 19:00 to 2026-10-02 21:00 (UTC)",
        ),
    ],
)
async def test_dates(when, line):
    assert line in (await one(thought(when=when))).split("\n")


async def test_times_are_utc_to_the_minute():
    naive = thought(
        created_at=datetime(2026, 10, 2, 8, 0, 59),
        updated_at=datetime(2026, 10, 3, 1, 2),
    )
    lines = (await one(naive)).split("\n")
    assert "- Filed: 2026-10-02 08:00 UTC" in lines
    assert "- Changed: 2026-10-03 01:02 UTC" in lines


# Sections and the end.


async def test_empty_batches_write_nothing():
    t1, t2, t3 = thought(title="one"), thought(title="two"), thought(title="three")
    text = await md([t1, t2], [], [t3], [])
    lines = text.split("\n")
    headings = [index for index, line in enumerate(lines) if line.startswith("## ")]
    assert [lines[index] for index in headings] == ["## one", "## two", "## three"]
    rules = [index for index, line in enumerate(lines) if line == "---"]
    # One after the header, then one after each section.
    assert len(rules) == 4
    assert (
        rules[0]
        < headings[0]
        < rules[1]
        < headings[1]
        < rules[2]
        < headings[2]
        < rules[3]
    )
    assert "---\n\n---" not in text
    assert text.endswith("---\n\nEnd of export: 3 thoughts.\n")


async def test_the_end_line():
    assert (await one(thought())).splitlines()[-1] == "End of export: 1 thought."
    three = await md([thought(), thought(), thought()])
    assert three.splitlines()[-1] == "End of export: 3 thoughts."


async def test_no_thoughts():
    text = await md()
    assert text == (
        "# Focus Funnel thoughts\n\nExported 2026-11-05 14:03 UTC.\n\n---\n\n"
        "No thoughts.\n\n---\n\nEnd of export: 0 thoughts.\n"
    )
