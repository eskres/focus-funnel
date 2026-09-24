import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.pool import NullPool

from app.auth import get_or_create_user
from app.db import create_engine
from app.models import (
    Base,
    ChatModel,
    Conversation,
    Message,
    Proposal,
    ProviderKey,
    SearchIndex,
    Thought,
    ThoughtEmbedding,
    UsageEvent,
    User,
    UserCategory,
    UserSettings,
)
from app.user_data import delete_user_data
from tests.conftest import TEST_ISSUER, count_users

# Every table with rows that belong to a user, and how to find that user's rows.
USER_OWNED = {
    Conversation: lambda user_id: Conversation.user_id == user_id,
    Message: lambda user_id: Message.conversation_id.in_(
        select(Conversation.id).where(Conversation.user_id == user_id)
    ),
    Proposal: lambda user_id: Proposal.user_id == user_id,
    UserCategory: lambda user_id: UserCategory.user_id == user_id,
    ProviderKey: lambda user_id: ProviderKey.user_id == user_id,
    ChatModel: lambda user_id: ChatModel.user_id == user_id,
    UserSettings: lambda user_id: UserSettings.user_id == user_id,
    UsageEvent: lambda user_id: UsageEvent.user_id == user_id,
    Thought: lambda user_id: Thought.user_id == user_id,
    SearchIndex: lambda user_id: SearchIndex.user_id == user_id,
    ThoughtEmbedding: lambda user_id: ThoughtEmbedding.thought_id.in_(
        select(Thought.id).where(Thought.user_id == user_id)
    ),
}


def test_every_user_owned_table_is_listed():
    """A new table that holds a users.id must be added above, and cascade."""
    owned = set()
    for table in Base.metadata.sorted_tables:
        for fk in table.foreign_keys:
            if fk.column.table.name in ("users", "conversations", "thoughts", "search_indexes"):
                owned.add(table.name)
                assert fk.ondelete == "CASCADE" or fk.parent.nullable, (table.name, fk)
    assert owned == {model.__tablename__ for model in USER_OWNED}


async def add_everything(session, user: User) -> None:
    conversation = Conversation(user_id=user.id, title="t")
    session.add(conversation)
    await session.flush()
    session.add_all(
        [
            Message(conversation_id=conversation.id, position=0, role="user", content="hi", status="complete"),
            Proposal(
                conversation_id=conversation.id,
                user_id=user.id,
                position=1,
                from_position=0,
                to_position=0,
                raw_text="hi",
                parts=[{"title": "t", "summary": "s", "tags": [], "category": None, "thought_id": None}],
            ),
            UserCategory(user_id=user.id, name="recipe"),
            ProviderKey(user_id=user.id, provider_id="nebius"),
            ChatModel(user_id=user.id, provider_id="nebius", model="m", is_default=True, position=0),
            UserSettings(user_id=user.id),
            UsageEvent(
                user_id=user.id,
                conversation_id=conversation.id,
                provider_id="nebius",
                model="m",
                kind="chat",
                prompt_tokens=1,
                completion_tokens=1,
            ),
        ]
    )
    thought = Thought(user_id=user.id, title="t", summary="s", tags=["a"])
    index = SearchIndex(
        user_id=user.id,
        version=1,
        embedding_provider="nebius",
        embedding_model="m",
        dimension=2,
        status="active",
    )
    session.add_all([thought, index])
    await session.flush()
    session.add(
        ThoughtEmbedding(index_id=index.id, thought_id=thought.id, chunk=0, embedding=[0.1, 0.2])
    )
    await session.commit()


async def counts(session, user_id: uuid.UUID) -> dict[str, int]:
    result = {}
    for model, where in USER_OWNED.items():
        query = select(func.count()).select_from(model).where(where(user_id))
        result[model.__tablename__] = (await session.execute(query)).scalar_one()
    return result


def test_delete_user_data_leaves_nothing_of_that_user_and_keeps_others(test_database_url):
    async def run():
        engine = create_engine(test_database_url, poolclass=NullPool)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            alice = await get_or_create_user(session, TEST_ISSUER, "alice")
            bob = await get_or_create_user(session, TEST_ISSUER, "bob")
            await add_everything(session, alice)
            await add_everything(session, bob)
            bob_before = await counts(session, bob.id)

            await delete_user_data(session, alice)

            alice_after = await counts(session, alice.id)
            bob_after = await counts(session, bob.id)
        await engine.dispose()
        return bob_before, alice_after, bob_after

    bob_before, alice_after, bob_after = asyncio.run(run())
    assert all(count == 0 for count in alice_after.values()), alice_after
    assert all(count == 1 for count in bob_before.values()), bob_before
    assert bob_after == bob_before
    assert count_users(test_database_url, "alice") == 0
    assert count_users(test_database_url, "bob") == 1
