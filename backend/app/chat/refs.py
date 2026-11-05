"""Refs: the short names (T1, T2, …) the model uses for the thoughts a
conversation has seen (thought-appending design decisions 2 and 15).

A thought gets a ref the first time the conversation sees it, in this order
of the stored rows, by position: each tool message's `details.sources`
(search results) and `details.similar` (check candidates), then each
proposal's parts by index, with their `add_to`, `similar`, and `thought_id`.
A part's `thought_id` is written when the user confirms it, so it counts at
the part's `seen_position`, stamped at the confirm, and at the proposal's
position for a part confirmed before that stamp existed.

The rows are never rewritten and a deleted thought keeps its id in them, so
a number never moves and is never given to another thought. Another user's
thought id, which only a crafted row can hold, gets no number.
"""

import logging
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import FilingConfig
from app.chat.prompt import seen_thoughts_note
from app.models import Message, Proposal, Thought

logger = logging.getLogger(__name__)

REF = re.compile(r"^\s*T(\d+)\s*$", re.IGNORECASE)


def normal_ref(value: str) -> str | None:
    """A ref as the server writes it (`T3`), or None when the text is not one."""
    match = REF.match(value)
    return f"T{int(match.group(1))}" if match else None


@dataclass(frozen=True)
class SeenThought:
    """A thought the conversation has seen, as it is now."""

    ref: str
    id: uuid.UUID
    title: str
    summary: str
    tags: list[str]
    category: str | None
    created_at: datetime
    updated_at: datetime
    # The thought's own date (thought-dates), as thought_date_text() reads it.
    starts_on: date | None = None
    starts_at: time | None = None
    ends_on: date | None = None
    ends_at: time | None = None


def date_fields(thought: Any) -> dict[str, Any]:
    """A thought's date columns, for a SeenThought."""
    return {
        "starts_on": thought.starts_on,
        "starts_at": thought.starts_at,
        "ends_on": thought.ends_on,
        "ends_at": thought.ends_at,
    }


def _thought_id(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _position(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def appearances(
    messages: Sequence[Message],
    proposals: Sequence[Proposal],
    *,
    seen_before: int | None = None,
) -> list[uuid.UUID]:
    """Every thought id the rows name, in the order the conversation saw them,
    repeats included: the first of an id fixes its number, the last says how
    recently it was seen.

    Within one position, a tool message's sources come first, then its
    candidates, then the parts of the proposals there, by part index.

    With `seen_before`, a confirmed part stamped at that position or later
    is left out: a row the turn stores there will be numbered before it.
    """
    found: list[tuple[tuple[int, ...], uuid.UUID]] = []
    for message in messages:
        if message.role != "tool" or not isinstance(message.details, dict):
            continue
        for kind, name in enumerate(("sources", "similar")):
            items = message.details.get(name)
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                thought_id = _thought_id(item.get("id") or item.get("thought_id"))
                if thought_id is not None:
                    found.append(((message.position, 0, kind, index, 0), thought_id))
    for order, proposal in enumerate(proposals):
        for index, part in enumerate(proposal.parts or []):
            if not isinstance(part, dict):
                continue
            similar = part.get("similar")
            named = (
                (part.get("add_to"), proposal.position),
                (similar.get("thought_id") if isinstance(similar, dict) else None, proposal.position),
                (part.get("thought_id"), _position(part.get("seen_position"), proposal.position)),
            )
            for kind, (value, position) in enumerate(named):
                thought_id = _thought_id(value)
                if kind == 2 and seen_before is not None and position >= seen_before:
                    continue
                if thought_id is not None:
                    found.append(((position, 1, order, index, kind), thought_id))
    found.sort(key=lambda item: item[0])
    return [thought_id for _, thought_id in found]


class Refs:
    """The refs of one conversation, and the seen thoughts that still exist.

    `numbered` holds every numbered id, T1 first, deleted ones included.
    `thoughts` holds the user's thoughts among them that exist, as they are
    now. `recent` lists those ids most recently seen first.
    """

    def __init__(
        self,
        numbered: list[uuid.UUID],
        thoughts: dict[uuid.UUID, SeenThought],
        recent: list[uuid.UUID],
    ):
        self.numbered = list(numbered)
        self._numbers = {thought_id: index + 1 for index, thought_id in enumerate(self.numbered)}
        self.thoughts = thoughts
        self.recent = recent

    def ref_of(self, thought_id: uuid.UUID) -> str | None:
        number = self._numbers.get(thought_id)
        return f"T{number}" if number else None

    def label(self, thought_id: uuid.UUID) -> str:
        """The thought's ref, or the one it gets when it is added next."""
        return self.ref_of(thought_id) or f"T{len(self.numbered) + 1}"

    def add(self, thought_id: uuid.UUID) -> str:
        """Number a thought seen now, after every other; returns its ref."""
        if thought_id not in self._numbers:
            self.numbered.append(thought_id)
            self._numbers[thought_id] = len(self.numbered)
        return f"T{self._numbers[thought_id]}"

    def see(self, thought: Thought) -> str:
        """Number a thought the user's row shows now, as add() does, and keep
        it as a seen thought, so a ref to it resolves before any stored row
        names it (the offer's candidates)."""
        ref = self.add(thought.id)
        if thought.id not in self.thoughts:
            self.thoughts[thought.id] = SeenThought(
                ref=ref,
                id=thought.id,
                title=thought.title,
                summary=thought.summary,
                tags=list(thought.tags or []),
                category=thought.category,
                created_at=thought.created_at,
                updated_at=thought.updated_at,
                **date_fields(thought),
            )
        return ref

    def resolve(self, ref: str) -> SeenThought | None:
        """The user's existing thought a ref names, or None for a ref the
        conversation has not seen, or one whose thought is gone."""
        normal = normal_ref(ref)
        if normal is None:
            return None
        number = int(normal[1:])
        if not 1 <= number <= len(self.numbered):
            return None
        return self.thoughts.get(self.numbered[number - 1])

    def seen(self) -> list[SeenThought]:
        """The seen thoughts that exist, most recently seen first."""
        return [self.thoughts[thought_id] for thought_id in self.recent]

    def by_id(self) -> dict[str, str]:
        """The ref of each seen thought that exists, by its id as text."""
        return {str(thought.id): thought.ref for thought in self.thoughts.values()}

    def note(
        self,
        filing: FilingConfig,
        keep: set[uuid.UUID] | frozenset[uuid.UUID] = frozenset(),
        zone: ZoneInfo | None = None,
    ) -> str | None:
        """The seen-thoughts note, or None when no seen thought exists: the
        `filing.seen_thoughts` most recently seen, and every thought in
        `keep` past them (the offer keeps the thoughts the conversation filed).
        Filing days are the user's local days in `zone` (UTC when not given),
        as in the search tool's text."""
        seen = self.seen()
        cap = filing.seen_thoughts
        listed = seen[:cap] + [thought for thought in seen[cap:] if thought.id in keep]
        return seen_thoughts_note(listed, len(listed), filing.seen_summary_chars, zone)


async def conversation_refs(
    session: AsyncSession,
    user_id: uuid.UUID,
    messages: Sequence[Message],
    proposals: Sequence[Proposal],
    *,
    seen_before: int | None = None,
) -> Refs:
    """The conversation's refs from the rows a turn loads anyway, with one
    query for the thoughts they name. `seen_before` as for appearances()."""
    order = appearances(messages, proposals, seen_before=seen_before)
    distinct = list(dict.fromkeys(order))
    if not distinct:
        return Refs([], {}, [])
    # One query tells the user's thoughts (read in full), another user's
    # (only their id is read), and deleted ones (no row) apart.
    own_row = Thought.user_id == user_id

    def own(column):
        return case((own_row, column), else_=None)

    rows = (
        await session.execute(
            select(
                Thought.id,
                own_row.label("own"),
                own(Thought.title).label("title"),
                own(Thought.summary).label("summary"),
                own(Thought.tags).label("tags"),
                own(Thought.category).label("category"),
                own(Thought.created_at).label("created_at"),
                own(Thought.updated_at).label("updated_at"),
                own(Thought.starts_on).label("starts_on"),
                own(Thought.starts_at).label("starts_at"),
                own(Thought.ends_on).label("ends_on"),
                own(Thought.ends_at).label("ends_at"),
            ).where(Thought.id.in_(distinct))
        )
    ).all()
    foreign = {row.id for row in rows if not row.own}
    if foreign:
        logger.warning("A conversation's rows name %d thoughts of another user", len(foreign))
    numbered = [thought_id for thought_id in distinct if thought_id not in foreign]
    numbers = {thought_id: index + 1 for index, thought_id in enumerate(numbered)}
    thoughts = {
        row.id: SeenThought(
            ref=f"T{numbers[row.id]}",
            id=row.id,
            title=row.title,
            summary=row.summary,
            tags=list(row.tags or []),
            category=row.category,
            created_at=row.created_at,
            updated_at=row.updated_at,
            **date_fields(row),
        )
        for row in rows
        if row.own
    }
    recent = [thought_id for thought_id in dict.fromkeys(reversed(order)) if thought_id in thoughts]
    return Refs(numbered, thoughts, recent)


def saved_ids(proposals: Sequence[Proposal]) -> set[uuid.UUID]:
    """The thoughts the conversation's confirmed parts saved or added to."""
    return {
        thought_id
        for proposal in proposals
        for part in proposal.parts or []
        if isinstance(part, dict) and (thought_id := _thought_id(part.get("thought_id")))
    }


def resolve_additions(parts: list[dict[str, Any]], refs: Refs) -> list[dict[str, Any]]:
    """The parts as stored: a part whose `add_to_ref` names a seen thought
    becomes an addition to it (design decision 3), with `add_to` (its id),
    `based_on` (its `updated_at`), and its current title, since an addition
    never changes the title and the model's is ignored. An addition never
    changes the thought's date either (design decision 22), so the model's
    date or date choices are dropped. Any other ref makes the part a new
    thought, and is logged."""
    resolved: list[dict[str, Any]] = []
    for part in parts:
        ref = part.get("add_to_ref")
        stored = {key: value for key, value in part.items() if key != "add_to_ref"}
        if ref is None:
            resolved.append(stored)
            continue
        target = refs.resolve(ref)
        if target is None:
            logger.info(
                "A proposal part adds to %s, which this conversation has not seen or whose "
                "thought is gone; it is proposed as a new thought",
                ref,
            )
            resolved.append(stored)
            continue
        resolved.append(
            {
                **stored,
                "title": target.title,
                "when": None,
                "when_choices": None,
                "add_to": str(target.id),
                "based_on": target.updated_at.isoformat(),
            }
        )
    return resolved
