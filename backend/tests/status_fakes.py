"""Fakes for the turn checks of thought-status task group 3 that run on SQLite.

On SQLite, `search_thoughts()` runs Postgres-only SQL once the user has a
thought, and the similar-thought check's layer 1 is a vector search
(`search_by_vector`), gated to Postgres by `similar.check_runs()`
(thought-status design decision 12). So:

- `canned_search(thought_id, url)` stands in for the turn's
  `search_tool_result`: it answers `1 thought: <title>` with that stored
  thought as the one source, so the turn stores its id in
  `details.sources`, and the next call can name it as `T1` (the first ref of
  a new conversation).
- `fake_similar(candidates, url)` stands in for layer 1's
  `search_by_vector` (and lets `check_runs` pass): for each new part whose
  words (title and tags) hold a key of `candidates`, it returns those stored
  thoughts, read from the database, and no candidate for any other part.
  The embedding request before the lookup still goes to the fake provider,
  when the user has an active index (`seed_active_index`), so embedding
  counts stay true.

Both are set with monkeypatch.
"""

import uuid
from collections.abc import Mapping, Sequence

from sqlalchemy import select

from app.chat import similar as similar_module
from app.chat import turn as turn_module
from app.chat.tools import SearchToolResult
from app.models import SearchIndex, Thought
from app.thoughts.search import Hit, SearchResult
from tests.chat_helpers import run_db
from tests.thought_helpers import EMBED_MODEL

# concept_embedder's vectors: five concepts, 64 hashed buckets, one constant.
DIMENSION = 70


def canned_search(monkeypatch, thought_id) -> list[dict]:
    """Make every search_thoughts call find the stored thought `thought_id`.
    Returns the list of calls' arguments, for checks."""
    calls: list[dict] = []

    async def fake(session, user, arguments, **options):
        calls.append({"arguments": arguments, **options})
        thought = await session.get(Thought, uuid.UUID(str(thought_id)))
        return SearchToolResult(
            text=f"1 thought: {thought.title}",
            sources=[
                {
                    "id": str(thought.id),
                    "title": thought.title,
                    "created_at": thought.created_at.isoformat(),
                    "tags": list(thought.tags or []),
                }
            ],
        )

    monkeypatch.setattr(turn_module, "search_tool_result", fake)
    return calls


def fake_similar(monkeypatch, candidates: Mapping[str, Sequence]) -> list[str]:
    """Make layer 1 find, for a part whose words hold a key of `candidates`,
    those stored thoughts (ids), and nothing for any other part. Returns the
    words of each lookup, for checks."""
    lookups: list[str] = []

    async def check_runs(session, user) -> bool:
        return True

    async def search_by_vector(session, user, words, **options) -> SearchResult:
        lookups.append(words)
        ids = [
            uuid.UUID(str(thought_id))
            for key, thought_ids in candidates.items()
            if key.lower() in words.lower()
            for thought_id in thought_ids
        ]
        if not ids:
            return SearchResult()
        rows = {
            thought.id: thought
            for thought in (
                await session.execute(
                    select(Thought).where(Thought.id.in_(ids), Thought.user_id == user.id)
                )
            ).scalars()
        }
        hits = [
            Hit(thought=rows[thought_id], similarity=None, keyword_rank=None, chunk=None)
            for thought_id in dict.fromkeys(ids)
            if thought_id in rows
        ]
        return SearchResult(hits=hits, total=len(hits))

    monkeypatch.setattr(similar_module, "check_runs", check_runs)
    monkeypatch.setattr(similar_module, "search_by_vector", search_by_vector)
    return lookups


def seed_active_index(url, user_id) -> None:
    """An active search index for the user, so layer 1 sends its embedding
    request to the fake provider before the lookup."""

    async def work(session):
        session.add(
            SearchIndex(
                user_id=uuid.UUID(str(user_id)),
                version=1,
                embedding_provider="nebius",
                embedding_model=EMBED_MODEL,
                dimension=DIMENSION,
                status="active",
            )
        )
        await session.commit()

    run_db(url, work)
