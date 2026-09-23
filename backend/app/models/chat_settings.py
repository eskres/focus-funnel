import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ChatModel(Base):
    """One model in a user's loadout. The limit of five is enforced in code."""

    __tablename__ = "chat_models"
    __table_args__ = (UniqueConstraint("user_id", "provider_id", "model"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)


class UserSettings(Base):
    """Chat settings for one user: temperature and the usage warning."""

    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    warning_unit: Mapped[str | None] = mapped_column(String(8), nullable=True)
    warning_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    # "YYYY-MM" of the last month a usage warning was sent.
    warning_notified_month: Mapped[str | None] = mapped_column(String(7), nullable=True)
