"""Thought storage and search: thoughts in Postgres, indexed with pgvector."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


class VectorExtensionMissing(RuntimeError):
    """Postgres lacks the pgvector extension that thought search needs."""


async def check_vector_extension(connection: AsyncConnection) -> None:
    """Refuse to start on a Postgres without pgvector. SQLite is not checked."""
    if connection.dialect.name != "postgresql":
        return
    found = (
        await connection.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
    ).first()
    if found is None:
        raise VectorExtensionMissing(
            "The Postgres extension 'vector' (pgvector) is not installed in this database. "
            "Thought search needs it: use a Postgres with pgvector, such as the "
            "pgvector/pgvector image, and let the migrations create it. See docs/search.md."
        )
