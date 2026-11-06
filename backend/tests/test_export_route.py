"""GET /api/me/export (thought-export task 2.4, design decisions 1, 6, 7, 8,
and 12)."""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import Conversation, Message, Proposal, Thought, UsageEvent, User
from tests.export_helpers import (
    SENTINELS,
    assert_no_sentinel_logged,
    export_records,
    seed_everything,
    seed_plain,
    seed_sentinel_thoughts,
    updated_times,
)

ZEBRA = "ZEBRA-SENTINEL-42"
THOUGHT_KEYS = {
    "id", "title", "summary", "tags", "category", "raw_text", "status", "status_changed_at",
    "when", "created_at", "updated_at", "origin", "additions",
}  # fmt: skip


async def export_of(api, format="json", headers=None):
    return await api.http.get(
        "/api/me/export", params={"format": format}, headers=headers or api.headers
    )


def thoughts_of(response) -> list[dict]:
    return response.json()["thoughts"]


@pytest.mark.postgres
async def test_the_json_answer(async_api, export_now):
    api = async_api
    user_id = await api.user_id()
    ids = await seed_everything(api, user_id)
    [plain_id] = await seed_plain(api, user_id, 1)
    response = await export_of(api)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="focus-funnel-thoughts-2026-11-05.json"'
    )
    assert response.headers["cache-control"] == "no-store"
    document = response.json()
    assert document["exported_at"] == "2026-11-05T14:03:00Z"
    assert document["count"] == 2
    by_id = {item["id"]: item for item in thoughts_of(response)}
    for item in by_id.values():
        assert set(item) == THOUGHT_KEYS

    # The same thought as the single-thought API answers it.
    single = await api.http.get(f"/api/thoughts/{ids['thought']}", headers=api.headers)
    assert single.status_code == 200
    everything = by_id[str(ids["thought"])]
    assert everything == single.json()
    assert everything["status"] == "done" and everything["category"] == "task"
    assert everything["when"] == {
        "start": "2026-11-09",
        "end": None,
        "time_zone": "Europe/Oslo",
    }
    assert everything["origin"]["conversation_title"] == "Weekend plans"
    assert [a["conversation_title"] for a in everything["additions"]] == [
        "Plumber chat"
    ] * 2

    plain = by_id[str(plain_id)]
    assert plain["origin"] is None
    assert plain["when"] is None
    assert plain["raw_text"] is None
    assert plain["additions"] == []
    assert plain["status"] == "open"
    assert plain["status_changed_at"] is None


@pytest.mark.postgres
async def test_the_markdown_answer(async_api, export_now):
    api = async_api
    user_id = await api.user_id()
    await seed_everything(api, user_id)
    response = await export_of(api, "markdown")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/markdown; charset=utf-8"
    assert response.headers["content-disposition"] == (
        'attachment; filename="focus-funnel-thoughts-2026-11-05.md"'
    )
    assert response.headers["cache-control"] == "no-store"
    assert response.text.startswith(
        "# Focus Funnel thoughts\n\nExported 2026-11-05 14:03 UTC."
    )
    assert "## Call the plumber" in response.text
    assert response.text.endswith("End of export: 1 thought.\n")


@pytest.mark.postgres
async def test_nothing_the_assistant_wrote_is_exported(async_api):
    api = async_api
    user_id = await api.user_id()

    async def work(session):
        conversation = Conversation(user_id=user_id, title="Shopping")
        session.add(conversation)
        await session.flush()
        session.add_all(
            [
                Message(
                    conversation_id=conversation.id,
                    position=0,
                    role="user",
                    content="buy milk",
                ),
                Message(
                    conversation_id=conversation.id,
                    position=1,
                    role="assistant",
                    content=f"Sure, {ZEBRA}.",
                ),  # fmt: skip
            ]
        )
        proposal = Proposal(
            conversation_id=conversation.id, user_id=user_id, position=1,
            from_position=0, to_position=0, raw_text=f"buy milk {ZEBRA}",
            parts=[{"title": f"Milk {ZEBRA}", "summary": ZEBRA}],
        )  # fmt: skip
        session.add(proposal)
        await session.flush()
        session.add(
            Thought(
                user_id=user_id,
                title="Buy milk",
                summary="Buy milk today.",
                tags=["food"],
                raw_text="buy milk",
                proposal_id=proposal.id,
            )  # fmt: skip
        )
        await session.commit()

    await api.db(work)
    for format in ("json", "markdown"):
        response = await export_of(api, format)
        assert response.status_code == 200
        assert "Buy milk" in response.text
        assert ZEBRA not in response.text


@pytest.mark.postgres
@pytest.mark.parametrize("params", [{"format": "csv"}, {}])
async def test_a_bad_or_missing_format_is_refused(async_api, params):
    response = await async_api.http.get(
        "/api/me/export", params=params, headers=async_api.headers
    )
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert "format" in error["message"]
    assert "content-disposition" not in response.headers


@pytest.mark.postgres
async def test_no_token_is_refused(async_api):
    response = await async_api.http.get("/api/me/export", params={"format": "json"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert "content-disposition" not in response.headers


@pytest.mark.postgres
async def test_a_demo_visitor_exports_their_own_thoughts(demo_visitor):
    visitor = demo_visitor
    visitor_id = await visitor.user_id()
    await seed_plain(visitor, visitor_id, 2)

    async def other(session):
        user = User(
            issuer="demo",
            subject="b" * 64,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        session.add(user)
        await session.commit()
        return user.id

    await seed_everything(visitor, await visitor.db(other))
    response = await export_of(visitor)
    assert response.status_code == 200
    document = response.json()
    assert document["count"] == 2
    assert [item["title"] for item in document["thoughts"]] == [
        "Thought 0",
        "Thought 1",
    ]


@pytest.mark.postgres
async def test_exporting_changes_nothing(async_api, caplog):
    caplog.set_level(logging.INFO, logger="app.thoughts.export")
    api = async_api
    user_id = await api.user_id()
    await seed_everything(api, user_id)
    await seed_sentinel_thoughts(api, user_id, 3)
    before = await updated_times(api, user_id)

    async def usage(session):
        return (
            await session.execute(select(func.count()).select_from(UsageEvent))
        ).scalar_one()

    usage_before = await api.db(usage)
    json_answer = await export_of(api)
    markdown_answer = await export_of(api, "markdown")
    assert json_answer.status_code == markdown_answer.status_code == 200
    assert all(sentinel in json_answer.text for sentinel in SENTINELS)
    assert await updated_times(api, user_id) == before
    assert await api.db(usage) == usage_before
    assert export_records(caplog) == [
        f"export ended user={user_id} format=json thoughts=4 outcome=complete",
        f"export ended user={user_id} format=markdown thoughts=4 outcome=complete",
    ]
    assert_no_sentinel_logged(caplog)


async def test_a_demo_export_on_sqlite_compares_the_naive_expiry(
    demo_visitor, export_now
):
    """SQLite hands back a naive expires_at; the lease compares it with the
    aware demo clock without error (design decision 12)."""
    visitor = demo_visitor
    visitor_id = await visitor.user_id()
    await seed_plain(visitor, visitor_id, 3)
    response = await export_of(visitor)
    assert response.status_code == 200, response.text
    assert response.text.endswith('],"count":3}\n')
    assert json.loads(response.text)["count"] == 3
    assert uuid.UUID(response.json()["thoughts"][0]["id"])
