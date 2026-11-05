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
from datetime import datetime
from typing import Any

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


def _thought_id(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _position(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def appearances(messages: Sequence[Message], proposals: Sequence[Proposal]) -> list[uuid.UUID]:
    """Every thought id the rows name, in the order the conversation saw them,
    repeats included: the first of an id fixes its number, the last says how
    recently it was seen.

    Within one position, a tool message's sources come first, then its
    candidates, then the parts of the proposals there, by part index.
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

    def titles(self) -> dict[str, str]:
        """The current title of each seen thought that exists, by its id as
        text: the answer saved_titles() gives, from the same lookup."""
        return {str(thought.id): thought.title for thought in self.thoughts.values()}

    def by_id(self) -> dict[str, str]:
        """The ref of each seen thought that exists, by its id as text."""
        return {str(thought.id): thought.ref for thought in self.thoughts.values()}

    def note(self, filing: FilingConfig) -> str | None:
        """The seen-thoughts note, or None when no seen thought exists."""
        return seen_thoughts_note(self.seen(), filing.seen_thoughts, filing.seen_summary_chars)


async def conversation_refs(
    session: AsyncSession,
    user_id: uuid.UUID,
    messages: Sequence[Message],
    proposals: Sequence[Proposal],
) -> Refs:
    """The conversation's refs from the rows a turn loads anyway, with one
    query for the thoughts they name."""
    order = appearances(messages, proposals)
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
        )
        for row in rows
        if row.own
    }
    recent = [thought_id for thought_id in dict.fromkeys(reversed(order)) if thought_id in thoughts]
    return Refs(numbered, thoughts, recent)


def resolve_additions(parts: list[dict[str, Any]], refs: Refs) -> list[dict[str, Any]]:
    """The parts as stored: a part whose `add_to_ref` names a seen thought
    becomes an addition to it (design decision 3), with `add_to` (its id),
    `based_on` (its `updated_at`), and its current title, since an addition
    never changes the title and the model's is ignored. Any other ref makes
    the part a new thought, and is logged."""
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
                "add_to": str(target.id),
                "based_on": target.updated_at.isoformat(),
            }
        )
    return resolved
