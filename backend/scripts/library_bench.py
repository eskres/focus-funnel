"""Time the Library list's SQL for a user with 5,000 thoughts (thought-library task 1.5).

Seeds 10 users with --thoughts thoughts each, with titles and tags drawn as
search_bench.py draws them, categories, statuses, and an explicit created_at:
one distinct time per thought, spread over two years (search_bench's seed()
leaves it to now(), one time for the whole transaction). Every user has the
same categories, tags and statuses, and each user's 5 oldest thoughts carry
the rare tag, so the tag index and the status filter meet other users' rows.

It then times the database part of list_thoughts() for one of the users,
--runs times per case: the first page, the last page (by its cursor), a
category, the rare tag, status=done with the seeded statuses, status=done
after a reseed in which only each user's oldest 1% are done, and a one-month
filed range. It prints each case's 95th percentile, row count, and EXPLAIN
plan. The target in the spec is a 95th percentile under 50 ms.

Run from backend/ against a Postgres with pgvector. The script creates a
scratch database next to the one in the URL and drops it afterwards:

  uv run python -m scripts.library_bench \\
      --database-url postgresql+asyncpg://focus_funnel:focus_funnel@localhost:55432/focus_funnel
"""

import argparse
import asyncio
import math
import random
import statistics
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Thought, User
from app.thoughts.library import decode_cursor, library_query, list_thoughts
from scripts.search_bench import draw, sentence
from scripts.search_eval import with_scratch_database

USERS = 10
RARE_TAG = "rare-tag"
RARE_COUNT = 5
CATEGORIES = ["task", "idea", "note", "event", "reference", "journal", None]
SPAN = timedelta(days=730)
END = datetime(2026, 11, 1, tzinfo=UTC)
ZONE = ZoneInfo("Europe/Oslo")


async def seed(session: AsyncSession, per_user: int, rng: random.Random) -> list[User]:
    users = [User(issuer="library-bench", subject=uuid.uuid4().hex) for _ in range(USERS)]
    session.add_all(users)
    await session.flush()
    step = SPAN / per_user
    for user_number, user in enumerate(users):
        rows = []
        for number in range(per_user):
            # Oldest first; each user's times are offset so no two thoughts share one.
            created_at = END - SPAN + step * number + timedelta(microseconds=user_number * 1000 + 1)
            tags = draw(rng, 2)
            if number < RARE_COUNT:
                tags.append(RARE_TAG)
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "user_id": user.id,
                    "title": sentence(rng, 3),
                    "summary": sentence(rng, 18),
                    "tags": tags,
                    "category": rng.choice(CATEGORIES),
                    "status": "done" if rng.random() < 0.3 else "open",
                    "created_at": created_at,
                }
            )
        for start in range(0, len(rows), 1000):
            await session.execute(insert(Thought), rows[start : start + 1000])
    await session.commit()
    await session.execute(text("ANALYZE"))
    return users


async def only_oldest_done(session: AsyncSession, users: list[User], per_user: int) -> None:
    """Reseed the statuses: only each user's oldest 1% are done."""
    count = per_user // 100
    await session.execute(update(Thought).values(status="open"))
    for user in users:
        oldest = (
            select(Thought.id)
            .where(Thought.user_id == user.id)
            .order_by(Thought.created_at)
            .limit(count)
            .scalar_subquery()
        )
        await session.execute(update(Thought).where(Thought.id.in_(oldest)).values(status="done"))
    await session.commit()
    await session.execute(text("ANALYZE"))


async def explain(session: AsyncSession, user: User, options: dict) -> str:
    query = library_query(user, **options)
    compiled = query.compile(dialect=postgresql.asyncpg.dialect())
    params = tuple(compiled.params[name] for name in compiled.positiontup)
    connection = await session.connection()
    result = await connection.exec_driver_sql("EXPLAIN " + compiled.string, params)
    return "\n".join("    " + row[0] for row in result)


async def last_page_cursor(session: AsyncSession, user: User):
    """The cursor that leads to the last page, found by paging through."""
    cursor = None
    previous = None
    while True:
        page = await list_thoughts(session, user, cursor=cursor)
        if page.next_cursor is None:
            return previous
        previous = cursor = decode_cursor(page.next_cursor)


async def time_case(session, user, runs, options) -> tuple[float, int, list[float]]:
    timings = []
    rows = 0
    for number in range(runs + 5):
        started = time.perf_counter()
        page = await list_thoughts(session, user, **options)
        elapsed = (time.perf_counter() - started) * 1000
        rows = len(page.items)
        session.expunge_all()
        if number >= 5:  # the first few warm the caches
            timings.append(elapsed)
    ordered = sorted(timings)
    return ordered[math.ceil(0.95 * len(ordered)) - 1], rows, timings


async def bench(session: AsyncSession, args) -> bool:
    rng = random.Random(args.seed)
    started = time.monotonic()
    users = await seed(session, args.thoughts, rng)
    user = users[args.seed % USERS]
    server = (await session.execute(text("SHOW server_version"))).scalar()
    print(f"Postgres {server}.")
    print(f"Seeded {USERS} users x {args.thoughts} thoughts in {time.monotonic() - started:.0f} s.")
    distinct = (
        await session.execute(
            select(func.count(func.distinct(Thought.created_at))).where(Thought.user_id == user.id)
        )
    ).scalar_one()
    print(f"Distinct created_at values among the benched user's thoughts: {distinct}.")

    last = await last_page_cursor(session, user)
    month_from = (END - timedelta(days=200)).date().replace(day=1)
    month_to = (month_from + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    cases: list[tuple[str, dict]] = [
        ("first page", {}),
        ("last page", {"cursor": last}),
        ("category task", {"category": "task"}),
        (f"rare tag ({RARE_TAG})", {"tag": RARE_TAG}),
        ("status=done (seeded)", {"status": "done"}),
        ("status=done (oldest 1% done)", {"status": "done"}),
        (
            f"filed {month_from} to {month_to}",
            {"filed_from": month_from, "filed_to": month_to, "zone": ZONE},
        ),
    ]
    ok = True
    for name, options in cases:
        if name.startswith("status=done (oldest"):
            await only_oldest_done(session, users, args.thoughts)
        p95, rows, timings = await time_case(session, user, args.runs, options)
        plan = await explain(session, user, options)
        owner_scoped = "ix_thoughts_user_id_created_at" in plan or "user_id = " in plan
        passed = p95 < 50 and owner_scoped
        ok = ok and passed
        print(
            f"\n{name}: {rows} rows; median {statistics.median(timings):.2f} ms, "
            f"95th percentile {p95:.2f} ms, max {max(timings):.2f} ms "
            f"({'pass' if passed else 'fail'})"
        )
        print(f"  plan scans ix_thoughts_user_id_created_at or filters on user_id: {owner_scoped}")
        print(plan)
    return ok


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--thoughts", type=int, default=5000)
    parser.add_argument("--runs", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    ok = await with_scratch_database(args.database_url, lambda session: bench(session, args))
    print(
        "\nTarget: 95th percentile under 50 ms and an owner-scoped plan for every case: "
        f"{'pass' if ok else 'fail'}."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
