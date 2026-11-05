"""How full a conversation's context is: the meter, the soft limit, and the hard limit.

The figure is the prompt token count the provider reported for the last
answer, which includes the offered tool definitions. Without one (a new
conversation, a switched model, a connector turned on or off, or a compacted
one), it is estimated from the characters of the context and of the tool
definitions (openspec mcp-connectors design decision 10).
"""

from dataclasses import dataclass
from typing import Any

from app.chat.config import ChatConfig
from app.chat.prompt import estimate_text_tokens, estimate_tokens, estimate_tool_tokens
from app.errors import context_full
from app.models import Conversation


@dataclass(frozen=True)
class Meter:
    tokens: int
    # True until the next answer reports the model's own count.
    estimated: bool
    context_length: int | None
    # The estimated share of the tokens that the offered tool definitions take.
    tool_tokens: int = 0


def meter(
    conversation: Conversation,
    context: list[dict[str, Any]],
    context_length: int | None,
    tools: list[dict[str, Any]] | None = None,
) -> Meter:
    tool_tokens = estimate_tool_tokens(tools)
    if conversation.last_prompt_tokens is not None:
        return Meter(conversation.last_prompt_tokens, False, context_length, tool_tokens)
    return Meter(estimate_tokens(context, tools), True, context_length, tool_tokens)


def next_prompt_estimate(
    conversation: Conversation,
    context: list[dict[str, Any]],
    message: str,
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """The next prompt: the last reported count plus the new message, or the
    whole context and the tool definitions when there is no reported count.
    A reported count already includes the definitions."""
    if conversation.last_prompt_tokens is not None:
        return conversation.last_prompt_tokens + estimate_text_tokens(message)
    return estimate_tokens(context, tools)


def fits(prompt_tokens: int, context_length: int | None, config: ChatConfig) -> bool:
    """True when a prompt and the longest reply fit the context. Unknown length fits."""
    return context_length is None or prompt_tokens + config.reply_max_tokens <= context_length


def check_room(
    conversation: Conversation,
    context: list[dict[str, Any]],
    message: str,
    context_length: int | None,
    config: ChatConfig,
    tools: list[dict[str, Any]] | None = None,
    connectors: bool = False,
) -> None:
    """Raise context_full, before any model call, when the next prompt, with
    the offered tool definitions, cannot fit. With connectors on, the message
    also advises turning some off."""
    prompt = next_prompt_estimate(conversation, context, message, tools)
    if not fits(prompt, context_length, config):
        raise context_full(connectors=connectors)


def compact_suggestion(
    before: int | None, after: int | None, context_length: int | None, config: ChatConfig
) -> dict[str, Any] | None:
    """The compact_suggested notice, when an answer takes the count past the soft limit.

    Only the crossing counts, so the notice is not repeated while the count
    stays above the limit.
    """
    if after is None or not context_length:
        return None
    limit = config.compact_suggest_share * context_length
    if after <= limit or (before is not None and before > limit):
        return None
    return {"kind": "compact_suggested", "prompt_tokens": after, "context_length": context_length}
