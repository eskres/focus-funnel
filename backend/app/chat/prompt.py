"""The system prompt, the two tools, and the context sent to the model."""

import json
import math
from datetime import UTC, date, datetime
from typing import Any

from app.chat.commands import parse_message
from app.errors import ApiError
from app.models import Message
from app.thoughts.categories import FIXED_CATEGORIES

SEARCH_TOOL = "search_thoughts"
PROPOSE_TOOL = "propose_thought"

SYSTEM_PROMPT = """\
You are Focus Funnel, a thinking partner. The user brain-dumps to you: to-dos, \
ideas, worries, and half-formed thoughts. Talk with them and help them think. \
Keep replies short.

You have two tools:
- search_thoughts: search the thoughts the user filed before. Use it when the \
user asks what they said, noted, or decided earlier. Pass the key words and \
names to look for, not a question. When the user names a time, such as this \
month, also pass the start date; when they name a kind of thought, such as \
work, also pass it as a tag.
- propose_thought: propose a thought to file, with a short title, a summary, \
tags, and a category. Use it when the user states something clearly worth \
keeping, such as a to-do or an idea, and when a discussion reaches a \
conclusion or a decision. The summary keeps the key findings, including your \
points the user agreed with. When a message holds several separate things to \
keep, propose each as its own entry in one call; otherwise propose one. A \
detail, reason, or step of one thing stays in that thing's entry. The user \
reviews and edits the proposal before anything is saved.

Answer questions about filed thoughts only from what search_thoughts \
returns. When it finds nothing, say so plainly, and never answer as if the \
user had filed something.

A to-do or an idea the user states is proposed right away. When the user \
asks for help thinking something through, talk with them first and propose \
once they reach a conclusion. Propose each conclusion once: details, doubts, \
and next steps that follow it are not proposed again.

Reply in plain text, without a tool, to greetings, small talk, and messages \
that look unfinished. When you cannot tell what the user wants, ask one short \
question. Never suggest deleting a conversation."""


SEARCH_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": SEARCH_TOOL,
        "description": (
            "Search the thoughts the user filed before, by meaning and by words. "
            "Returns the best matches, or says that none matched."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The key words and names to look for, not a question. "
                        "For example: 'dentist appointment' or 'ACME-4471 invoice'."
                    ),
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only thoughts with at least one of these tags.",
                },
                "since": {
                    "type": "string",
                    "description": "Only thoughts filed on or after this date, YYYY-MM-DD.",
                },
            },
            "required": ["query"],
        },
    },
}

MAX_PARTS = 8
CATEGORY_DESCRIPTION = (
    "The kind of thought. task: something to do. idea: something to try, make, or "
    "change. decision: a choice made. note: something that happened or someone said. "
    "reference: facts to look up later, such as numbers, codes, names, or a "
    "recommendation. The user's own categories are for their own kinds."
)
TAGS_DESCRIPTION = "A few short tags."


def propose_tool_schema(categories: list[str], known_tags: list[str]) -> dict[str, Any]:
    """The propose_thought tool for one user: their categories, and the tags they use."""
    tags_description = TAGS_DESCRIPTION
    if known_tags:
        tags_description += (
            " Reuse one of the user's tags where it fits: " + ", ".join(known_tags) + "."
        )
    part = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "A short title."},
            "summary": {
                "type": "string",
                "description": (
                    "A short summary of the key findings or the item, with the points "
                    "the user agreed with."
                ),
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": tags_description,
            },
            "category": {
                "type": "string",
                "enum": categories,
                "description": CATEGORY_DESCRIPTION,
            },
        },
        "required": ["title", "summary", "tags", "category"],
    }
    return {
        "type": "function",
        "function": {
            "name": PROPOSE_TOOL,
            "description": (
                "Propose thoughts for the user to file. Usually one. Give several only "
                "when the text holds separate things to keep; a detail of one thing "
                "stays in its entry. Nothing is saved until the user confirms."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "thoughts": {
                        "type": "array",
                        "items": part,
                        "minItems": 1,
                        "maxItems": MAX_PARTS,
                        "description": "One entry per separate thing to keep.",
                    }
                },
                "required": ["thoughts"],
            },
        },
    }


def tools_for(categories: list[str], known_tags: list[str]) -> list[dict[str, Any]]:
    """The two tools, with the proposal tool built for one user."""
    return [SEARCH_TOOL_SCHEMA, propose_tool_schema(categories, known_tags)]


# The tools for a user with no added categories and no tags, for the model test.
TOOLS: list[dict[str, Any]] = tools_for(list(FIXED_CATEGORIES), [])


HELD_PROPOSAL_NOTE = """\
A proposal from this conversation was shown to the user and is held until \
they confirm it:
{parts}

Do not propose it again while the user keeps talking about it. Before you \
answer, decide whether the user's latest message is still about this \
proposal's topic. If it is about something else (a new question, a new task, \
or a new subject), your first action must be a propose_thought call with the \
held proposal, updated with anything discussed since. Then answer the new \
message."""


def unsaved_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [part for part in parts if not part.get("thought_id")]


def held_proposal_note(parts: list[dict[str, Any]]) -> str:
    """The note for a held proposal: its parts the user has not saved."""
    blocks = [
        "Title: {title}\nSummary: {summary}\nTags: {tags}\nCategory: {category}".format(
            title=part.get("title", ""),
            summary=part.get("summary", ""),
            tags=", ".join(part.get("tags") or []) or "none",
            category=part.get("category") or "none",
        )
        for part in unsaved_parts(parts)
    ]
    return HELD_PROPOSAL_NOTE.format(parts="\n\n".join(blocks))


FILED_NOTE = (
    "These thoughts were already filed from this conversation:\n{titles}\n"
    "Propose only what the conversation added since, and do not propose any of "
    "these again, in any wording."
)


def filed_note(titles: list[str]) -> str:
    """The note for an offered proposal: the thoughts this conversation already filed."""
    return FILED_NOTE.format(titles="\n".join(f"- {title}" for title in titles))


def drop_held_note(context: list[dict[str, Any]], held_parts: list[dict[str, Any]] | None) -> None:
    """Remove the held-proposal note once the turn has proposed, so the model
    does not follow the note again in the next round."""
    if not held_parts:
        return
    note = {"role": "system", "content": held_proposal_note(held_parts)}
    if note in context:
        context.remove(note)


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


def system_prompt(today: date | None = None) -> str:
    """The system prompt with today's date, so the model can pass a start date."""
    today = today or datetime.now(UTC).date()
    return f"{SYSTEM_PROMPT}\n\nToday is {today.strftime('%A')} {today.isoformat()}."


def build_context(
    messages: list[Message],
    held_parts: list[dict[str, Any]] | None = None,
    today: date | None = None,
) -> list[dict[str, Any]]:
    """The system prompt, the latest summary if any, every message not
    compacted, then the held-proposal note if a proposal with unsaved parts
    is held. The note
    comes last because the model follows it far more often there."""
    context: list[dict[str, Any]] = [{"role": "system", "content": system_prompt(today)}]
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
    if held_parts and unsaved_parts(held_parts):
        context.append({"role": "system", "content": held_proposal_note(held_parts)})
    return context


def tool_arguments(raw: str) -> dict[str, Any]:
    """Parse a tool call's arguments. Raises ValueError when they are not a JSON object."""
    value = json.loads(raw or "{}")
    if not isinstance(value, dict):
        raise ValueError("arguments must be a JSON object")
    return value


# No provider offers a tokenizer, so sizes are estimated from characters.
CHARS_PER_TOKEN = 3.5


def estimate_text_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def estimate_tokens(context: list[dict[str, Any]]) -> int:
    """An estimate of a request's prompt tokens: its text, and its tool calls as JSON."""
    chars = 0
    for message in context:
        chars += len(message.get("content") or "")
        if message.get("tool_calls"):
            chars += len(json.dumps(message["tool_calls"]))
    return math.ceil(chars / CHARS_PER_TOKEN)
