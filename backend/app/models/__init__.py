"""Import every model here so Base.metadata is complete for Alembic."""

from app.db import Base
from app.models.chat_settings import ChatModel, UserSettings
from app.models.conversation import Conversation, Message
from app.models.provider_key import ProviderKey
from app.models.thought import SearchIndex, Thought, ThoughtEmbedding
from app.models.usage_event import UsageEvent
from app.models.user import User

__all__ = [
    "Base",
    "ChatModel",
    "Conversation",
    "Message",
    "ProviderKey",
    "SearchIndex",
    "Thought",
    "ThoughtEmbedding",
    "UsageEvent",
    "User",
    "UserSettings",
]
