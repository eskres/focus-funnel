from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import create_engine
from app.models import (
    Base,
    ChatModel,
    Conversation,
    Message,
    UsageEvent,
    User,
    UserSettings,
)


@pytest.fixture
async def session():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        yield session
    await engine.dispose()


async def make_user(session, sub: str = "auth0|alice") -> User:
    user = User(auth0_sub=sub)
    session.add(user)
    await session.commit()
    return user


async def make_conversation(session, user: User) -> Conversation:
    conversation = Conversation(user_id=user.id, title="buy oat milk")
    session.add(conversation)
    await session.commit()
    return conversation


async def count(session, model) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def delete_user(session, user: User) -> None:
    # A bulk delete, so the database's own cascade does the work.
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
    session.expunge_all()


# --- 3.1 conversations and messages ---


async def test_a_conversation_stores_its_messages_in_order(session):
    user = await make_user(session)
    conversation = await make_conversation(session, user)
    session.add_all(
        [
            Message(conversation_id=conversation.id, position=0, role="user", content="hi"),
            Message(
                conversation_id=conversation.id,
                position=1,
                role="assistant",
                tool_calls=[{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
            ),
        ]
    )
    await session.commit()

    rows = (
        await session.execute(select(Message).order_by(Message.position))
    ).scalars().all()
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[0].status == "complete"
    assert rows[0].compacted is False
    assert rows[1].tool_calls[0]["id"] == "c1"


async def test_a_duplicate_position_is_rejected(session):
    user = await make_user(session)
    conversation = await make_conversation(session, user)
    session.add(Message(conversation_id=conversation.id, position=0, role="user", content="a"))
    await session.commit()

    session.add(Message(conversation_id=conversation.id, position=0, role="user", content="b"))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_deleting_the_user_deletes_conversations_and_messages(session):
    user = await make_user(session)
    conversation = await make_conversation(session, user)
    session.add(Message(conversation_id=conversation.id, position=0, role="user", content="a"))
    await session.commit()

    await delete_user(session, user)

    assert await count(session, Conversation) == 0
    assert await count(session, Message) == 0


async def test_deleting_a_conversation_deletes_its_messages(session):
    user = await make_user(session)
    kept = await make_conversation(session, user)
    gone = await make_conversation(session, user)
    session.add_all(
        [
            Message(conversation_id=kept.id, position=0, role="user", content="keep"),
            Message(conversation_id=gone.id, position=0, role="user", content="go"),
        ]
    )
    await session.commit()

    await session.execute(delete(Conversation).where(Conversation.id == gone.id))
    await session.commit()

    contents = (await session.execute(select(Message.content))).scalars().all()
    assert contents == ["keep"]


# --- 3.2 usage, loadout, and settings ---


def chat_model(user: User, model: str = "org/m", position: int = 0) -> ChatModel:
    return ChatModel(user_id=user.id, provider_id="nebius", model=model, position=position)


async def test_a_duplicate_model_per_user_is_rejected(session):
    user = await make_user(session)
    session.add(chat_model(user))
    await session.commit()

    session.add(chat_model(user, position=1))
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_two_users_may_have_the_same_model(session):
    alice = await make_user(session, "auth0|alice")
    bob = await make_user(session, "auth0|bob")
    session.add_all([chat_model(alice), chat_model(bob)])
    await session.commit()
    assert await count(session, ChatModel) == 2


def usage(user: User, conversation: Conversation | None) -> UsageEvent:
    return UsageEvent(
        user_id=user.id,
        conversation_id=conversation.id if conversation else None,
        kind="chat",
        provider_id="nebius",
        model="org/m",
        prompt_tokens=550,
        completion_tokens=360,
        cost_usd=Decimal("0.00012"),
    )


async def test_deleting_a_conversation_keeps_its_usage_record(session):
    user = await make_user(session)
    conversation = await make_conversation(session, user)
    session.add(usage(user, conversation))
    await session.commit()

    await session.execute(delete(Conversation).where(Conversation.id == conversation.id))
    await session.commit()
    session.expunge_all()

    row = (await session.execute(select(UsageEvent))).scalar_one()
    assert row.conversation_id is None
    assert row.prompt_tokens == 550


async def test_deleting_the_user_deletes_usage_loadout_and_settings(session):
    user = await make_user(session)
    conversation = await make_conversation(session, user)
    session.add_all(
        [usage(user, conversation), chat_model(user), UserSettings(user_id=user.id, temperature=0.5)]
    )
    await session.commit()

    await delete_user(session, user)

    assert await count(session, UsageEvent) == 0
    assert await count(session, ChatModel) == 0
    assert await count(session, UserSettings) == 0
