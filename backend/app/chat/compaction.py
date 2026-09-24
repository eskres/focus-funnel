"""/compact: a summary draft of the older messages, and storing it once accepted.

The draft changes nothing. Only an accepted summary is stored, as a summary
message, and the messages it replaces are marked compacted: they stay in the
transcript but are no longer sent to the model. A later compaction includes
the earlier summary, so it can repeat.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.chat.config import ChatConfig
from app.chat.model_call import ModelCall
from app.chat.prompt import text_for_model
from app.chat.sse import Event
from app.chat.turn import RoundState, read_round
from app.chat.usage import record_usage
from app.errors import ApiError, ErrorCode, output_limit_reached
from app.models import Conversation, Message

COMPACT_PROMPT = """\
Summarise the conversation below for the assistant to carry on from. Start \
with one line on what the conversation is about. Then keep every decision \
with its details (dates, places, amounts, numbers), every person, place, \
product, or book mentioned by name, and every open question the user has not \
settled. Leave out small talk. Write a short list, in the language the \
conversation's messages are written in. Write only the summary."""


@dataclass
class CompactionPlan:
    """The messages a summary replaces: the latest summary and every message
    before the most recent ones."""

    summary: Message | None
    replaced: list[Message]

    @property
    def through_position(self) -> int:
        return self.replaced[-1].position


def plan_compaction(messages: list[Message], keep_recent: int) -> CompactionPlan:
    """Keep the most recent messages as they are.

    The kept part never starts with a tool result, since a result must follow
    the call that asked for it, so such results are replaced with their call.
    """
    live = [m for m in messages if not m.compacted and m.role != "summary"]
    summaries = [m for m in messages if not m.compacted and m.role == "summary"]
    cut = max(len(live) - keep_recent, 0)
    while cut and cut < len(live) and live[cut].role == "tool":
        cut += 1
    return CompactionPlan(summary=summaries[-1] if summaries else None, replaced=live[:cut])


def nothing_to_compact(keep_recent: int) -> ApiError:
    return ApiError(
        422,
        ErrorCode.VALIDATION_ERROR,
        f"There is nothing to compact yet: /compact keeps the {keep_recent} most recent "
        "messages as they are.",
    )


def _transcript_line(message: Message) -> str | None:
    if message.role == "user":
        return f"User: {text_for_model(message.content or '')}"
    if message.role == "assistant":
        parts = [message.content or ""]
        for call in message.tool_calls or []:
            parts.append(f"[called {call['function']['name']} with {call['function']['arguments']}]")
        text = " ".join(part for part in parts if part).strip()
        return f"Assistant: {text}" if text else None
    if message.role == "tool":
        return f"Tool result: {message.content or ''}"
    return None


def compaction_request(plan: CompactionPlan) -> list[dict[str, Any]]:
    """The summary call's messages: no tools, the conversation as text."""
    lines = []
    if plan.summary is not None:
        lines.append(f"Summary of the conversation before this:\n{plan.summary.content or ''}\n")
    lines += [line for line in map(_transcript_line, plan.replaced) if line]
    return [
        {"role": "system", "content": COMPACT_PROMPT},
        {"role": "user", "content": "\n".join(lines)},
    ]


async def draft_events(
    session: AsyncSession,
    call: ModelCall,
    chunks: AsyncIterator[Any],
    plan: CompactionPlan,
    conversation: Conversation,
) -> AsyncIterator[Event]:
    """Read the summary call and send it as one compact_draft event. Stores nothing
    but the call's usage."""
    state = RoundState()
    async for _ in read_round(chunks, state, call.provider.capabilities.stream_usage):
        pass
    await record_usage(
        session, call, "compact", state.prompt_tokens, state.completion_tokens, conversation.id
    )
    summary = state.answer.strip()
    if state.finish_reason == "length" or not summary:
        raise output_limit_reached(thinking_only=not summary)
    yield (
        "compact_draft",
        {
            "summary": summary,
            "through_position": plan.through_position,
            "provider_id": call.provider.id,
            "model": call.model,
        },
    )


async def store_compaction(
    session: AsyncSession,
    conversation: Conversation,
    messages: list[Message],
    summary: str,
    through_position: int,
    config: ChatConfig,
) -> None:
    """Store an accepted summary and mark what it replaces as compacted."""
    replaced = [
        m
        for m in messages
        if not m.compacted and m.role != "summary" and m.position <= through_position
    ]
    if not replaced:
        raise nothing_to_compact(config.compact_keep_recent)
    for message in messages:
        if not message.compacted and (message.role == "summary" or message in replaced):
            message.compacted = True
    session.add(
        Message(
            conversation_id=conversation.id,
            position=messages[-1].position + 1,
            role="summary",
            content=summary,
        )
    )
    # The reported count was for the longer context; the meter estimates until
    # the next answer.
    conversation.last_prompt_tokens = None
