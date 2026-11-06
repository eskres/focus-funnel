"""The export at scale: 10,000 thoughts with flat memory, no temp file, and
no provider call (thought-export task 2.7, design decision 2)."""

import json
import os
import tempfile
import tracemalloc
import uuid

import pytest
from sqlalchemy import text

from app.db import get_sessionmaker
from app.thoughts.export import (
    Lease,
    export_thoughts,
    json_chunks,
    markdown_chunks,
    utcnow,
)
from tests.export_helpers import thoughts_queries
from tests.thought_helpers import counted_queries

pytestmark = pytest.mark.postgres

COUNT = 10_000
RAW_LENGTH = 2_000


async def seed_store(api, user_id: uuid.UUID) -> None:
    """10,000 thoughts in one INSERT … SELECT, each filed a millisecond apart."""

    async def work(session):
        await session.execute(
            text(
                "INSERT INTO thoughts (id, user_id, title, summary, raw_text, tags, status, "
                "created_at, updated_at) "
                "SELECT gen_random_uuid(), :user_id, 'Thought ' || n, 'About thought ' || n || '.', "
                "rpad('raw text ' || n || ' ', :length, 'abcdefghij'), ARRAY[]::text[], 'open', "
                "now() - n * interval '1 millisecond', now() "
                "FROM generate_series(1, :count) AS n"
            ),
            {"user_id": user_id, "length": RAW_LENGTH, "count": COUNT},
        )
        await session.commit()

    await api.db(work)


async def other_users_thought(api) -> str:
    from app.models import Thought, User

    async def work(session):
        user = User(issuer="https://login.focus-funnel.test", subject="user|other")
        session.add(user)
        await session.flush()
        session.add(
            Thought(
                user_id=user.id,
                title="OTHER-USERS-THOUGHT",
                summary="Not Alice's.",
                tags=[],
            )
        )
        await session.commit()

    await api.db(work)
    return "OTHER-USERS-THOUGHT"


async def run(writer, user_id) -> tuple[int, int, int, bytes | None]:
    """Iterate the writer chunk by chunk, dropping each. Returns the bytes
    produced, the traced peak, the thoughts queries run when the first chunk
    holding a thought arrived, and the last chunk."""
    lease = Lease(user_id=user_id, format="json", written_at=0.0)
    produced = 0
    first_queries = None
    last = None
    with counted_queries() as statements:
        tracemalloc.start()
        try:
            async for chunk in writer(
                export_thoughts(get_sessionmaker(), user_id, lease), utcnow()
            ):
                data = chunk.encode()
                produced += len(data)
                if first_queries is None and "Thought " in chunk:
                    first_queries = len(thoughts_queries(statements))
                last = data
                del chunk, data
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    return produced, peak, first_queries, last


async def test_ten_thousand_thoughts(async_api):
    api = async_api
    user_id = await api.user_id()
    other = await other_users_thought(api)
    await seed_store(api, user_id)
    temp = tempfile.gettempdir()
    temp_before = set(os.listdir(temp))

    for writer in (json_chunks, markdown_chunks):
        produced, peak, first_queries, last = await run(writer, user_id)
        print(f"{writer.__name__}: produced {produced} bytes, traced peak {peak} bytes")
        assert produced > COUNT * RAW_LENGTH
        assert first_queries == 1, writer
        assert peak < produced / 5, (writer.__name__, peak, produced)
        if writer is json_chunks:
            assert last.endswith(b'],"count":10000}\n')
        else:
            assert last == b"End of export: 10000 thoughts.\n"

    # Through the route, with no provider key: complete, and only Alice's.
    response = await api.http.get(
        "/api/me/export", params={"format": "json"}, headers=api.headers
    )
    assert response.status_code == 200
    document = json.loads(response.content)
    assert document["count"] == COUNT
    assert len(document["thoughts"]) == COUNT
    assert other not in response.text

    # With a key saved, the provider gets no request during the export.
    await api.ready()
    asked = len(api.fake.requests)
    response = await api.http.get(
        "/api/me/export", params={"format": "markdown"}, headers=api.headers
    )
    assert response.status_code == 200
    assert response.text.endswith("End of export: 10000 thoughts.\n")
    assert len(api.fake.requests) == asked
    assert set(os.listdir(temp)) == temp_before
