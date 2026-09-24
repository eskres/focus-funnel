import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# The issuer of user rows from before auth-modes. No login produces it, so
# those rows are never matched again.
LEGACY_ISSUER = "auth0-legacy"
# The issuer of anonymous demo users; their subject is the SHA-256 hex of the
# session value, never the value itself.
DEMO_ISSUER = "demo"


class User(Base):
    __tablename__ = "users"
    # One user record per pair of issuer and subject.
    __table_args__ = (UniqueConstraint("issuer", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    # The token's "sub" claim, or the demo session hash.
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Set for demo users only: when they and their data are deleted.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    demo_notice_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
