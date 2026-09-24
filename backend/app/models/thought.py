import uuid
from datetime import datetime

from pgvector.sqlalchemy import HALFVEC
from sqlalchemy import (
    DDL,
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Thought storage and search run on Postgres. These variants let the rest of
# the test suite create every table on SQLite.
TagsType = ARRAY(Text).with_variant(JSON(), "sqlite")
TsVectorType = TSVECTOR().with_variant(Text(), "sqlite")
# Half precision halves what a search reads and does not change the cosine
# ranking in any way that matters. No fixed dimension: indexes built with
# different models share the table.
VectorType = HALFVEC().with_variant(JSON(), "sqlite")
# Marks an index that exists only on Postgres, so Alembic's comparison skips
# it on SQLite (see alembic/env.py).
POSTGRES_ONLY = {"only_dialect": "postgresql"}


class Thought(Base):
    """A filed thought. Postgres is its source of truth.

    search_tsv holds the words search matches on: title and tags weighted A,
    summary B, raw text C. The store operation writes it with the row.
    """

    __tablename__ = "thoughts"
    __table_args__ = (
        Index("ix_thoughts_user_id_created_at", "user_id", "created_at"),
        Index(
            "ix_thoughts_tags", "tags", postgresql_using="gin", info=POSTGRES_ONLY
        ).ddl_if(dialect="postgresql"),
        Index(
            "ix_thoughts_search_tsv", "search_tsv", postgresql_using="gin", info=POSTGRES_ONLY
        ).ddl_if(dialect="postgresql"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(TagsType, nullable=False, default=list)
    # Only the database reads it, so it is not loaded with the row.
    search_tsv: Mapped[str | None] = mapped_column(TsVectorType, nullable=True, deferred=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SearchIndex(Base):
    """One version of a user's search index, and the model that built it.

    status is building, active, or retired. A user has at most one active and
    one building index. Store and search use this row's provider and model,
    never the current setting.
    """

    __tablename__ = "search_indexes"
    __table_args__ = (
        UniqueConstraint("user_id", "version", name="uq_search_indexes_user_id_version"),
        Index(
            "uq_search_indexes_one_active",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
        Index(
            "uq_search_indexes_one_building",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'building'"),
            sqlite_where=text("status = 'building'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    # The `dimensions` asked of the model, if any; every later call asks the same.
    requested_dimensions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ThoughtEmbedding(Base):
    """One embedded piece of a thought in one search index.

    chunk 0 is the head (title, tags, summary); 1 and up are raw-text chunks,
    with their character range in the raw text for excerpts.
    """

    __tablename__ = "thought_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "index_id", "thought_id", "chunk", name="uq_thought_embeddings_index_thought_chunk"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    index_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("search_indexes.id", ondelete="CASCADE"), nullable=False
    )
    thought_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("thoughts.id", ondelete="CASCADE"), nullable=False
    )
    chunk: Mapped[int] = mapped_column(Integer, nullable=False)
    start_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(VectorType, nullable=False)


# Keep vectors in the row rather than in a TOAST table, so an exact search
# does not fetch each one separately. A vector too large for the row (above
# about 4,000 dimensions at half precision) is still moved out.
EMBEDDING_STORAGE = "ALTER TABLE thought_embeddings ALTER COLUMN embedding SET STORAGE MAIN"
event.listen(
    ThoughtEmbedding.__table__,
    "after_create",
    DDL(EMBEDDING_STORAGE).execute_if(dialect="postgresql"),
)
