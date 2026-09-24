"""The held proposal the app offers before archive and /compact.

When no proposal is held for a discussion, the model is asked for one with a
forced propose_thought call. A held proposal is offered as it is, and no
model is called.
"""

import logging
import uuid
from typing import Any

import httpx2
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ChatConfig
from app.chat.conversations import list_messages, use_model
from app.chat.loadout import get_default_model, temperature_for
from app.chat.model_call import ModelCall, open_model_call
from app.chat.prompt import PROPOSE_TOOL, TOOLS, build_context, forced_tool, tool_arguments
from app.chat.tools import ToolArgumentError, parse_proposal
from app.chat.usage import completion_usage, record_usage
from app.config import Settings
from app.errors import model_not_set
from app.models import Conversation, User
from app.providers import provider_for_user

logger = logging.getLogger(__name__)


async def forced_proposal(
    session: AsyncSession,
    call: ModelCall,
    context: list[dict[str, Any]],
    conversation_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    """Ask the model for a proposal. Returns its title, summary, and tags, or
    None when the model's arguments do not make a proposal."""
    completion = await call.complete(context, tools=TOOLS, tool_choice=forced_tool(PROPOSE_TOOL))
    await record_usage(session, call, "proposal", *completion_usage(completion), conversation_id)
    choices = completion.choices or []
    tool_calls = (choices[0].message.tool_calls if choices else None) or []
    for tool_call in tool_calls:
        if tool_call.function.name != PROPOSE_TOOL:
            continue
        try:
            return parse_proposal(tool_arguments(tool_call.function.arguments)).as_dict()
        except (ValueError, ToolArgumentError):
            logger.info("The forced proposal call returned arguments that do not fit")
    return None


async def offer_proposal(
    session: AsyncSession,
    user: User,
    conversation: Conversation,
    config: ChatConfig,
    settings: Settings,
    http_client: httpx2.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """The proposal to show before archive or /compact, held from now on.

    Returns the held proposal without a model call when one exists, and None
    when the conversation has no discussion to propose.
    """
    if conversation.held_proposal is not None:
        return conversation.held_proposal
    messages = await list_messages(session, conversation)
    if not any(m.role == "user" and not m.compacted for m in messages):
        return None

    if conversation.model is None:
        default = await get_default_model(session, user)
        if default is None:
            raise model_not_set()
        use_model(conversation, default)
    provider = await provider_for_user(session, user, conversation.provider_id, settings)
    call = await open_model_call(
        session,
        user,
        provider,
        conversation.model,
        temperature=await temperature_for(session, user, config),
        max_tokens=config.reply_max_tokens,
        reasoning_effort=conversation.reasoning_effort,
        settings=settings,
        http_client=http_client,
    )
    try:
        proposal = await forced_proposal(session, call, build_context(messages), conversation.id)
    finally:
        await call.aclose()
    if proposal is None:
        return None
    conversation.held_proposal = {**proposal, "position": messages[-1].position}
    await session.commit()
    return conversation.held_proposal
