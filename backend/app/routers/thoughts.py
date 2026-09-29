"""One stored thought and its origin, for the detail view. Editing and deleting come later."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.db import get_session
from app.models import User
from app.thoughts.store import get_thought_with_origin

router = APIRouter(prefix="/api/thoughts")


class OriginOut(BaseModel):
    conversation_id: uuid.UUID
    conversation_title: str
    archived: bool
    proposal_id: uuid.UUID
    proposed_at: datetime


class ThoughtOut(BaseModel):
    id: uuid.UUID
    title: str
    summary: str
    tags: list[str]
    category: str | None
    raw_text: str | None
    created_at: datetime
    updated_at: datetime
    # The conversation and proposal it was saved from; null when there is none,
    # or once that conversation is deleted.
    origin: OriginOut | None


@router.get("/{thought_id}", response_model=ThoughtOut)
async def read_thought(
    thought_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ThoughtOut:
    """The user's thought. Another user's, and one that does not exist, are both not_found."""
    thought, origin = await get_thought_with_origin(session, user, thought_id)
    return ThoughtOut(
        id=thought.id,
        title=thought.title,
        summary=thought.summary,
        tags=list(thought.tags or []),
        category=thought.category,
        raw_text=thought.raw_text,
        created_at=thought.created_at,
        updated_at=thought.updated_at,
        origin=OriginOut(**vars(origin)) if origin else None,
    )
