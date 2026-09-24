"""Thought storage and search: thoughts in Postgres, indexed with pgvector."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


# halfvec, which stores the search vectors, arrived in pgvector 0.7.
MIN_PGVECTOR = (0, 7)


def _version(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split(".")[:2] if part.isdigit())


class VectorExtensionMissing(RuntimeError):
    """Postgres lacks the pgvector extension that thought search needs."""


async def check_vector_extension(connection: AsyncConnection) -> None:
    """Refuse to start on a Postgres without pgvector. SQLite is not checked."""
    if connection.dialect.name != "postgresql":
        return
    version = (
        await connection.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
    ).scalar()
    if version is None:
        raise VectorExtensionMissing(
            "The Postgres extension 'vector' (pgvector) is not installed in this database. "
            "Thought search needs it: use a Postgres with pgvector, such as the "
            "pgvector/pgvector image, and let the migrations create it. See docs/search.md."
        )
    if _version(version) < MIN_PGVECTOR:
        raise VectorExtensionMissing(
            f"The Postgres extension 'vector' is version {version}; thought search needs "
            f"{'.'.join(map(str, MIN_PGVECTOR))} or later for half-precision vectors. "
            "Upgrade pgvector and run ALTER EXTENSION vector UPDATE. See docs/search.md."
        )
