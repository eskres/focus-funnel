"""Proposals: writing them with their raw text, and offering the held one.

Each propose_thought call writes one proposals row. Its raw text is fixed
there, from the user's own messages, never from the browser. The held
proposal is the latest with a part not yet saved; the app offers it before
archive and /compact. When none is held, the model is asked for one with a
forced propose_thought call.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import httpx2
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ChatConfig
from app.chat.conversations import list_messages, use_model
from app.chat.loadout import get_default_model, temperature_for
from app.chat.model_call import ModelCall, open_model_call
from app.chat.prompt import (
    PROPOSE_TOOL,
    build_context,
    forced_tool,
    text_for_model,
    tool_arguments,
    tools_for,
    unsaved_parts,
)
from app.chat.tools import ToolArgumentError, parse_proposal
from app.chat.usage import completion_usage, record_usage
from app.config import Settings
from app.errors import model_not_set
from app.models import Conversation, Message, Proposal, User
from app.providers import provider_for_user
from app.thoughts.categories import user_categories
from app.thoughts.store import MAX_RAW_TEXT, known_tags

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Filing:
    """What the proposal tool offers one user: their categories and known tags."""

    categories: list[str]
    known_tags: list[str]

    @property
    def tools(self) -> list[dict[str, Any]]:
        return tools_for(self.categories, self.known_tags)


async def filing_for(session: AsyncSession, user: User, config: ChatConfig) -> Filing:
    return Filing(
        categories=await user_categories(session, user),
        known_tags=await known_tags(session, user, config.filing.known_tags),
    )


async def held_proposal(session: AsyncSession, conversation: Conversation) -> Proposal | None:
    if conversation.held_proposal_id is None:
        return None
    return await session.get(Proposal, conversation.held_proposal_id)


def held_parts(proposal: Proposal | None) -> list[dict[str, Any]] | None:
    """The parts the held-proposal note lists, or None when nothing is held."""
    if proposal is None or not unsaved_parts(proposal.parts):
        return None
    return proposal.parts


async def list_proposals(session: AsyncSession, conversation: Conversation) -> list[Proposal]:
    rows = await session.execute(
        select(Proposal)
        .where(Proposal.conversation_id == conversation.id)
        .order_by(Proposal.position, Proposal.created_at)
    )
    return list(rows.scalars())


@dataclass(frozen=True)
class RawText:
    text: str
    from_position: int
    to_position: int


def fit_raw_text(messages: list[Message]) -> RawText:
    """The user messages as one text, keeping the most recent whole messages
    that fit the thought store's limit. A latest message longer than the limit
    alone is cut at its end."""
    texts = [(message.position, text_for_model(message.content or "")) for message in messages]
    last_position, last_text = texts[-1]
    if len(last_text) > MAX_RAW_TEXT:
        return RawText(last_text[:MAX_RAW_TEXT], last_position, last_position)
    kept: list[tuple[int, str]] = []
    length = 0
    for position, text in reversed(texts):
        added = len(text) + (2 if kept else 0)
        if length + added > MAX_RAW_TEXT:
            break
        kept.insert(0, (position, text))
        length += added
    return RawText("\n\n".join(text for _, text in kept), kept[0][0], last_position)


async def raw_text_for(
    session: AsyncSession, conversation: Conversation, messages: list[Message], *, push: bool
) -> RawText:
    """The raw text of a proposal made now (design decision 3).

    For /push, the turn's message. Otherwise the user's messages since the
    latest proposal with a saved part, or since the start. Compacted messages
    count; summaries are not user messages.
    """
    users = [message for message in messages if message.role == "user"]
    if push:
        return fit_raw_text(users[-1:])
    start = 0
    for proposal in reversed(await list_proposals(session, conversation)):
        if any(part.get("thought_id") for part in proposal.parts):
            start = proposal.to_position + 1
            break
    discussion = [message for message in users if message.position >= start] or users[-1:]
    return fit_raw_text(discussion)


async def write_proposal(
    session: AsyncSession,
    conversation: Conversation,
    parts: list[dict[str, Any]],
    position: int,
    *,
    push: bool = False,
) -> Proposal:
    """Write a proposal and hold it. The caller commits."""
    raw = await raw_text_for(
        session, conversation, await list_messages(session, conversation), push=push
    )
    proposal = Proposal(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        user_id=conversation.user_id,
        position=position,
        from_position=raw.from_position,
        to_position=raw.to_position,
        raw_text=raw.text,
        parts=parts,
    )
    session.add(proposal)
    # The conversation points at the row, so the row goes in first.
    await session.flush()
    conversation.held_proposal_id = proposal.id
    return proposal


def proposal_payload(proposal: Proposal) -> dict[str, Any]:
    """A proposal as the chat receives it, in the event and in the conversation."""
    return {"id": str(proposal.id), "position": proposal.position, "parts": proposal.parts}


async def forced_proposal(
    session: AsyncSession,
    call: ModelCall,
    context: list[dict[str, Any]],
    filing: Filing,
    conversation_id: uuid.UUID | None = None,
) -> list[dict[str, Any]] | None:
    """Ask the model for a proposal. Returns its parts, or None when the
    model's arguments do not make a proposal."""
    completion = await call.complete(
        context, tools=filing.tools, tool_choice=forced_tool(PROPOSE_TOOL)
    )
    await record_usage(session, call, "proposal", *completion_usage(completion), conversation_id)
    choices = completion.choices or []
    tool_calls = (choices[0].message.tool_calls if choices else None) or []
    for tool_call in tool_calls:
        if tool_call.function.name != PROPOSE_TOOL:
            continue
        try:
            parts = parse_proposal(
                tool_arguments(tool_call.function.arguments), filing.categories
            )
            return [part.as_dict() for part in parts]
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
) -> Proposal | None:
    """The proposal to show before archive or /compact, held from now on.

    Returns the held proposal without a model call when it has a part not
    yet saved, and None when the conversation has no discussion to propose.
    """
    held = await held_proposal(session, conversation)
    if held_parts(held) is not None:
        return held
    messages = await list_messages(session, conversation)
    if not any(m.role == "user" and not m.compacted for m in messages):
        return None

    if conversation.model is None:
        default = await get_default_model(session, user)
        if default is None:
            raise model_not_set()
        use_model(conversation, default)
    filing = await filing_for(session, user, config)
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
        parts = await forced_proposal(
            session, call, build_context(messages), filing, conversation.id
        )
    finally:
        await call.aclose()
    if parts is None:
        return None
    proposal = await write_proposal(session, conversation, parts, messages[-1].position)
    await session.commit()
    return proposal
