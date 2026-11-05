"""The raw text rule for additions (thought-appending task 1.3, design decision 8)."""

import random
from datetime import date

import pytest

from app.chat.raw_text import (
    LEFT_OUT,
    Block,
    RawBlocks,
    added_texts,
    extend_raw_text,
    join_blocks,
    split_blocks,
)
from app.models import Message
from app.thoughts.store import MAX_RAW_TEXT, check_fields

DAY = date(2026, 9, 26)
LATER = date(2026, 9, 27)


def messages(*contents: tuple[str, str]) -> list[Message]:
    return [
        Message(position=position, role=role, content=content)
        for position, (role, content) in enumerate(contents)
    ]


CHAT = messages(
    ("user", "I need a new bike lock."),  # 0: filed with the thought
    ("assistant", "Noted."),
    ("user", "/push Red or black, I am not sure."),  # 2
    ("assistant", "Both are fine."),
    ("user", "Under 30 euros, please."),  # 4
    ("tool", "x"),
)


def add(raw_text, from_position, to_position, held_to, day=DAY, chat=CHAT):
    texts = added_texts(chat, from_position=from_position, to_position=to_position, held_to=held_to)
    return extend_raw_text(raw_text, texts, day)


def test_a_plain_append_has_the_dated_separator_and_the_messages():
    raw = add("I need a new bike lock.", 2, 4, held_to=0)
    assert raw == (
        "I need a new bike lock."
        "\n\n--- added 2026-09-26 ---\n\n"
        "Red or black, I am not sure.\n\nUnder 30 euros, please."
    )
    assert split_blocks(raw) == RawBlocks(
        "I need a new bike lock.",
        [Block("2026-09-26", "Red or black, I am not sure.\n\nUnder 30 euros, please.")],
    )


def test_no_repeat_when_two_additions_cover_the_same_messages():
    first = add("I need a new bike lock.", 2, 4, held_to=0)
    # The second proposal covers the same messages; the thought holds up to 4.
    second = add(first, 2, 4, held_to=4, day=LATER)
    assert second == first
    for text in ("Red or black", "Under 30 euros"):
        assert second.count(text) == 1


def test_only_the_messages_the_thought_does_not_hold_are_added():
    chat = [*CHAT, Message(position=6, role="user", content="Got the red one.")]
    first = add("I need a new bike lock.", 2, 4, held_to=0, chat=chat)
    second = add(first, 2, 6, held_to=4, day=LATER, chat=chat)
    assert second == first + "\n\n--- added 2026-09-27 ---\n\nGot the red one."


def test_no_change_when_no_message_is_left():
    assert add("I need a new bike lock.", 2, 4, held_to=4) == "I need a new bike lock."
    assert add(None, 2, 4, held_to=4) is None
    assert extend_raw_text("Kept as is.", ["", "  "], DAY) == "Kept as is."


def test_a_thought_with_no_raw_text_gets_the_addition_alone():
    raw = add(None, 2, 4, held_to=None)
    assert raw.startswith("--- added 2026-09-26 ---\n\nRed or black")
    assert split_blocks(raw).first == ""
    assert check_fields("t", "s", [], raw).raw_text == raw


def test_the_first_block_is_kept_and_cut_at_10000():
    first = "a" * 15_000
    raw = extend_raw_text(first, ["new words"], DAY)
    blocks = split_blocks(raw)
    assert len(blocks.first) == 10_000
    assert blocks.first == "a" * 9_999 + "…"
    assert blocks.additions == [Block("2026-09-26", "new words")]
    assert not blocks.left_out

    short = "b" * 10_000
    assert split_blocks(extend_raw_text(short, ["x"], DAY)).first == short


def test_the_newest_block_is_cut_at_its_start_when_it_alone_does_not_fit():
    first = "f" * 9_000
    newest = "start " + "n" * 14_000 + " the end"
    raw = extend_raw_text(first, [newest], DAY)
    assert len(raw) == MAX_RAW_TEXT
    blocks = split_blocks(raw)
    assert blocks.first == first
    [block] = blocks.additions
    assert block.text.startswith("…")
    assert block.text.endswith(" the end")
    assert newest.endswith(block.text[1:])
    assert LEFT_OUT not in raw


def test_oldest_additions_are_left_out_with_one_marker_line():
    raw = "first words " * 300  # 3,600 characters
    for n in range(8):
        raw = extend_raw_text(raw, [f"addition {n} " + "w" * 3_000], date(2026, 10, n + 1))
    assert len(raw) <= MAX_RAW_TEXT
    assert raw.startswith("first words " * 300)
    assert raw.count(LEFT_OUT) == 1
    blocks = split_blocks(raw)
    assert blocks.left_out
    kept = [block.text.split()[1] for block in blocks.additions]
    # The newest whole blocks, in order, ending with the newest.
    assert kept == [str(n) for n in range(8 - len(kept), 8)]
    assert len(kept) < 8
    assert raw.endswith("addition 7 " + "w" * 3_000)
    assert f"{LEFT_OUT}\n\n--- added 2026-10-0{8 - len(kept) + 1} ---" in raw


def test_a_new_marker_is_not_added_twice():
    blocks = RawBlocks("first", [Block("2026-10-01", "older")], left_out=True)
    raw = extend_raw_text(join_blocks(blocks), ["newer"], DAY)
    assert raw == f"first\n\n{LEFT_OUT}\n\n--- added 2026-10-01 ---\n\nolder\n\n--- added 2026-09-26 ---\n\nnewer"


@pytest.mark.parametrize("seed", range(20))
def test_the_result_is_never_over_20000(seed):
    rng = random.Random(seed)
    raw = rng.choice([None, "", "x" * rng.randint(1, 20_000)])
    first = split_blocks(raw).first
    for n in range(rng.randint(1, 15)):
        texts = ["y" * rng.randint(1, 9_000) for _ in range(rng.randint(1, 3))]
        raw = extend_raw_text(raw, texts, date(2026, 10, 1 + n % 28))
        assert len(raw) <= MAX_RAW_TEXT
        assert check_fields("t", "s", [], raw).raw_text == raw
        assert split_blocks(raw).first == (first if len(first) <= 10_000 else first[:9_999] + "…")
        assert raw.endswith(texts[-1][-100:])


def test_split_reads_back_what_join_writes():
    for blocks in (
        RawBlocks("only"),
        RawBlocks("", [Block("2026-01-02", "a")]),
        RawBlocks("f", [Block("2026-01-02", "a\n\nb"), Block("2026-01-03", "c")]),
        RawBlocks("", [Block("2026-01-02", "a")], left_out=True),
        RawBlocks("f", [Block("2026-01-02", "a")], left_out=True),
    ):
        assert split_blocks(join_blocks(blocks)) == blocks
