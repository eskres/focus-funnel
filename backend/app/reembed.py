"""Rebuild users' search indexes with the configured embedding model.

Run by the operator on the server, never through the API:

  python -m app.reembed --user <user id>
  python -m app.reembed --all [--restart]

For each user it builds a new index version beside the active one, from the
thoughts in the database and with that user's own key. Search keeps using the
active index meanwhile, and stores and updates also write to the new one.
When every thought has its entries, one transaction makes the new index
active, retires the old one, and deletes the old entries. A user whose key is
missing or refused keeps the old index and is reported; the job then ends
with a failure status. Demo users and users with no thoughts are skipped.
See openspec thought-storage design decision 12.
"""

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass

import httpx2
from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.chat.usage import utc_now
from app.config import Settings, get_settings
from app.db import create_engine
from app.models import SearchIndex, Thought, ThoughtEmbedding, User
from app.thoughts.indexing import (
    ACTIVE,
    BUILDING,
    RETIRED,
    count_missing,
    embed_for_index,
    index_with_status,
    missing_thoughts,
    thought_pieces,
)

# Texts per embeddings call while rebuilding.
REBUILD_BATCH = 64
# The rebuild retries a rate limit or a server error; a search does not.
REBUILD_RETRIES = 2
# How often the final check may find thoughts stored meanwhile before giving up.
SWAP_ATTEMPTS = 3
DEMO_ISSUER = "demo"


@dataclass
class Outcome:
    user_id: uuid.UUID
    status: str  # rebuilt, skipped, or failed
    detail: str = ""

    def line(self) -> str:
        return f"{self.user_id}  {self.status}" + (f"  {self.detail}" if self.detail else "")


class RebuildFailed(Exception):
    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


async def _drop(session: AsyncSession, index: SearchIndex) -> None:
    await session.execute(delete(SearchIndex).where(SearchIndex.id == index.id))
    await session.commit()


async def _fill(
    session: AsyncSession,
    user: User,
    index: SearchIndex | None,
    settings: Settings,
    http_client: httpx2.AsyncClient | None,
) -> SearchIndex | None:
    """Embed every thought that lacks entries in the index, a batch at a time.

    With no index yet, the first batch creates the building index. Raises
    RebuildFailed with the provider's error code.
    """
    while True:
        batch = await missing_thoughts(session, user.id, index, REBUILD_BATCH)
        if not batch:
            return index
        outcome = await embed_for_index(
            session,
            user,
            index,
            [(thought.id, thought_pieces(thought)) for thought in batch],
            settings=settings,
            create_status=BUILDING,
            http_client=http_client,
            max_retries=REBUILD_RETRIES,
        )
        await session.commit()
        if outcome.error is not None:
            raise RebuildFailed(outcome.error.code)
        index = outcome.index


async def start_rebuild(
    session: AsyncSession,
    user: User,
    settings: Settings,
    *,
    restart: bool = False,
    http_client: httpx2.AsyncClient | None = None,
) -> SearchIndex:
    """Create the building index and fill it. Search still uses the active one."""
    leftover = await index_with_status(session, user.id, BUILDING)
    if leftover is not None:
        if not restart:
            raise RebuildFailed(
                "a building index is left from an earlier run; rerun with --restart"
            )
        await _drop(session, leftover)
    try:
        index = await _fill(session, user, None, settings, http_client)
    except RebuildFailed:
        building = await index_with_status(session, user.id, BUILDING)
        if building is not None:
            await _drop(session, building)
        raise
    assert index is not None  # the user has thoughts, so the first batch made it
    return index


async def finish_rebuild(
    session: AsyncSession,
    user: User,
    building: SearchIndex,
    settings: Settings,
    *,
    http_client: httpx2.AsyncClient | None = None,
) -> None:
    """Fill what was stored meanwhile, then swap the indexes in one transaction."""
    try:
        for _ in range(SWAP_ATTEMPTS):
            await _fill(session, user, building, settings, http_client)
            # Lock the user's indexes, so a store waits until the swap is done.
            await session.execute(
                select(SearchIndex.id).where(SearchIndex.user_id == user.id).with_for_update()
            )
            if await count_missing(session, user.id, building) == 0:
                break
            await session.rollback()
        else:
            raise RebuildFailed("thoughts kept arriving without entries; try again")
    except RebuildFailed:
        await session.rollback()
        await _drop(session, building)
        raise
    old = await index_with_status(session, user.id, ACTIVE)
    if old is not None:
        await session.execute(
            update(SearchIndex)
            .where(SearchIndex.id == old.id)
            .values(status=RETIRED, retired_at=utc_now())
        )
    await session.execute(
        update(SearchIndex).where(SearchIndex.id == building.id).values(status=ACTIVE)
    )
    if old is not None:
        await session.execute(delete(ThoughtEmbedding).where(ThoughtEmbedding.index_id == old.id))
    await session.commit()


async def rebuild_user(
    session: AsyncSession,
    user: User,
    settings: Settings,
    *,
    restart: bool = False,
    http_client: httpx2.AsyncClient | None = None,
) -> Outcome:
    if user.issuer == DEMO_ISSUER:
        return Outcome(user.id, "skipped", "demo user")
    has_thoughts = (
        await session.execute(select(exists().where(Thought.user_id == user.id)))
    ).scalar()
    if not has_thoughts:
        return Outcome(user.id, "skipped", "no thoughts")
    try:
        building = await start_rebuild(
            session, user, settings, restart=restart, http_client=http_client
        )
        await finish_rebuild(session, user, building, settings, http_client=http_client)
    except RebuildFailed as failure:
        return Outcome(user.id, "failed", failure.detail)
    return Outcome(
        user.id, "rebuilt", f"{building.embedding_provider} {building.embedding_model}"
    )


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.reembed",
        description="Rebuild search indexes with the configured embedding model.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--user", type=uuid.UUID, help="one user's id")
    target.add_argument("--all", action="store_true", help="every user")
    parser.add_argument(
        "--restart", action="store_true", help="replace a building index left by an earlier run"
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None, http_client: httpx2.AsyncClient | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    print(f"Embedding model: {settings.embedding_provider} {settings.embedding_model}")
    engine = create_engine(settings.database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessions() as session:
            query = select(User.id).order_by(User.created_at)
            if args.user is not None:
                query = query.where(User.id == args.user)
            user_ids = list((await session.execute(query)).scalars())
        if args.user is not None and not user_ids:
            print(f"No user with id {args.user}.", file=sys.stderr)
            return 2
        failed = 0
        for user_id in user_ids:
            async with sessions() as session:
                user = await session.get(User, user_id)
                outcome = await rebuild_user(
                    session, user, settings, restart=args.restart, http_client=http_client
                )
            print(outcome.line())
            failed += outcome.status == "failed"
        if failed:
            print(f"{failed} user(s) failed; their old index is still in use.", file=sys.stderr)
        return 1 if failed else 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
