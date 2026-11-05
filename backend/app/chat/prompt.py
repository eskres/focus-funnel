"""The system prompt, the two tools, and the context sent to the model."""

import json
import math
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from app.chat.commands import parse_message
from app.errors import ApiError
from app.models import Message
from app.thoughts.categories import FIXED_CATEGORIES
from app.thoughts.dates import DEFAULT_ZONE, today_in

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
tags, a category, and a date when the thought is about a set date or time. Use it when the user states something clearly worth \
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
            "Returns the best matches, or says that none matched. When the user asks "
            "what is on, coming up, or planned for a time, pass dated_from and "
            "dated_to, with no query unless they name a subject; the result then "
            "lists the thoughts dated in those days, in date order."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "The key words and names to look for, not a question. "
                        "For example: 'dentist appointment' or 'ACME-4471 invoice'. "
                        "Needed unless dated_from or dated_to is given."
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
                "dated_from": {
                    "type": "string",
                    "description": (
                        "The first of the days the thought happens on, not the day it "
                        "was filed, YYYY-MM-DD. Only thoughts dated on or after it."
                    ),
                },
                "dated_to": {
                    "type": "string",
                    "description": (
                        "The last of the days the thought happens on, not the day it "
                        "was filed, YYYY-MM-DD. Only thoughts dated on or before it."
                    ),
                },
            },
        },
    },
}

MAX_PARTS = 8
CATEGORY_DESCRIPTION = (
    "The kind of thought. task: something to do. idea: something to try, make, or "
    "change. decision: a choice made. note: something that happened or someone said. "
    "reference: facts to look up later, such as numbers, codes, names, or a "
    "recommendation. event: something planned for a set date or time, such as an "
    "appointment, a meeting, a trip, or a dinner. Something to do or arrange is a task, "
    "even on a set day; something that already happened is a note. The user's own "
    "categories are for their own kinds."
)
TAGS_DESCRIPTION = "A few short tags."
# Additions (thought-appending design decisions 2 and 3).
ADD_TO_DESCRIPTION = (
    "The ref, such as T2, of a thought this conversation has seen, to add this entry "
    "to it instead of filing a new thought. Give it when the entry continues that "
    "thought. The summary is then the whole new summary of that thought, and says "
    "what changed and when; its title is kept and the title here is ignored."
)
NEW_DESCRIPTION = (
    "true to keep this entry a new thought after similar thoughts were listed for it."
)

# The model gives a start and an end only; the server adds the user's zone
# (thought-dates design decisions 2 and 5).
DATE_POINT_DESCRIPTION = "YYYY-MM-DD for a day, or YYYY-MM-DDTHH:MM for a day and a time."
DATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "start": {"type": "string", "description": "The start: " + DATE_POINT_DESCRIPTION},
        "end": {
            "type": "string",
            "description": (
                "The end, only when the user names one: " + DATE_POINT_DESCRIPTION
                + " Give it a time only when the start has one."
            ),
        },
    },
    "required": ["start"],
}
WHEN_DESCRIPTION = (
    "The thought's date. Give it only when the thought is about a set date or time; "
    "leave it out otherwise. Work out weekdays and relative days such as 'tomorrow' "
    "from today's date. A weekday means the soonest such day after today. Give a "
    "time or an end only when the user names one. For example, said on Wednesday "
    "2026-09-30, 'dinner Friday at 7' is {\"start\": \"2026-10-02T19:00\"}, and "
    "'trip 3-6 Nov' is {\"start\": \"2026-11-03\", \"end\": \"2026-11-06\"}."
)
WHEN_CHOICES_DESCRIPTION = (
    "Do not guess an unclear day: give two choices here instead, and no when. The "
    "day is unclear in two cases. A weekday that is today's weekday: today, and the "
    "same weekday one week later; said on Friday 2026-10-02, 'Friday at 7' gives "
    "2026-10-02T19:00 and 2026-10-09T19:00. 'Next' with a weekday: the soonest such "
    "day after today, and the same weekday one week after that; said on Wednesday "
    "2026-09-30, 'next Friday' gives 2026-10-02 and 2026-10-09. The user picks one."
)


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
            "when": {**DATE_SCHEMA, "description": WHEN_DESCRIPTION},
            "when_choices": {
                "type": "array",
                "items": DATE_SCHEMA,
                "minItems": 2,
                "maxItems": 2,
                "description": WHEN_CHOICES_DESCRIPTION,
            },
            "add_to": {"type": "string", "description": ADD_TO_DESCRIPTION},
            "new": {"type": "boolean", "description": NEW_DESCRIPTION},
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


def _date_text(when: dict[str, Any]) -> str:
    start = when.get("start") or ""
    return f"{start} to {when['end']}" if when.get("end") else start


def date_line(part: dict[str, Any]) -> str:
    """A part's date for the held-proposal note: one date, both choices, or none."""
    choices = part.get("when_choices")
    if choices:
        return " or ".join(_date_text(choice) for choice in choices) + " (not picked yet)"
    if part.get("when"):
        return _date_text(part["when"])
    return "none"


def held_proposal_note(
    parts: list[dict[str, Any]], refs: Mapping[str, str] | None = None
) -> str:
    """The note for a held proposal: its parts the user has not saved. An
    addition's part also names the thought it adds to by its ref, from `refs`
    (a ref by thought id), when that thought still exists."""
    blocks = [
        "Title: {title}\nSummary: {summary}\nTags: {tags}\nCategory: {category}\nDate: {date}".format(
            title=part.get("title", ""),
            summary=part.get("summary", ""),
            tags=", ".join(part.get("tags") or []) or "none",
            category=part.get("category") or "none",
            date=date_line(part),
        )
        + _adds_to_line(part, refs)
        for part in unsaved_parts(parts)
    ]
    return HELD_PROPOSAL_NOTE.format(parts="\n\n".join(blocks))


def _adds_to_line(part: dict[str, Any], refs: Mapping[str, str] | None) -> str:
    ref = (refs or {}).get(str(part.get("add_to"))) if part.get("add_to") else None
    return f"\nAdds to: {ref}" if ref else ""


SEEN_THOUGHTS_NOTE = """\
Thoughts this conversation has seen, most recently seen first, each with its \
ref. To add to one instead of filing a new thought, set add_to to its ref in \
propose_thought.
{thoughts}"""


def _cut(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def thought_entry(ref: str, thought: Any, summary_chars: int) -> str:
    """A filed thought as the model reads it by ref: ref, title, filing date,
    tags, and category, then the summary cut at `summary_chars`."""
    heading = f"{ref} · {thought.title} · filed {thought.created_at.date().isoformat()}"
    if thought.tags:
        heading += " · " + " ".join(f"#{tag}" for tag in thought.tags)
    if thought.category:
        heading += f" · {thought.category}"
    return heading + "\n   " + _cut(thought.summary, summary_chars)


def seen_thoughts_note(seen: Sequence[Any], limit: int, summary_chars: int) -> str | None:
    """The note naming the thoughts this conversation has seen, by ref and
    never by id (thought-appending design decision 2): the first `limit` of
    `seen`, which comes most recently seen first, each with its title, filing
    date, tags, category, and summary cut at `summary_chars`. None when
    nothing was seen."""
    entries = [
        thought_entry(thought.ref, thought, summary_chars) for thought in list(seen)[:limit]
    ]
    if not entries:
        return None
    return SEEN_THOUGHTS_NOTE.format(thoughts="\n".join(entries))


OFFER_NOTE = (
    "The user is about to archive or compact this conversation. If the "
    "conversation since the last filed thought holds something worth keeping, "
    "such as a decision, a task, an idea, or facts to look up later, call "
    "propose_thought for it. Leave out greetings, thanks, and small talk. If "
    "nothing is worth keeping, reply with one word, nothing, and call no tool."
)

# In the offer, after the seen-thoughts note. It replaces the list of titles
# filed from this conversation that the offer once had.
OFFER_SEEN_NOTE = (
    "The thoughts this conversation has seen are filed already: do not propose them "
    "again as new thoughts. When the conversation since adds new facts or decisions "
    "about one of them, propose them as an addition to it, with add_to set to its ref."
)


def offer_note(seen: bool) -> str:
    """The note for the call before archive or /compact, and when the
    seen-thoughts note lists any thought, how to treat them."""
    return OFFER_NOTE + "\n\n" + OFFER_SEEN_NOTE if seen else OFFER_NOTE


def drop_held_note(context: list[dict[str, Any]], held_parts: list[dict[str, Any]] | None) -> None:
    """Remove the held-proposal note once the turn has proposed, so the model
    does not follow the note again in the next round. The note is found by its
    first line, since an addition's part names its ref in it."""
    if not held_parts:
        return
    head = HELD_PROPOSAL_NOTE.split("\n", 1)[0]
    for message in context:
        if message.get("role") == "system" and (message.get("content") or "").startswith(head):
            context.remove(message)
            return


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
    """The system prompt with today's date, the user's local date when the
    caller knows their zone, so the model can work out dates."""
    today = today or today_in(ZoneInfo(DEFAULT_ZONE))
    return (
        f"{SYSTEM_PROMPT}\n\nToday is {today.strftime('%A')} {today.isoformat()}. "
        "Weeks start on Monday."
    )


def build_context(
    messages: list[Message],
    held_parts: list[dict[str, Any]] | None = None,
    today: date | None = None,
    *,
    seen_note: str | None = None,
    refs: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """The system prompt, the latest summary if any, every message not
    compacted, the seen-thoughts note if any, then the held-proposal note if
    a proposal with unsaved parts is held, naming an addition's thought by
    its ref from `refs`. The held note
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
    if seen_note:
        context.append({"role": "system", "content": seen_note})
    if held_parts and unsaved_parts(held_parts):
        context.append({"role": "system", "content": held_proposal_note(held_parts, refs)})
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
