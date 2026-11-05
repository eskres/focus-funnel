import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.conversation import JsonType


class ThoughtAddition(Base):
    """One addition to a saved thought from a later proposal.

    before holds the thought's title, summary, tags, category, and raw_text as
    they were just before the addition, so undo can restore them.
    after_updated_at is the thought's updated_at right after the addition:
    undo is refused once the thought has changed since. Deleting the
    proposal's conversation deletes the row; the thought keeps what was added.
    """

    __tablename__ = "thought_additions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    thought_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("thoughts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False
    )
    from_position: Mapped[int] = mapped_column(Integer, nullable=False)
    to_position: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    after_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    before: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
