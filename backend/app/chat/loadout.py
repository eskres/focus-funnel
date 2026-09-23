"""A user's chat models: the loadout, the default, and the temperature."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ChatConfig
from app.models import ChatModel, User, UserSettings

MAX_LOADOUT_MODELS = 5


async def get_loadout(session: AsyncSession, user: User) -> list[ChatModel]:
    return list(
        (
            await session.execute(
                select(ChatModel).where(ChatModel.user_id == user.id).order_by(ChatModel.position)
            )
        ).scalars()
    )


async def get_default_model(session: AsyncSession, user: User) -> ChatModel | None:
    return (
        await session.execute(
            select(ChatModel).where(ChatModel.user_id == user.id, ChatModel.is_default.is_(True))
        )
    ).scalar_one_or_none()


async def find_loadout_model(
    session: AsyncSession, user: User, provider_id: str, model: str
) -> ChatModel | None:
    return (
        await session.execute(
            select(ChatModel).where(
                ChatModel.user_id == user.id,
                ChatModel.provider_id == provider_id,
                ChatModel.model == model,
            )
        )
    ).scalar_one_or_none()


async def get_user_settings(session: AsyncSession, user: User) -> UserSettings | None:
    return await session.get(UserSettings, user.id)


async def temperature_for(session: AsyncSession, user: User, config: ChatConfig) -> float:
    """The user's temperature, or the system default when none is set."""
    row = await get_user_settings(session, user)
    if row is None or row.temperature is None:
        return config.temperature.default
    return row.temperature
