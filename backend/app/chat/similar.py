"""The similar-thought check (thought-appending design decision 4).

Layer 1 finds candidates: every checked part's query (title, tags, summary,
as a head entry is embedded) goes to the embedding provider in one request,
then the search's ranking runs once per part with that vector. A thought
passes the candidate cut-off from the index's baseline (design decision 5)
or the search's word-share rule; at most three per part, leaving out the
thoughts other parts add to. Age never counts against a thought. With no
key, a provider error, or no index, the words half still runs.

Layer 2 lets the model decide: when any part has candidates, the turn writes
no proposal, and the tool result lists them by ref and asks for the call
again, with add_to or new: true on each new part. Layer 3 lets the user
decide: a written new part that is not a task, whose best candidate passes
the strong cut-off, stores `similar`, and the card offers to add to it.

The check stores and changes nothing. It runs on Postgres only, and only for
a user who has thoughts.
"""

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx2
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ChatConfig
from app.chat.prompt import thought_entry
from app.chat.refs import Refs
from app.chat.tools import ProposalPart
from app.config import Settings
from app.models import Thought, User
from app.thoughts.baseline import Cutoffs, cutoffs
from app.thoughts.chunking import head_text
from app.thoughts.indexing import ACTIVE, embed_for_index, index_with_status
from app.thoughts.search import search_by_vector

logger = logging.getLogger(__name__)

# Candidates listed for one part, at most.
MAX_CANDIDATES = 3
TASK = "task"

CANDIDATES_FOUND = """\
Nothing was proposed yet: the user has filed thoughts similar to what you \
proposed, listed below by ref. For each thought you proposed, decide whether \
it continues one of the filed thoughts listed for it or is a new thing. Then \
call propose_thought again with every thought: give add_to with the ref of \
the filed thought it adds to, or new: true to keep it a new thought. An \
addition's summary is the whole new summary of that thought, and says what \
changed. A thought not listed here has no similar filed thought; keep it as \
it is.
{parts}"""
REPEATED_TASK = "A repeated task is usually a new task."


@dataclass(frozen=True)
class Candidate:
    thought: Thought
    # The best entry's cosine similarity, or None for a match by words only.
    similarity: float | None


@dataclass(frozen=True)
class PartCheck:
    # The candidates the model is told about (layer 2), best first.
    candidates: list[Candidate] = field(default_factory=list)
    # The best candidate past the strong cut-off, for the card's hint (layer 3).
    strong: Candidate | None = None


@dataclass
class Check:
    """What the check found for each part of one proposal call, in order."""

    parts: list[PartCheck]
    # The conversation's refs, when the check needed them.
    refs: Refs | None = None

    @property
    def has_candidates(self) -> bool:
        return any(part.candidates for part in self.parts)


def check_query(title: str, tags: Sequence[str], summary: str) -> str:
    """What a part's query embeds: its head entry's text, with no query
    instruction, so its similarities are on the scale of the baseline,
    which compares head entries."""
    return head_text(title, _tags(tags), summary)


def word_query(title: str, tags: Sequence[str]) -> str:
    """The words a part is matched on: its title and tags. The whole summary
    would rarely reach the word-share rule."""
    return " ".join([title, *_tags(tags)])


def _tags(tags: Sequence[str]) -> list[str]:
    return [tag.strip().lstrip("#").lower() for tag in tags if tag.strip().lstrip("#")]


async def check_runs(session: AsyncSession, user: User) -> bool:
    """Whether the check can find anything: on Postgres, for a user with thoughts."""
    if session.bind.dialect.name != "postgresql":
        return False
    has_thoughts = select(Thought.id).where(Thought.user_id == user.id)
    return bool((await session.execute(select(exists(has_thoughts)))).scalar())


@dataclass(frozen=True)
class Query:
    title: str
    tags: list[str]
    summary: str


async def find_similar(
    session: AsyncSession,
    user: User,
    queries: Sequence[Query],
    *,
    config: ChatConfig,
    settings: Settings,
    exclude: set[uuid.UUID] | frozenset[uuid.UUID] = frozenset(),
    conversation_id: uuid.UUID | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> tuple[list[list[Candidate]], Cutoffs | None]:
    """Layer 1: the candidates for each query, best first, at most three,
    and the cut-offs used (None when it matched by words only).

    All the queries' vectors come from one embedding request. It never
    creates an index and never raises for a provider problem.
    """
    if not queries:
        return [], None
    index = await index_with_status(session, user.id, ACTIVE)
    vectors: list[list[float] | None] = [None] * len(queries)
    limits = cutoffs(index, config) if index is not None else None
    if index is not None:
        outcome = await embed_for_index(
            session,
            user,
            index,
            [],
            settings=settings,
            extra_texts=[check_query(q.title, q.tags, q.summary) for q in queries],
            conversation_id=conversation_id,
            http_client=http_client,
        )
        if outcome.error is None:
            vectors = list(outcome.extra_vectors)
        else:
            logger.info("The similar-thought check runs by words only: %s", outcome.error.code)
            limits = None
    found: list[list[Candidate]] = []
    for query, vector in zip(queries, vectors):
        result = await search_by_vector(
            session,
            user,
            word_query(query.title, query.tags),
            index=index,
            vector=vector,
            # Unused without a vector: then only the word-share rule passes.
            min_similarity=limits.candidate if limits is not None else 2.0,
            limit=MAX_CANDIDATES + len(exclude),
            config=config.search,
        )
        candidates = [
            Candidate(thought=hit.thought, similarity=hit.similarity if vector else None)
            for hit in result.hits
            if hit.thought.id not in exclude
        ]
        found.append(candidates[:MAX_CANDIDATES])
    return found, limits


def _strong(candidates: list[Candidate], limits: Cutoffs | None) -> Candidate | None:
    if limits is None:
        return None
    scored = [c for c in candidates if c.similarity is not None and c.similarity >= limits.strong]
    return max(scored, key=lambda c: c.similarity, default=None)


async def check_parts(
    session: AsyncSession,
    user: User,
    parts: Sequence[ProposalPart],
    refs: Refs | None,
    *,
    config: ChatConfig,
    settings: Settings,
    again: bool = False,
    conversation_id: uuid.UUID | None = None,
    http_client: httpx2.AsyncClient | None = None,
) -> Check:
    """Check a proposal call's parts.

    A part that adds to a seen thought is not checked, and the thoughts such
    parts name are no other part's candidates. A part with neither add_to nor
    new gets candidates for layer 2, unless the call comes `again`, after a
    candidate round. Every new part that is not a task is checked for the
    strong match of layer 3.
    """
    if not await check_runs(session, user):
        return Check(parts=[PartCheck() for _ in parts], refs=refs)
    targets = {
        index: refs.resolve(part.add_to)
        for index, part in enumerate(parts)
        if part.add_to is not None and refs is not None
    }
    added = {index for index, target in targets.items() if target is not None}
    exclude = {targets[index].id for index in added}
    wanted = [
        (
            index,
            index not in added and not part.new and not again,
            index not in added and part.category != TASK,
        )
        for index, part in enumerate(parts)
    ]
    checked = [(index, layer2, layer3) for index, layer2, layer3 in wanted if layer2 or layer3]
    found, limits = await find_similar(
        session,
        user,
        [
            Query(parts[index].title, parts[index].tags, parts[index].summary)
            for index, _, _ in checked
        ],
        config=config,
        settings=settings,
        exclude=exclude,
        conversation_id=conversation_id,
        http_client=http_client,
    )
    results = [PartCheck() for _ in parts]
    for (index, layer2, layer3), candidates in zip(checked, found):
        results[index] = PartCheck(
            candidates=candidates if layer2 else [],
            strong=_strong(candidates, limits) if layer3 else None,
        )
    return Check(parts=results, refs=refs)


def candidates_note(
    parts: Sequence[ProposalPart], check: Check, refs: Refs, summary_chars: int
) -> tuple[str, list[dict[str, Any]]]:
    """Layer 2: the text that lists each part's candidates by ref and asks
    for the call again, and the candidates as the tool message stores them
    (`details.similar`), so they get refs: {id, title, created_at, tags}.

    A thought new to the conversation is numbered after every other, in the
    order of the list, as the next turn numbers it from the stored rows.
    """
    similar: list[dict[str, Any]] = []
    listed: set[uuid.UUID] = set()
    blocks: list[str] = []
    for part, part_check in zip(parts, check.parts):
        if not part_check.candidates:
            continue
        entries = []
        for candidate in part_check.candidates:
            thought = candidate.thought
            entries.append(thought_entry(refs.see(thought), thought, summary_chars))
            if thought.id not in listed:
                listed.add(thought.id)
                similar.append(
                    {
                        "id": str(thought.id),
                        "title": thought.title,
                        "created_at": thought.created_at.isoformat(),
                        "tags": list(thought.tags or []),
                    }
                )
        block = f"Similar to “{part.title}”:\n" + "\n".join(entries)
        if part.category == TASK:
            block += "\n" + REPEATED_TASK
        blocks.append(block)
    return CANDIDATES_FOUND.format(parts="\n\n".join(blocks)), similar


def with_similar(stored: list[dict[str, Any]], check: Check) -> list[dict[str, Any]]:
    """The stored parts, each new part with a strong match naming it as
    `similar` (layer 3). Two parts of one proposal never add to one thought,
    so a thought several parts match strongly is named on the closest only
    (the first of equals)."""
    # The best (similarity, -index) per thought: the closest, then the first.
    closest: dict[uuid.UUID, tuple[float, int]] = {}
    for index, part_check in enumerate(check.parts):
        strong = part_check.strong
        if strong is not None:
            score = (strong.similarity or 0.0, -index)
            closest[strong.thought.id] = max(closest.get(strong.thought.id, score), score)
    named = {-index for _, index in closest.values()}
    return [
        {**part, "similar": {"thought_id": str(part_check.strong.thought.id)}}
        if part_check.strong is not None and index in named
        else part
        for index, (part, part_check) in enumerate(zip(stored, check.parts))
    ]
