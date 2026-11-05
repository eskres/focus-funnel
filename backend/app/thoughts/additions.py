"""Additions to a saved thought: confirming one, listing them, and undoing
the last (thought-appending design decisions 7, 8, and 9).

An addition changes a thought's summary, tags, category, and raw text, never
its title or its origin. Each one leaves a thought_additions row with the
fields before it, so the newest can be undone while nothing changed since.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.raw_text import added_texts, extend_raw_text
from app.config import Settings
from app.errors import ApiError, ErrorCode
from app.models import Conversation, Message, Proposal, Thought, ThoughtAddition, User
from app.thoughts.categories import check_category
from app.thoughts.store import apply_update, thought_not_found


def target_gone() -> ApiError:
    return ApiError(
        404,
        ErrorCode.NOT_FOUND,
        "The thought this adds to no longer exists. File it as a new thought instead.",
    )


def current_fields(thought: Thought) -> dict[str, Any]:
    """The fields a card or the sheet shows, with the version a confirm sends back."""
    return {
        "id": str(thought.id),
        "title": thought.title,
        "summary": thought.summary,
        "tags": list(thought.tags or []),
        "category": thought.category,
        "updated_at": thought.updated_at.isoformat(),
    }


def thought_changed(thought: Thought, message: str) -> ApiError:
    """409 thought_changed, with the thought as it is now, so the card can
    show the current fields and confirm again against this version."""
    return ApiError(
        409, ErrorCode.THOUGHT_CHANGED, message, extra={"thought": current_fields(thought)}
    )


def parse_version(value: Any) -> datetime:
    """A thought's updated_at as the server sent it (ISO 8601)."""
    if not isinstance(value, str):
        raise ApiError(422, ErrorCode.VALIDATION_ERROR, "based_on: must be the thought's updated_at")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ApiError(
            422, ErrorCode.VALIDATION_ERROR, "based_on: must be the thought's updated_at"
        ) from None


async def lock_thought(
    session: AsyncSession, user: User, thought_id: uuid.UUID
) -> Thought | None:
    """The user's thought, locked until the transaction ends, and read afresh,
    so no edit slips in between the version check and the write."""
    return (
        await session.execute(
            select(Thought)
            .where(Thought.id == thought_id, Thought.user_id == user.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def held_to(
    session: AsyncSession, thought: Thought, conversation_id: uuid.UUID
) -> int | None:
    """The last message position the thought already holds from this
    conversation: the highest to_position of its origin proposal and of its
    additions there that are not undone. None when it holds none."""
    origin = select(Proposal.to_position).where(
        Proposal.id == thought.proposal_id, Proposal.conversation_id == conversation_id
    )
    added = (
        select(ThoughtAddition.to_position)
        .join(Proposal, Proposal.id == ThoughtAddition.proposal_id)
        .where(
            ThoughtAddition.thought_id == thought.id,
            ThoughtAddition.undone_at.is_(None),
            Proposal.conversation_id == conversation_id,
        )
    )
    both = origin.union_all(added).subquery()
    return (await session.execute(select(func.max(both.c.to_position)))).scalar_one_or_none()


async def add_to_thought(
    session: AsyncSession,
    user: User,
    thought: Thought,
    proposal: Proposal,
    messages: Sequence[Message],
    *,
    based_on: datetime,
    summary: Any,
    tags: Any,
    category: str | None,
    settings: Settings,
    http_client: httpx2.AsyncClient | None,
) -> ThoughtAddition:
    """Apply one addition to a thought the caller locked, without committing
    (design decision 7, steps 2 to 6).

    Refused with thought_changed when the thought changed after `based_on`,
    the version the card was built from. The title and origin stay; the raw
    text grows by the proposal's messages the thought does not hold yet.
    An embedding failure does not fail it: search finds it by words at once.
    """
    if thought.updated_at != based_on:
        raise thought_changed(
            thought,
            "The thought changed after this addition was proposed. "
            "Review its current version and add again.",
        )
    category = await check_category(session, user, category, keep=thought.category)
    before = {
        "title": thought.title,
        "summary": thought.summary,
        "tags": list(thought.tags or []),
        "category": thought.category,
        "raw_text": thought.raw_text,
    }
    texts = added_texts(
        messages,
        from_position=proposal.from_position,
        to_position=proposal.to_position,
        held_to=await held_to(session, thought, proposal.conversation_id),
    )
    await apply_update(
        session,
        user,
        thought,
        summary=summary,
        tags=tags,
        category=category,
        raw_text=extend_raw_text(thought.raw_text, texts, datetime.now(UTC).date()),
        settings=settings,
        conversation_id=proposal.conversation_id,
        http_client=http_client,
    )
    # The update expired updated_at; read the version the addition leaves.
    await session.refresh(thought, ["updated_at"])
    addition = ThoughtAddition(
        id=uuid.uuid4(),
        thought_id=thought.id,
        user_id=user.id,
        proposal_id=proposal.id,
        from_position=proposal.from_position,
        to_position=proposal.to_position,
        after_updated_at=thought.updated_at,
        before=before,
    )
    session.add(addition)
    await session.flush()
    return addition


@dataclass(frozen=True)
class AdditionOut:
    """One addition as the detail view lists it."""

    id: uuid.UUID
    added_at: datetime
    undone: bool
    conversation_id: uuid.UUID
    conversation_title: str
    proposal_id: uuid.UUID


async def list_additions(
    session: AsyncSession, user: User, thought_id: uuid.UUID
) -> list[AdditionOut]:
    """The thought's additions, newest first, each with its conversation's
    current title, in one query. Deleting a conversation deletes its
    additions, so they are not listed."""
    rows = await session.execute(
        select(ThoughtAddition, Conversation.id, Conversation.title)
        .join(Proposal, Proposal.id == ThoughtAddition.proposal_id)
        .join(Conversation, Conversation.id == Proposal.conversation_id)
        .where(
            ThoughtAddition.thought_id == thought_id,
            ThoughtAddition.user_id == user.id,
            Conversation.user_id == user.id,
        )
        .order_by(ThoughtAddition.added_at.desc(), ThoughtAddition.to_position.desc())
    )
    return [
        AdditionOut(
            id=addition.id,
            added_at=addition.added_at,
            undone=addition.undone_at is not None,
            conversation_id=conversation_id,
            conversation_title=title,
            proposal_id=addition.proposal_id,
        )
        for addition, conversation_id, title in rows
    ]


async def proposal_additions(
    session: AsyncSession, user: User, proposal_ids: Sequence[uuid.UUID]
) -> dict[tuple[str, str], bool]:
    """Whether each addition made from these proposals is undone, by
    (proposal id, thought id) as text, in one query."""
    if not proposal_ids:
        return {}
    rows = await session.execute(
        select(
            ThoughtAddition.proposal_id, ThoughtAddition.thought_id, ThoughtAddition.undone_at
        ).where(
            ThoughtAddition.proposal_id.in_(list(proposal_ids)),
            ThoughtAddition.user_id == user.id,
        )
    )
    return {
        (str(proposal_id), str(thought_id)): undone_at is not None
        for proposal_id, thought_id, undone_at in rows
    }


async def undo_addition(
    session: AsyncSession,
    user: User,
    thought_id: uuid.UUID,
    addition_id: uuid.UUID,
    *,
    settings: Settings,
    http_client: httpx2.AsyncClient | None = None,
) -> None:
    """Restore the fields the thought had before this addition, and commit
    (design decision 9).

    Another user's thought, and an addition that is not this thought's, are
    not_found. Refused with thought_changed unless the addition is the
    thought's newest not undone and the thought has not changed since. The
    proposal part keeps its thought_id, so the proposal is not offered again.
    """
    thought = await lock_thought(session, user, thought_id)
    if thought is None:
        raise thought_not_found()
    addition = (
        await session.execute(
            select(ThoughtAddition).where(
                ThoughtAddition.id == addition_id,
                ThoughtAddition.thought_id == thought.id,
                ThoughtAddition.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if addition is None:
        raise ApiError(404, ErrorCode.NOT_FOUND, "No such addition.")
    newest = (
        await session.execute(
            select(ThoughtAddition.id)
            .where(ThoughtAddition.thought_id == thought.id, ThoughtAddition.undone_at.is_(None))
            .order_by(ThoughtAddition.added_at.desc(), ThoughtAddition.to_position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if newest != addition.id:
        raise thought_changed(
            thought,
            "Only the last addition that is not undone can be undone.",
        )
    if thought.updated_at != addition.after_updated_at:
        raise thought_changed(
            thought,
            "The thought changed after this addition, so it can no longer be undone.",
        )
    before = addition.before
    await apply_update(
        session,
        user,
        thought,
        title=before.get("title", thought.title),
        summary=before.get("summary", thought.summary),
        tags=before.get("tags", []),
        category=before.get("category"),
        raw_text=before.get("raw_text"),
        settings=settings,
        http_client=http_client,
    )
    addition.undone_at = func.now()
    await session.commit()
