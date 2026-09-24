"""How full a conversation's context is: the meter, the soft limit, and the hard limit.

The figure is the prompt token count the provider reported for the last
answer. Without one (a new conversation, a switched model, or a compacted
one), it is estimated from the characters of the context.
"""

from dataclasses import dataclass
from typing import Any

from app.chat.config import ChatConfig
from app.chat.prompt import estimate_text_tokens, estimate_tokens
from app.errors import context_full
from app.models import Conversation


@dataclass(frozen=True)
class Meter:
    tokens: int
    # True until the next answer reports the model's own count.
    estimated: bool
    context_length: int | None


def meter(
    conversation: Conversation, context: list[dict[str, Any]], context_length: int | None
) -> Meter:
    if conversation.last_prompt_tokens is not None:
        return Meter(conversation.last_prompt_tokens, False, context_length)
    return Meter(estimate_tokens(context), True, context_length)


def next_prompt_estimate(
    conversation: Conversation, context: list[dict[str, Any]], message: str
) -> int:
    """The next prompt: the last reported count plus the new message, or the
    whole context when there is no reported count."""
    if conversation.last_prompt_tokens is not None:
        return conversation.last_prompt_tokens + estimate_text_tokens(message)
    return estimate_tokens(context)


def fits(prompt_tokens: int, context_length: int | None, config: ChatConfig) -> bool:
    """True when a prompt and the longest reply fit the context. Unknown length fits."""
    return context_length is None or prompt_tokens + config.reply_max_tokens <= context_length


def check_room(
    conversation: Conversation,
    context: list[dict[str, Any]],
    message: str,
    context_length: int | None,
    config: ChatConfig,
) -> None:
    """Raise context_full, before any model call, when the next prompt cannot fit."""
    if not fits(next_prompt_estimate(conversation, context, message), context_length, config):
        raise context_full()


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
