"""The raw text of a thought that grows by additions (thought-appending design decision 8).

A thought's raw text is a list of blocks. The first is the text the thought
was filed with; each later block is one addition, after a dated separator:

    <first block>\\n\\n--- added 2026-09-26 ---\\n\\n<messages joined by blank lines>

Within the store's limit, the first block is kept (cut at its end past half
the limit), then the newest additions whole, newest first. Where additions
were left out, one marker line follows the first block. The left-out text is
not lost: it stays in its proposal's raw text while that conversation exists.

Everything here is pure: it reads no rows and writes none.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from app.chat.prompt import text_for_model
from app.models import Message
from app.thoughts.store import MAX_RAW_TEXT

# A separator starts the text when the thought was filed with no raw text.
SEPARATOR = re.compile(r"(?:^|\n\n)--- added (\d{4}-\d{2}-\d{2}) ---\n\n")
LEFT_OUT = "--- earlier additions left out ---"
FIRST_BLOCK_LIMIT = MAX_RAW_TEXT // 2
ELLIPSIS = "…"


@dataclass(frozen=True)
class Block:
    """One addition: the day it was added (YYYY-MM-DD) and its messages."""

    day: str
    text: str


@dataclass(frozen=True)
class RawBlocks:
    """A raw text split into its blocks. left_out is true when earlier
    additions were left out, which the marker line records."""

    first: str
    additions: list[Block] = field(default_factory=list)
    left_out: bool = False


def split_blocks(raw_text: str | None) -> RawBlocks:
    """The blocks of a stored raw text. No raw text is an empty first block."""
    text = raw_text or ""
    matches = list(SEPARATOR.finditer(text))
    if not matches:
        return RawBlocks(text)
    first = text[: matches[0].start()]
    left_out = first == LEFT_OUT or first.endswith("\n\n" + LEFT_OUT)
    if left_out:
        first = first.removesuffix(LEFT_OUT).removesuffix("\n\n")
    additions = [
        Block(match.group(1), text[match.end() : nxt.start() if nxt else len(text)])
        for match, nxt in zip(matches, [*matches[1:], None])
    ]
    return RawBlocks(first, additions, left_out)


def join_blocks(blocks: RawBlocks) -> str:
    """The raw text of these blocks; split_blocks() reads it back."""
    text = "\n\n".join(part for part in (blocks.first, LEFT_OUT if blocks.left_out else "") if part)
    for block in blocks.additions:
        text += ("\n\n" if text else "") + f"--- added {block.day} ---\n\n" + block.text
    return text


def _cut_end(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + ELLIPSIS


def fit_blocks(blocks: RawBlocks, limit: int = MAX_RAW_TEXT) -> RawBlocks:
    """The blocks that fit `limit` characters once joined.

    The first block is kept, cut at its end past half the limit. Then the
    newest additions, whole, newest first, while they fit; the newest alone
    is cut at its start when it does not fit. Leaving any out sets left_out.
    """
    first = _cut_end(blocks.first, limit // 2)
    whole = RawBlocks(first, list(blocks.additions), blocks.left_out)
    if len(join_blocks(whole)) <= limit:
        return whole
    kept: list[Block] = []
    for block in reversed(blocks.additions):
        trial = RawBlocks(first, [block, *kept], True)
        if len(join_blocks(trial)) > limit:
            break
        kept.insert(0, block)
    if kept:
        return RawBlocks(first, kept, True)
    # The newest addition alone does not fit: keep its end.
    newest = blocks.additions[-1]
    left_out = blocks.left_out or len(blocks.additions) > 1
    room = limit - len(join_blocks(RawBlocks(first, [Block(newest.day, "")], left_out)))
    tail = newest.text[len(newest.text) - (room - 1) :] if room > 1 else ""
    return RawBlocks(first, [Block(newest.day, ELLIPSIS + tail)], left_out)


def added_texts(
    messages: Iterable[Message],
    *,
    from_position: int,
    to_position: int,
    held_to: int | None,
) -> list[str]:
    """The user's messages an addition brings, as the model read them.

    The messages from the proposal's from_position up to its to_position,
    after held_to, the last position the thought already holds from this
    conversation (None when it holds none). Compacted messages count, as for
    a proposal's raw text; empty ones are skipped.
    """
    start = from_position if held_to is None else max(from_position, held_to + 1)
    texts = (
        text_for_model(message.content or "").strip()
        for message in messages
        if message.role == "user" and start <= message.position <= to_position
    )
    return [text for text in texts if text]


def extend_raw_text(raw_text: str | None, texts: list[str], day: date) -> str | None:
    """The raw text after an addition of these message texts on `day`.

    With no text to add, the raw text is returned unchanged. The result is
    never longer than the store's limit.
    """
    texts = [text.strip() for text in texts if text.strip()]
    if not texts:
        return raw_text
    blocks = split_blocks(raw_text)
    grown = RawBlocks(
        blocks.first,
        [*blocks.additions, Block(day.isoformat(), "\n\n".join(texts))],
        blocks.left_out,
    )
    return join_blocks(fit_blocks(grown))
