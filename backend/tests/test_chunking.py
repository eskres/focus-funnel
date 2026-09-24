"""The chunker (thought-storage task 4.2)."""

import random

from app.thoughts.chunking import OVERLAP, chunk_raw_text, head_text, pieces

SENTENCES = [
    "The flat near Alfama was cheaper than the hotel.",
    "Ride tram 28 early in the morning before it gets crowded.",
    "Budget stays under eight thousand for everything including food.",
    "Take the train to Sintra for a day if the weather is good.",
    "Book the flights this month while the fares are low.",
]


def long_text(length: int, seed: int = 1) -> str:
    rng = random.Random(seed)
    paragraphs: list[str] = []
    while sum(len(p) + 2 for p in paragraphs) < length:
        paragraphs.append(" ".join(rng.choice(SENTENCES) for _ in range(rng.randint(3, 6))))
    text = "\n\n".join(paragraphs)[:length]
    # End on a whole sentence.
    return text[: text.rfind(".") + 1]


def test_no_raw_text_gives_only_the_head():
    assert pieces("Oat milk", ["groceries"], "Buy oat milk.", None) == pieces(
        "Oat milk", ["groceries"], "Buy oat milk.", "   "
    )
    [head] = pieces("Oat milk", ["groceries"], "Buy oat milk.", None)
    assert head.chunk == 0 and head.start_char is None
    assert head.text == "Oat milk\n#groceries\nBuy oat milk."


def test_raw_text_equal_to_the_summary_gives_only_the_head():
    assert chunk_raw_text("  Buy OAT milk. ", "Buy oat   milk.") == []


def test_head_without_tags():
    assert head_text("Title", [], "Summary") == "Title\nSummary"


def test_short_raw_text_is_one_chunk():
    raw = "Some detail that is not in the summary."
    [head, chunk] = pieces("T", [], "Summary", raw)
    assert (chunk.chunk, chunk.start_char, chunk.end_char, chunk.text) == (1, 0, len(raw), raw)


def test_long_text_splits_into_overlapping_chunks_at_boundaries():
    raw = long_text(20_000)
    ranges = chunk_raw_text(raw, "summary")

    assert 20 <= len(ranges) <= 35
    for start, end in ranges:
        assert end - start <= 1000
        # Each chunk ends at a sentence or paragraph break, except the last.
        if end < len(raw.rstrip()):
            assert raw[end - 1] in ".!?"
        # And starts at the beginning of a word.
        assert start == 0 or raw[start - 1].isspace()
    sizes = [end - start for start, end in ranges[:-1]]
    assert 600 <= sum(sizes) / len(sizes) <= 900
    for (_, previous_end), (start, _) in zip(ranges, ranges[1:]):
        assert 0 < previous_end - start <= OVERLAP + 60
    assert ranges[0][0] == 0 and ranges[-1][1] == len(raw.rstrip())


def test_each_range_points_at_its_text():
    raw = long_text(5_000, seed=7)
    for piece in pieces("T", ["a"], "Summary", raw)[1:]:
        assert raw[piece.start_char : piece.end_char] == piece.text
        assert piece.text == piece.text.strip()


def test_text_without_breaks_is_still_cut():
    raw = "x" * 2500
    ranges = chunk_raw_text(raw, "summary")
    assert len(ranges) >= 3
    assert all(end - start <= 1000 for start, end in ranges)
