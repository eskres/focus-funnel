import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.conversation import JsonType


class Connector(Base):
    """One MCP server a user can turn on in a conversation.

    source is user (the user added it) or operator (from connectors.yaml;
    operator_key is the entry's name, url and auth stay in the config). auth
    is encrypted with "connector:<id>" as the provider id, and last4 is kept
    so listing never decrypts. tools is the list the last Test stored, each
    {name, description, input_schema, read_only_hint, available};
    tool_settings maps a tool name to {enabled, acts, always_allow}.
    """

    __tablename__ = "connectors"
    # Names are unique per user across user and operator rows.
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    operator_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    auth_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    auth_header: Mapped[str | None] = mapped_column(String(255), nullable=True)
    auth_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    auth_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    auth_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    auth_last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    tools: Mapped[list[dict[str, Any]]] = mapped_column(JsonType, nullable=False, default=list)
    tools_listed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tool_settings: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ConversationConnector(Base):
    """A connector turned on in a conversation."""

    __tablename__ = "conversation_connectors"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    connector_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("connectors.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class ToolAction(Base):
    """One call to an acts tool that waits for, or had, the user's approval.

    position is the tool message's position, tool the unprefixed tool name.
    status is pending, running, done, failed, declined, or expired. result is
    the capped text the server returned, without the data marking.
    connector_id is cleared when the connector is deleted, so the card stays.
    """

    __tablename__ = "tool_actions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    connector_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("connectors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(String(255), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JsonType, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
