"""Seeding and listing for the Library tests (thought-library tasks 1.1 to 1.4).

Thoughts are stored directly with a set `created_at`, so their filed order is
known; `seed_many` returns ids oldest first, and `newest_first` reverses them.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.auth import get_or_create_user
from app.models import Thought, User
from app.thoughts.library import list_thoughts
from tests.chat_helpers import run_db
from tests.conftest import TEST_ISSUER

# Noon UTC on 1 November 2026; seeded thoughts are filed before it.
FILED = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def make_user(url: str, subject: str) -> str:
    async def work(session):
        user = await get_or_create_user(session, TEST_ISSUER, subject)
        await session.commit()
        return str(user.id)

    return run_db(url, work)


def seed(url: str, user_id: str, *rows: dict) -> list[str]:
    """Store one thought per row; each row names its fields, `created_at` among them."""

    async def work(session):
        thoughts = []
        for row in rows:
            fields = {"title": "A thought", "tags": [], **row}
            fields.setdefault("summary", f"About {fields['title']}.")
            thoughts.append(Thought(user_id=uuid.UUID(user_id), **fields))
        session.add_all(thoughts)
        await session.commit()
        return [str(thought.id) for thought in thoughts]

    return run_db(url, work)


def filed_at(index: int, *, start: datetime = FILED, whole_seconds: bool = False) -> datetime:
    """The filed time of the index-th seeded thought: a minute apart, and with
    a different microsecond each unless `whole_seconds`."""
    moment = start + timedelta(minutes=index)
    if not whole_seconds:
        moment += timedelta(microseconds=1 + (index * 7919) % 999_998)
    return moment


def seed_many(
    url: str, user_id: str, count: int, *, start: datetime = FILED, whole_seconds=False, **fields
) -> list[str]:
    """`count` thoughts titled `Thought <n>`, filed in that order; ids oldest first."""
    rows = [
        {
            "title": f"Thought {index}",
            "created_at": filed_at(index, start=start, whole_seconds=whole_seconds),
            **fields,
        }
        for index in range(count)
    ]
    ids: list[str] = []
    for begin in range(0, len(rows), 500):
        ids.extend(seed(url, user_id, *rows[begin : begin + 500]))
    return ids


def newest_first(ids: list[str]) -> list[str]:
    return list(reversed(ids))


def listing(url: str, user_id: str, **options) -> dict:
    """list_thoughts() for the user, as {items: [{id, title, tags, ...}], next_cursor}."""

    async def work(session):
        user = await session.get(User, uuid.UUID(user_id))
        page = await list_thoughts(session, user, **options)
        return {
            "items": [
                {
                    "id": str(row.id),
                    "title": row.title,
                    "category": row.category,
                    "tags": list(row.tags or []),
                    "status": row.status,
                    "created_at": row.created_at,
                }
                for row in page.items
            ],
            "next_cursor": page.next_cursor,
        }

    return run_db(url, work)


def ids_of(answer: dict) -> list[str]:
    return [item["id"] for item in answer["items"]]


def titles_of(answer: dict) -> list[str]:
    return [item["title"] for item in answer["items"]]


def all_pages(fetch, limit: int = 50) -> list[dict]:
    """Every page `fetch(limit=..., cursor=...)` gives, following next_cursor."""
    pages = [fetch(limit=limit, cursor=None)]
    while pages[-1]["next_cursor"] is not None:
        assert len(pages) < 100, "paging does not end"
        pages.append(fetch(limit=limit, cursor=pages[-1]["next_cursor"]))
    return pages
