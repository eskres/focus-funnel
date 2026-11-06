"""export_thoughts(): keyset batches, each in its own short REPEATABLE READ
session, the lease checks, and what the queries read (thought-export task
2.1, design decisions 2, 3, and 15)."""

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import demo
from app.db import create_engine
from app.models import Conversation, Proposal, Thought, ThoughtAddition, User
from app.thoughts import export
from app.thoughts.export import ExportAborted, Lease, export_thoughts
from tests.export_helpers import (
    BASE,
    additions_queries,
    listen_after,
    seed_everything,
    thoughts_queries,
)
from tests.thought_helpers import counted_queries

pytestmark = pytest.mark.postgres


class Store:
    """The test database through one pooled engine, with `db()` as the
    export helpers expect."""

    def __init__(self, url: str):
        self.engine = create_engine(url)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def db(self, work):
        async with self.sessions() as session:
            return await work(session)

    async def user(self, subject: str) -> uuid.UUID:
        async def work(session):
            user = User(issuer="https://login.focus-funnel.test", subject=subject)
            session.add(user)
            await session.commit()
            return user.id

        return await self.db(work)

    async def thoughts(self, user_id, *created: datetime, **fields) -> list[uuid.UUID]:
        async def work(session):
            rows = [
                Thought(
                    user_id=user_id,
                    title=f"Thought {index}",
                    summary=f"About {index}.",
                    tags=[],
                    created_at=moment,
                    **fields,
                )
                for index, moment in enumerate(created)
            ]
            session.add_all(rows)
            await session.commit()
            return [row.id for row in rows]

        return await self.db(work)


@pytest.fixture
async def store(test_database_url):
    store = Store(test_database_url)
    yield store
    await store.engine.dispose()


def new_lease(user_id, expires_at=None) -> Lease:
    return Lease(user_id=user_id, format="json", written_at=0.0, expires_at=expires_at)


async def collect(store, user_id, lease=None) -> list[list]:
    lease = lease or new_lease(user_id)
    return [batch async for batch in export_thoughts(store.sessions, user_id, lease)]


def minutes(*offsets: int) -> list[datetime]:
    return [BASE + timedelta(minutes=offset) for offset in offsets]


async def test_batches_run_oldest_first_with_ties_by_id(store, batch_of_two):
    alice = await store.user("alice")
    # Three share one filing time; one is older and one newer.
    ids = await store.thoughts(alice, *minutes(5, 1, 3, 3, 3))
    batches = await collect(store, alice)
    assert [len(batch) for batch in batches] == [2, 2, 1]
    got = [thought.id for batch in batches for thought in batch]
    ties = sorted(ids[2:5])
    assert got == [ids[1], *ties, ids[0]]
    assert len(set(got)) == 5


async def test_a_full_last_batch_ends_after_one_more_thoughts_query(
    store, batch_of_two
):
    alice = await store.user("alice")
    await store.thoughts(alice, *minutes(1, 2, 3, 4))
    batches = export_thoughts(store.sessions, alice, new_lease(alice))
    assert len(await anext(batches)) == 2
    assert len(await anext(batches)) == 2
    with counted_queries() as statements:
        with pytest.raises(StopAsyncIteration):
            await anext(batches)
    assert len(thoughts_queries(statements)) == 1
    assert additions_queries(statements) == []


async def test_no_thoughts_yield_nothing(store):
    alice = await store.user("alice")
    assert await collect(store, alice) == []


async def test_each_batch_runs_two_selects_in_its_own_session(store, batch_of_two):
    alice = await store.user("alice")
    await store.thoughts(alice, *minutes(1, 2, 3, 4, 5))
    pool_events: list[str] = []
    event.listen(
        store.engine.sync_engine, "checkout", lambda *a: pool_events.append("checkout")
    )
    event.listen(
        store.engine.sync_engine, "checkin", lambda *a: pool_events.append("checkin")
    )
    batches = export_thoughts(store.sessions, alice, new_lease(alice))
    for size in (2, 2, 1):
        pool_events.clear()
        with counted_queries() as statements:
            assert len(await anext(batches)) == size
        selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
        assert len(selects) == 2, statements
        assert (
            len(thoughts_queries(selects)) == 1 and len(additions_queries(selects)) == 1
        )
        # The batch's session was opened and closed before it was yielded.
        assert pool_events == ["checkout", "checkin"]
    with pytest.raises(StopAsyncIteration):
        await anext(batches)


async def test_a_batch_reads_one_snapshot(store, monkeypatch, batch_of_two):
    """Both queries of a batch run at REPEATABLE READ: an addition committed
    between them is not seen, nor its text (design decision 2).

    The batch's thoughts, `raw_text` included, are loaded by the thoughts
    query before the addition is committed, so their `raw_text` would read
    "first words" at any isolation level. The text half is therefore checked
    by reading `raw_text` again in the batch's own session after the commit:
    only the batch's snapshot keeps it at "first words"."""
    alice = await store.user("alice")
    [first, second] = await store.thoughts(
        alice, *minutes(1, 2), raw_text="first words"
    )

    async def add_conversation(session):
        conversation = Conversation(user_id=alice, title="Later chat")
        session.add(conversation)
        await session.flush()
        proposal = Proposal(
            conversation_id=conversation.id, user_id=alice, position=1,
            from_position=0, to_position=0, raw_text="added words", parts=[],
        )  # fmt: skip
        session.add(proposal)
        await session.commit()
        return proposal.id

    proposal_id = await store.db(add_conversation)
    seen: list[str] = []
    reread: list[str] = []
    real = export.additions_for

    async def wrapped(session, user_id, thought_ids):
        seen.append(
            (await session.execute(text("SHOW transaction_isolation"))).scalar_one()
        )

        async def add(other):
            other.add(
                ThoughtAddition(
                    thought_id=first,
                    user_id=alice,
                    proposal_id=proposal_id,
                    from_position=0,
                    to_position=0,
                    after_updated_at=datetime.now(UTC),
                    before={},
                )  # fmt: skip
            )
            await other.execute(
                update(Thought)
                .where(Thought.id == first)
                .values(raw_text="first words\n\nadded words")
            )
            await other.commit()

        await store.db(add)
        reread.append(
            (
                await session.execute(
                    select(Thought.raw_text).where(Thought.id == first)
                )
            ).scalar_one()
        )
        return await real(session, user_id, thought_ids)

    monkeypatch.setattr(export, "additions_for", wrapped)
    [batch] = await collect(store, alice)
    assert seen == ["repeatable read"]
    by_id = {thought.id: thought for thought in batch}
    assert by_id[first].additions == [] and by_id[second].additions == []
    assert by_id[first].raw_text == "first words"
    assert reread == ["first words"]


async def test_an_abort_after_a_batch_stops_before_the_next_query(store, batch_of_two):
    alice = await store.user("alice")
    await store.thoughts(alice, *minutes(1, 2, 3, 4, 5))
    lease = new_lease(alice)
    batches = export_thoughts(store.sessions, alice, lease)
    await anext(batches)
    lease.aborted = True
    with counted_queries() as statements:
        with pytest.raises(ExportAborted):
            await anext(batches)
    assert statements == []


async def test_an_abort_during_the_thoughts_query_yields_nothing_more(
    store, batch_of_two
):
    alice = await store.user("alice")
    await store.thoughts(alice, *minutes(1, 2, 3, 4, 5))
    lease = new_lease(alice)
    batches = export_thoughts(store.sessions, alice, lease)
    await anext(batches)
    seen: list[str] = []

    def hook(statement):
        if thoughts_queries([statement]):
            seen.append(statement)
            lease.aborted = True

    remove = listen_after(hook)
    try:
        with counted_queries() as statements:
            with pytest.raises(ExportAborted):
                await anext(batches)
    finally:
        remove()
    assert len(seen) == 1
    # The additions query of that batch never ran.
    assert additions_queries(statements) == []


async def test_the_last_check_after_the_only_batch(store, monkeypatch):
    alice = await store.user("alice")
    await store.thoughts(alice, *minutes(1, 2, 3))

    # Aborted while the only batch is sent.
    lease = new_lease(alice)
    batches = export_thoughts(store.sessions, alice, lease)
    assert len(await anext(batches)) == 3
    lease.aborted = True
    with counted_queries() as statements:
        with pytest.raises(ExportAborted):
            await anext(batches)
    assert statements == []

    # A demo session that ended meanwhile.
    end = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
    monkeypatch.setattr(demo, "now", lambda: end - timedelta(minutes=1))
    lease = new_lease(alice, expires_at=end)
    batches = export_thoughts(store.sessions, alice, lease)
    assert len(await anext(batches)) == 3
    monkeypatch.setattr(demo, "now", lambda: end + timedelta(seconds=1))
    with counted_queries() as statements:
        with pytest.raises(ExportAborted):
            await anext(batches)
    assert statements == []

    # Neither: it stops normally, with no further query.
    monkeypatch.setattr(demo, "now", lambda: end - timedelta(minutes=1))
    lease = new_lease(alice, expires_at=end)
    batches = export_thoughts(store.sessions, alice, lease)
    assert len(await anext(batches)) == 3
    with counted_queries() as statements:
        with pytest.raises(StopAsyncIteration):
            await anext(batches)
    assert statements == []


BANNED = (
    "thought_embeddings",
    "search_indexes",
    "embedding",
    "search_tsv",
    "before",
    "messages",
    "proposals.parts",
    "proposals.raw_text",
)
PROPOSAL_COLUMNS = {"id", "created_at", "conversation_id", "user_id"}


async def test_the_queries_read_only_what_the_file_holds(store):
    alice = await store.user("alice")
    await seed_everything(store, alice)
    await store.thoughts(alice, *minutes(30))
    with counted_queries() as statements:
        batches = await collect(store, alice)
    assert sum(len(batch) for batch in batches) == 2
    assert statements
    for statement in statements:
        lowered = statement.lower()
        for word in BANNED:
            assert word not in lowered, (word, statement)
        for column in re.findall(r"proposals\.(\w+)", lowered):
            assert column in PROPOSAL_COLUMNS, statement


async def test_only_the_users_own_thoughts_and_conversations(store):
    alice = await store.user("alice")
    bob = await store.user("bob")
    ids = await seed_everything(store, alice)
    bobs = await seed_everything(store, bob)
    await store.thoughts(bob, *minutes(1, 2))

    # Bob's thought claims Alice's proposal as its origin, and Bob's addition
    # Alice's proposal: neither of Alice's conversations may show.
    async def cross(session):
        await session.execute(
            update(Thought)
            .where(Thought.id == bobs["thought"])
            .values(proposal_id=ids["origin"])
        )
        await session.execute(
            update(ThoughtAddition)
            .where(ThoughtAddition.thought_id == bobs["thought"])
            .values(proposal_id=ids["added"])
        )
        await session.commit()

    await store.db(cross)
    [alices] = await collect(store, alice)
    assert [thought.id for thought in alices] == [ids["thought"]]
    bob_thoughts = [thought for batch in await collect(store, bob) for thought in batch]
    assert len(bob_thoughts) == 3
    alice_conversations = {ids["weekend"], ids["plumber"]}
    for thought in bob_thoughts:
        assert (
            thought.origin is None
            or thought.origin.conversation_id not in alice_conversations
        )
        for addition in thought.additions:
            assert addition.conversation_id not in alice_conversations
    crossed = next(thought for thought in bob_thoughts if thought.id == bobs["thought"])
    assert crossed.origin is None and crossed.additions == []


async def test_a_deleted_source_conversation_leaves_no_origin(store):
    alice = await store.user("alice")
    ids = await seed_everything(store, alice)

    async def drop(session):
        conversation = await session.get(Conversation, ids["weekend"])
        await session.delete(conversation)
        await session.commit()

    await store.db(drop)
    [[thought]] = await collect(store, alice)
    assert thought.origin is None
    assert thought.title == "Call the plumber"
    assert thought.summary == "Call the plumber about the leaking kitchen tap."
    assert thought.raw_text.startswith("the kitchen tap leaks again")
    assert len(thought.additions) == 2


async def test_a_deleted_addition_conversation_drops_only_its_addition(store):
    alice = await store.user("alice")
    ids = await seed_everything(store, alice)

    async def another(session):
        conversation = Conversation(user_id=alice, title="Second chat")
        session.add(conversation)
        await session.flush()
        proposal = Proposal(
            conversation_id=conversation.id, user_id=alice, position=1,
            from_position=0, to_position=0, raw_text="x", parts=[],
        )  # fmt: skip
        session.add(proposal)
        await session.flush()
        session.add(
            ThoughtAddition(
                thought_id=ids["thought"],
                user_id=alice,
                proposal_id=proposal.id,
                from_position=0,
                to_position=0,
                added_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
                after_updated_at=datetime(2026, 10, 13, 9, 0, tzinfo=UTC),
                before={},
            )  # fmt: skip
        )
        await session.commit()
        return conversation.id

    second = await store.db(another)
    [[thought]] = await collect(store, alice)
    assert [a.conversation_title for a in thought.additions] == [
        "Second chat", "Plumber chat", "Plumber chat",
    ]  # fmt: skip

    async def drop(session):
        await session.delete(await session.get(Conversation, ids["plumber"]))
        await session.commit()

    await store.db(drop)
    [[thought]] = await collect(store, alice)
    assert [a.conversation_id for a in thought.additions] == [second]
    # The raw text keeps what the deleted conversation added.
    assert "he comes at nine" in thought.raw_text

    async def remaining(session):
        return (
            await session.execute(
                select(ThoughtAddition.id).where(
                    ThoughtAddition.thought_id == ids["thought"]
                )
            )
        ).all()

    assert len(await store.db(remaining)) == 1
