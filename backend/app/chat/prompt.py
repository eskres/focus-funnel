"""The system prompt, the two tools, and the context sent to the model."""

import json
from typing import Any

from app.chat.commands import parse_message
from app.errors import ApiError
from app.models import Message

SEARCH_TOOL = "search_thoughts"
PROPOSE_TOOL = "propose_thought"

SYSTEM_PROMPT = """\
You are Focus Funnel, a thinking partner. The user brain-dumps to you: to-dos, \
ideas, worries, and half-formed thoughts. Talk with them and help them think. \
Keep replies short.

You have two tools:
- search_thoughts: search the thoughts the user filed before. Use it when the \
user asks what they said, noted, or decided earlier.
- propose_thought: propose a thought to file, with a short title, a summary, \
and tags. Use it when the user states something clearly worth keeping, such \
as a to-do or an idea, and when a discussion reaches a conclusion or a \
decision. The summary keeps the key findings. The user reviews and edits the \
proposal before anything is saved.

Reply in plain text, without a tool, to greetings, small talk, and messages \
that look unfinished. When you cannot tell what the user wants, ask one short \
question. Never suggest deleting a conversation."""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": SEARCH_TOOL,
            "description": "Search the thoughts the user filed before, by meaning.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for."}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": PROPOSE_TOOL,
            "description": (
                "Propose a thought for the user to file. Nothing is saved until "
                "the user confirms it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "A short title."},
                    "summary": {
                        "type": "string",
                        "description": "A short summary of the key findings or the item.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "A few short tags.",
                    },
                },
                "required": ["title", "summary", "tags"],
            },
        },
    },
]


def forced_tool(name: str) -> dict[str, Any]:
    """A tool_choice that makes the model call this tool."""
    return {"type": "function", "function": {"name": name}}


def text_for_model(content: str) -> str:
    """A stored user message as the model receives it: without its command."""
    try:
        return parse_message(content).content or content
    except ApiError:
        return content


def _as_model_message(message: Message) -> dict[str, Any] | None:
    if message.role == "user":
        return {"role": "user", "content": text_for_model(message.content or "")}
    if message.role == "assistant":
        if not message.content and not message.tool_calls:
            # A failed answer with nothing in it; sending it would only confuse.
            return None
        result: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            result["tool_calls"] = message.tool_calls
        return result
    if message.role == "tool":
        return {"role": "tool", "tool_call_id": message.tool_call_id, "content": message.content or ""}
    return None


def build_context(messages: list[Message]) -> list[dict[str, Any]]:
    """The system prompt, the latest summary if any, then every message not compacted."""
    context: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    summaries = [m for m in messages if m.role == "summary" and not m.compacted]
    if summaries:
        context.append(
            {
                "role": "system",
                "content": "Summary of the earlier conversation:\n" + (summaries[-1].content or ""),
            }
        )
    for message in messages:
        if message.compacted or message.role == "summary":
            continue
        converted = _as_model_message(message)
        if converted is not None:
            context.append(converted)
    return context


def tool_arguments(raw: str) -> dict[str, Any]:
    """Parse a tool call's arguments. Raises ValueError when they are not a JSON object."""
    value = json.loads(raw or "{}")
    if not isinstance(value, dict):
        raise ValueError("arguments must be a JSON object")
    return value
