"""What gets embedded for a thought: its head, and its raw text in chunks.

The head (chunk 0) is the title, the tags, and the summary. Raw text, when a
thought has some that is not just its summary, is split into pieces of about
TARGET characters with about OVERLAP characters shared between neighbours,
breaking at a paragraph if one is near, else at a sentence, else at a space.
"""

import re
from dataclasses import dataclass

TARGET = 800
OVERLAP = 100
# A break is looked for between these distances from the chunk's start.
MIN_BREAK = 400
MAX_CHUNK = 1000

_SENTENCE_END = re.compile(r"[.!?](?=\s)|\n")


@dataclass(frozen=True)
class Piece:
    chunk: int
    text: str
    start_char: int | None = None
    end_char: int | None = None


def head_text(title: str, tags: list[str], summary: str) -> str:
    lines = [title]
    if tags:
        lines.append(" ".join(f"#{tag}" for tag in tags))
    lines.append(summary)
    return "\n".join(lines)


def _normalized(text: str) -> str:
    return " ".join(text.split()).lower()


def _best_break(text: str, start: int) -> int:
    """Where the chunk starting at `start` should end."""
    if len(text) - start <= MAX_CHUNK:
        return len(text)
    low, high, aim = start + MIN_BREAK, start + MAX_CHUNK, start + TARGET

    def closest(positions: list[int]) -> int | None:
        return min(positions, key=lambda position: abs(position - aim)) if positions else None

    window = text[low:high]
    paragraphs = [low + match.end() for match in re.finditer(r"\n\s*\n", window)]
    sentences = [low + match.end() for match in _SENTENCE_END.finditer(window)]
    spaces = [low + match.start() for match in re.finditer(r"\s", window)]
    return closest(paragraphs) or closest(sentences) or closest(spaces) or aim


def _next_start(text: str, end: int, start: int) -> int:
    """Start the next chunk about OVERLAP characters back, at a word."""
    position = max(end - OVERLAP, start + 1)
    while position < end and not text[position - 1].isspace():
        position += 1
    while position < end and text[position].isspace():
        position += 1
    return position if position < end else end


def chunk_raw_text(raw_text: str | None, summary: str) -> list[tuple[int, int]]:
    """Character ranges of the raw text's chunks, or none when there is nothing to add."""
    if not raw_text or not raw_text.strip() or _normalized(raw_text) == _normalized(summary):
        return []
    ranges = []
    start = len(raw_text) - len(raw_text.lstrip())
    while start < len(raw_text):
        end = _best_break(raw_text, start)
        # Trim whitespace at the edges so each range points at text.
        trimmed_end = end
        while trimmed_end > start and raw_text[trimmed_end - 1].isspace():
            trimmed_end -= 1
        if trimmed_end > start:
            ranges.append((start, trimmed_end))
        if end >= len(raw_text):
            break
        start = _next_start(raw_text, end, start)
    return ranges


def pieces(title: str, tags: list[str], summary: str, raw_text: str | None) -> list[Piece]:
    """Everything to embed for one thought, head first."""
    result = [Piece(chunk=0, text=head_text(title, tags, summary))]
    for number, (start, end) in enumerate(chunk_raw_text(raw_text, summary), start=1):
        result.append(Piece(chunk=number, text=raw_text[start:end], start_char=start, end_char=end))
    return result
