from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SETUP_STATE_ID = 1


class SetupState(Base):
    """The instance's first-run setup record: one row, id 1.

    Only the migration creates the row; a missing row means setup is closed.
    token_hash is the SHA-256 hex digest of the token printed at the last
    start, never the token. completed_at is set once setup is finished.
    """

    __tablename__ = "setup_state"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    token_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
