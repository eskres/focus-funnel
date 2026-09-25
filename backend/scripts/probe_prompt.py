"""Probe the chat's system prompt and tools against a real model.

Eight probes, each with its data set in scripts/probe_data/:

  tools    labelled messages: does the model pick the tool the label names?
  topic    a held proposal, then an unrelated or a related message: does the
           model offer the held summary only on the unrelated one?
  repeat   a held proposal, then the user keeps going on the same topic: does
           the model propose the same conclusion again?
  compact  long conversations summarised as /compact does: do the checklist
           items survive in the summary?
  search   recall questions: does the model search with key words rather than
           the question, and pass a tag or a start date when the user names one?
  split    /push messages with one, two, or three things to keep: does the
           proposal have one part per thing?
  filing   /push messages for a user with known tags: does the part get the
           expected category, and reuse an existing tag where one fits?
  nomatch  recall questions whose search finds nothing: does the answer say
           so plainly, without claiming anything was filed?

`topic` and `repeat` together are the discussion probes.

The probes build the context with the app's own code (build_context,
plan_compaction, compaction_request), so they test what the chat sends.

Run from backend/, with the key in NEBIUS_API_KEY:

  uv run python -m scripts.probe_prompt tools --runs 2 --report out.md
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from openai import AsyncOpenAI

from app.chat.compaction import compaction_request, plan_compaction
from app.chat.config import load_chat_config
from app.chat.prompt import (
    PROPOSE_TOOL,
    SEARCH_TOOL,
    TOOLS,
    build_context,
    drop_held_note,
    forced_tool,
    tool_arguments,
    tools_for,
)
from app.chat.tools import (
    NO_MATCH,
    PROPOSAL_SHOWN,
    ToolArgumentError,
    parse_proposal,
    parse_search,
)
from app.models import Message
from app.thoughts.categories import FIXED_CATEGORIES

DATA = Path(__file__).parent / "probe_data"
BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
DEFAULT_MODEL = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
LABELS = {"search": SEARCH_TOOL, "propose": PROPOSE_TOOL, "none": None}
# Models write non-breaking hyphens and spaces; checklist patterns use ASCII.
PLAIN = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2013": "-", "\u00a0": " ", "\u202f": " "})


@dataclass
class Settings:
    client: AsyncOpenAI
    model: str
    temperature: float
    max_tokens: int
    tool_rounds: int
    effort: str | None
    limit: asyncio.Semaphore


@dataclass
class Turn:
    """What one user turn produced: every tool call across the rounds, the
    final text, and the first round's time and tokens."""

    calls: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    seconds: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    held: list[dict[str, Any]] | None = None

    @property
    def first_tool(self) -> str | None:
        return self.calls[0]["name"] if self.calls else None

    @property
    def proposals(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["name"] == PROPOSE_TOOL]

    def first_parts(self, categories: list[str] | None = None) -> list[dict[str, Any]]:
        """The parts of the first valid proposal, as the chat stores them."""
        for call in self.proposals:
            parts = parts_of(call["arguments"], categories)
            if parts:
                return parts
        return []


def parts_of(raw: str, categories: list[str] | None = None) -> list[dict[str, Any]]:
    """A propose_thought call's parts, or none when its arguments do not fit."""
    try:
        parts = parse_proposal(tool_arguments(raw), categories or list(FIXED_CATEGORIES))
    except (ValueError, ToolArgumentError):
        return []
    return [part.as_dict() for part in parts]


def titles_of(turn: "Turn") -> list[str]:
    return [part["title"] for call in turn.proposals for part in parts_of(call["arguments"])]


# ---------------------------------------------------------------- transcript


def _message(position: int, role: str, content: str | None = None, **extra: Any) -> Message:
    return Message(
        id=uuid.uuid4(), position=position, role=role, content=content, compacted=False, **extra
    )


def transcript(turns: list[dict[str, Any]]) -> list[Message]:
    """Stored messages from a data set's turns.

    A turn is {user: text}, {assistant: text}, or {proposal: arguments,
    reply: text}, which is stored as the chat stores a proposal: a tool call,
    its result, and the model's short reply. The arguments are one part
    ({title, summary, tags}) or {thoughts: [...]}.
    """
    messages: list[Message] = []
    for turn in turns:
        position = len(messages)
        if "user" in turn:
            messages.append(_message(position, "user", turn["user"]))
        elif "assistant" in turn:
            messages.append(_message(position, "assistant", turn["assistant"]))
        elif "proposal" in turn:
            call_id = f"call_{uuid.uuid4().hex[:12]}"
            call = {
                "id": call_id,
                "type": "function",
                "function": {"name": PROPOSE_TOOL, "arguments": json.dumps(turn["proposal"])},
            }
            messages.append(_message(position, "assistant", None, tool_calls=[call]))
            messages.append(_message(position + 1, "tool", PROPOSAL_SHOWN, tool_call_id=call_id))
            messages.append(_message(position + 2, "assistant", turn.get("reply", "")))
        else:
            raise ValueError(f"unknown turn: {turn}")
    return messages


def held_from(turns: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """The parts of the latest proposal in the turns, held as the chat holds them."""
    held = None
    for turn in turns:
        if "proposal" in turn:
            held = parts_of(json.dumps(turn["proposal"])) or None
    return held


# ---------------------------------------------------------------- model calls


def _valid(name: str, raw: str) -> bool:
    try:
        arguments = tool_arguments(raw)
        if name == PROPOSE_TOOL:
            parse_proposal(arguments, list(FIXED_CATEGORIES))
            return True
        if name == SEARCH_TOOL:
            parse_search(arguments)
            return True
    except (ValueError, ToolArgumentError):
        return False
    return False


def _tool_result(name: str, valid: bool) -> str:
    if not valid:
        return "Error: the arguments do not fit the tool. Call the tool again with valid arguments."
    if name == SEARCH_TOOL:
        return NO_MATCH
    return PROPOSAL_SHOWN


async def _create(settings: Settings, messages: list[dict[str, Any]], **extra: Any) -> Any:
    request: dict[str, Any] = {
        "model": settings.model,
        "messages": messages,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        **extra,
    }
    if settings.effort is not None:
        request["reasoning_effort"] = settings.effort
    return await settings.client.chat.completions.create(**request)


async def run_turn(
    settings: Settings,
    messages: list[Message],
    held: list[dict[str, Any]] | None,
    *,
    tools: list[dict[str, Any]] | None = None,
    forced: str | None = None,
) -> Turn:
    """Run one user turn the way the chat does: with tools, running each call
    and calling the model again, up to the round limit. The search tool finds
    nothing and a proposal is shown. `forced` names the tool the first round
    must call, as /push and /pull do."""
    turn = Turn(held=held)
    context = build_context(messages, held)
    async with settings.limit:
        for round_number in range(settings.tool_rounds):
            started = time.monotonic()
            extra: dict[str, Any] = {"tools": tools or TOOLS}
            if forced and round_number == 0:
                extra["tool_choice"] = forced_tool(forced)
            try:
                completion = await _create(settings, context, **extra)
            except Exception as exc:  # a probe reports failures, it does not stop on them
                turn.error = f"{type(exc).__name__}: {exc}"
                return turn
            if round_number == 0:
                turn.seconds = time.monotonic() - started
                if completion.usage is not None:
                    turn.prompt_tokens = completion.usage.prompt_tokens
                    turn.completion_tokens = completion.usage.completion_tokens
            message = completion.choices[0].message
            tool_calls = message.tool_calls or []
            if not tool_calls:
                turn.text = message.content or ""
                return turn
            stored = []
            for call in tool_calls:
                valid = _valid(call.function.name, call.function.arguments)
                turn.calls.append(
                    {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                        "valid": valid,
                    }
                )
                stored.append(
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                )
            context.append(
                {"role": "assistant", "content": message.content or "", "tool_calls": stored}
            )
            for call, recorded in zip(tool_calls, turn.calls[-len(tool_calls) :]):
                if call.function.name == PROPOSE_TOOL and recorded["valid"]:
                    drop_held_note(context, held)
                context.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": _tool_result(call.function.name, recorded["valid"]),
                    }
                )
        turn.error = "tool_loop_limit"
        return turn


# ---------------------------------------------------------------- reports


def _tokens(turn: Turn) -> str:
    if turn.prompt_tokens is None:
        return "?"
    return f"{turn.prompt_tokens}+{turn.completion_tokens}"


def _tool_cell(turn: Turn) -> str:
    if turn.error:
        return f"error ({turn.error[:60]})"
    if not turn.calls:
        return "none"
    return ", ".join(c["name"] + ("" if c["valid"] else " (invalid)") for c in turn.calls)


def _short(text: str, length: int = 70) -> str:
    text = " ".join(text.split()).replace("|", "/")
    return text if len(text) <= length else text[: length - 1] + "…"


def _header(title: str, settings: Settings, runs: int) -> list[str]:
    return [
        f"# {title}",
        "",
        f"- Model: `{settings.model}`",
        f"- Temperature: {settings.temperature}, max_tokens: {settings.max_tokens}, "
        f"effort: {settings.effort or 'not sent'}",
        f"- Runs: {runs}",
        f"- Date: {time.strftime('%Y-%m-%d %H:%M')}",
        "",
    ]


def _timing(turns: list[Turn]) -> str:
    done = [t for t in turns if not t.error and t.prompt_tokens is not None]
    if not done:
        return "No timings."
    seconds = sorted(t.seconds for t in done)
    completion = sorted(t.completion_tokens or 0 for t in done)
    return (
        f"First round: median {seconds[len(seconds) // 2]:.1f} s, max {seconds[-1]:.1f} s; "
        f"completion tokens median {completion[len(completion) // 2]}, max {completion[-1]}."
    )


# ---------------------------------------------------------------- probes


async def probe_tools(settings: Settings, runs: int) -> tuple[list[str], bool]:
    cases = yaml.safe_load((DATA / "tools.yaml").read_text())["cases"]
    jobs = []
    for run in range(runs):
        for case in cases:
            turns = case.get("history", []) + [{"user": case["message"]}]
            jobs.append((run, case, run_turn(settings, transcript(turns), held_from(turns))))
    results = await asyncio.gather(*(job for _, _, job in jobs))

    lines = _header("Tool choice probe", settings, runs)
    lines += ["| Run | Case | Category | Expected | Chosen | Args | Time | Tokens | Message |"]
    lines += ["|---|---|---|---|---|---|---|---|---|"]
    per_run: dict[int, list[bool]] = {}
    per_category: dict[str, list[bool]] = {}
    silent_failures = []
    for (run, case, _), turn in zip(jobs, results):
        expected = LABELS[case["expect"]]
        match = not turn.error and turn.first_tool == expected
        per_run.setdefault(run, []).append(match)
        per_category.setdefault(case["category"], []).append(match)
        if case["category"] in ("greeting", "unfinished") and turn.calls:
            silent_failures.append(f"run {run + 1} {case['id']}")
        valid = "n/a" if not turn.calls else ("ok" if all(c["valid"] for c in turn.calls) else "bad")
        lines.append(
            f"| {run + 1} | {case['id']} | {case['category']} | {case['expect']} | "
            f"{'✓ ' if match else '✗ '}{_tool_cell(turn)} | {valid} | {turn.seconds:.1f} s | "
            f"{_tokens(turn)} | {_short(case['message'], 50)} |"
        )

    lines += ["", "## Summary", ""]
    passed = True
    for run, matches in sorted(per_run.items()):
        share = sum(matches) / len(matches)
        passed &= share >= 0.9
        lines.append(f"- Run {run + 1}: {sum(matches)} of {len(matches)} match ({share:.0%})")
    for category, matches in per_category.items():
        lines.append(f"- {category}: {sum(matches)} of {len(matches)}")
    lines.append(
        "- Greeting or unfinished messages that called a tool: "
        + (", ".join(silent_failures) if silent_failures else "none")
    )
    passed &= not silent_failures
    lines.append(f"- {_timing(list(results))}")
    return lines, passed


async def probe_topic(settings: Settings, runs: int) -> tuple[list[str], bool]:
    discussions = yaml.safe_load((DATA / "discussions.yaml").read_text())["discussions"]
    jobs = []
    for run in range(runs):
        for item in discussions:
            for kind in ("unrelated", "related"):
                turns = item["turns"] + [{"user": item[kind]}]
                jobs.append((run, item, kind, run_turn(settings, transcript(turns), held_from(turns))))
    results = await asyncio.gather(*(job for *_, job in jobs))

    lines = _header("Topic change probe", settings, runs)
    lines += ["| Run | Discussion | Next message | Proposed | Tools | Proposal title | Message |"]
    lines += ["|---|---|---|---|---|---|---|"]
    score = {"unrelated": [0, 0], "related": [0, 0]}
    for (run, item, kind, _), turn in zip(jobs, results):
        proposed = bool(turn.proposals) and not turn.error
        right = proposed if kind == "unrelated" else not proposed
        score[kind][0] += right
        score[kind][1] += 1
        title = "; ".join(titles_of(turn)) if proposed else ""
        lines.append(
            f"| {run + 1} | {item['id']} | {kind} | {'✓ ' if right else '✗ '}"
            f"{'yes' if proposed else 'no'} | {_tool_cell(turn)} | {_short(str(title), 40)} | "
            f"{_short(item[kind], 50)} |"
        )
    lines += ["", "## Summary", ""]
    passed = True
    for kind, (right, total) in score.items():
        expected = "offered" if kind == "unrelated" else "not offered"
        lines.append(f"- {kind}: {expected} on {right} of {total}")
        passed &= right >= 0.8 * total
    lines.append(f"- {_timing(list(results))}")
    return lines, passed


async def _continue(settings: Settings, item: dict[str, Any]) -> list[Turn]:
    """Play the scripted continuation messages one by one, keeping the model's
    live answers, and store proposals as the chat would."""
    turns = list(item["turns"])
    played = []
    for text in item["continue"]:
        turns.append({"user": text})
        turn = await run_turn(settings, transcript(turns), held_from(turns))
        played.append(turn)
        if turn.proposals:
            try:
                proposal = json.loads(turn.proposals[-1]["arguments"])
            except ValueError:
                proposal = {"title": "", "summary": "", "tags": []}
            turns.append({"proposal": proposal, "reply": turn.text})
        else:
            turns.append({"assistant": turn.text or "…"})
    return played


async def probe_repeat(settings: Settings, runs: int) -> tuple[list[str], bool]:
    discussions = yaml.safe_load((DATA / "discussions.yaml").read_text())["discussions"]
    jobs = [(run, item) for run in range(runs) for item in discussions]
    results = await asyncio.gather(*(_continue(settings, item) for _, item in jobs))

    lines = _header("Repeat proposal probe", settings, runs)
    lines += ["| Run | Discussion | Held title | Turn | Tools | New proposal title |"]
    lines += ["|---|---|---|---|---|---|"]
    repeats: dict[int, set[str]] = {}
    for (run, item), played in zip(jobs, results):
        held_title = held_from(item["turns"])[0]["title"]
        for index, turn in enumerate(played, start=1):
            titles = titles_of(turn) or (["(invalid)"] if turn.proposals else [])
            if turn.proposals:
                repeats.setdefault(run, set()).add(item["id"])
            lines.append(
                f"| {run + 1} | {item['id']} | {_short(held_title, 30)} | {index} | "
                f"{_tool_cell(turn)} | {_short('; '.join(titles), 50)} |"
            )
    lines += ["", "## Summary", ""]
    passed = True
    for run in range(runs):
        found = sorted(repeats.get(run, set()))
        lines.append(
            f"- Run {run + 1}: discussions with a proposal after the held one: {len(found)} of "
            f"{len(discussions)}" + (f" ({', '.join(found)})" if found else "")
        )
        passed &= len(found) <= 1
    lines.append(
        "- Every proposal after the held one counts, since the continuations reach no new "
        "conclusion. Read the titles above to tell a repeat from a new conclusion."
    )
    lines.append(f"- {_timing([t for played in results for t in played])}")
    return lines, passed


async def _summarise(settings: Settings, item: dict[str, Any], keep: int) -> tuple[str, Any, float]:
    plan = plan_compaction(transcript(item["turns"]), keep)
    async with settings.limit:
        started = time.monotonic()
        completion = await _create(settings, compaction_request(plan))
        seconds = time.monotonic() - started
    return (completion.choices[0].message.content or "").strip(), completion, seconds


async def probe_compact(settings: Settings, runs: int) -> tuple[list[str], bool]:
    conversations = yaml.safe_load((DATA / "compact.yaml").read_text())["conversations"]
    keep = load_chat_config().compact_keep_recent
    jobs = [(run, item) for run in range(runs) for item in conversations]
    results = await asyncio.gather(*(_summarise(settings, item, keep) for _, item in jobs))

    lines = _header("/compact probe", settings, runs)
    lines.append(f"The summary replaces every message but the {keep} most recent.")
    lines.append("")
    passed = True
    total_missing = 0
    for (run, item), (summary, completion, seconds) in zip(jobs, results):
        missing = []
        rows = []
        for check in item["checklist"]:
            found = any(re.search(pattern, summary.translate(PLAIN), re.IGNORECASE) for pattern in check["any"])
            rows.append(f"- {'✓' if found else '✗'} {check['kind']}: {check['item']}")
            if not found:
                missing.append(check["item"])
        total_missing += len(missing)
        passed &= not missing
        usage = completion.usage
        lines += [
            f"## Run {run + 1}: {item['id']}",
            "",
            f"{len(item['checklist']) - len(missing)} of {len(item['checklist'])} checklist "
            f"items survive. {seconds:.1f} s, "
            f"{usage.prompt_tokens}+{usage.completion_tokens} tokens, "
            f"finish: {completion.choices[0].finish_reason}.",
            "",
            *rows,
            "",
            "<details><summary>Summary</summary>",
            "",
            summary,
            "",
            "</details>",
            "",
        ]
    lines.insert(len(_header("", settings, runs)) + 2, f"Checklist items missing in total: {total_missing}.\n")
    return lines, passed


QUESTION_WORDS = ("what", "which", "did", "do", "have", "when", "where", "who", "how", "remind", "show", "find", "anything")


def _since_ok(expected: str | None, since: date | None, today: date) -> bool:
    if expected is None:
        return True
    if since is None:
        return False
    if expected == "month":
        return since == today.replace(day=1)
    if expected == "week":
        return today - timedelta(days=8) <= since <= today
    if expected == "year":
        return since == today.replace(month=1, day=1)
    raise ValueError(f"unknown since: {expected}")


async def probe_search(settings: Settings, runs: int) -> tuple[list[str], bool]:
    cases = yaml.safe_load((DATA / "search.yaml").read_text())["cases"]
    today = datetime.now(UTC).date()
    jobs = [
        (run, case, run_turn(settings, transcript([{"user": case["message"]}]), None))
        for run in range(runs)
        for case in cases
    ]
    results = await asyncio.gather(*(job for _, _, job in jobs))

    lines = _header("Search arguments probe", settings, runs)
    lines.append(f"Today, as the prompt says: {today.isoformat()}.")
    lines.append("")
    lines += ["| Run | Case | Searched | Key words | Tag | Since | Arguments |"]
    lines += ["|---|---|---|---|---|---|---|"]
    checks: list[bool] = []
    for (run, case, _), turn in zip(jobs, results):
        search = next((c for c in turn.calls if c["name"] == SEARCH_TOOL and c["valid"]), None)
        searched = not turn.error and turn.first_tool == SEARCH_TOOL and search is not None
        args = parse_search(tool_arguments(search["arguments"])) if search else None
        query = args.query.lower() if args else ""
        keywords = bool(args) and "?" not in query and not query.startswith(QUESTION_WORDS) and any(
            word in query for word in case["words"]
        )
        tag_ok = case.get("tag") is None or bool(
            args and args.tags and case["tag"] in [tag.lower() for tag in args.tags]
        )
        since_ok = _since_ok(case.get("since"), args.since if args else None, today)
        checks += [searched, keywords, tag_ok, since_ok]
        mark = lambda ok: "✓" if ok else "✗"  # noqa: E731
        lines.append(
            f"| {run + 1} | {case['id']} | {mark(searched)} | {mark(keywords)} | "
            f"{mark(tag_ok) if 'tag' in case else '–'} | {mark(since_ok) if 'since' in case else '–'} | "
            f"{_short(search['arguments'] if search else _tool_cell(turn), 60)} |"
        )
    share = sum(checks) / len(checks)
    lines += ["", f"{sum(checks)} of {len(checks)} checks pass ({share:.0%}).", f"- {_timing(list(results))}"]
    return lines, share >= 0.9


async def probe_split(settings: Settings, runs: int) -> tuple[list[str], bool]:
    cases = yaml.safe_load((DATA / "split.yaml").read_text())["cases"]
    jobs = [
        (run, case, run_turn(settings, transcript([{"user": case["message"]}]), None, forced=PROPOSE_TOOL))
        for run in range(runs)
        for case in cases
    ]
    results = await asyncio.gather(*(job for _, _, job in jobs))

    lines = _header("Split probe", settings, runs)
    lines += ["Each message is sent as /push, so the proposal tool is forced.", ""]
    lines += ["| Run | Case | Expected | Parts | Titles | Message |"]
    lines += ["|---|---|---|---|---|---|"]
    right: list[bool] = []
    split_single = []
    for (run, case, _), turn in zip(jobs, results):
        parts = turn.first_parts()
        ok = not turn.error and len(parts) == case["parts"]
        right.append(ok)
        if case["parts"] == 1 and len(parts) > 1:
            split_single.append(f"run {run + 1} {case['id']}")
        lines.append(
            f"| {run + 1} | {case['id']} | {case['parts']} | {'✓ ' if ok else '✗ '}"
            f"{len(parts) if parts else _tool_cell(turn)} | "
            f"{_short('; '.join(p['title'] for p in parts), 60)} | {_short(case['message'], 50)} |"
        )
    share = sum(right) / len(right)
    lines += ["", "## Summary", ""]
    lines.append(f"- Right number of parts: {sum(right)} of {len(right)} ({share:.0%})")
    lines.append(
        "- Single-thing messages split: " + (", ".join(split_single) if split_single else "none")
    )
    claimed = [t for t in results if claims_saved(t)]
    lines.append(f"- Replies that say the proposal was saved: {len(claimed)} of {len(results)}")
    for turn in claimed:
        lines.append(f"  - {_short(turn.text, 90)}")
    lines.append(f"- {_timing(list(results))}")
    # A split single thing is listed but does not fail: the user merges the
    # parts with one click (design decision 10).
    return lines, share >= 0.9


async def probe_filing(settings: Settings, runs: int) -> tuple[list[str], bool]:
    data = yaml.safe_load((DATA / "filing.yaml").read_text())
    categories = list(FIXED_CATEGORIES)
    tools = tools_for(categories, data["known_tags"])
    cases = data["cases"]
    jobs = [
        (
            run,
            case,
            run_turn(
                settings,
                transcript([{"user": case["message"]}]),
                None,
                tools=tools,
                forced=PROPOSE_TOOL,
            ),
        )
        for run in range(runs)
        for case in cases
    ]
    results = await asyncio.gather(*(job for _, _, job in jobs))

    lines = _header("Filing probe", settings, runs)
    lines += [f"Known tags: {', '.join(data['known_tags'])}. Each message is sent as /push.", ""]
    lines += ["| Run | Case | Expected category | Category | Expected tag | Tags |"]
    lines += ["|---|---|---|---|---|---|"]
    category_hits: list[bool] = []
    tag_hits: list[bool] = []
    for (run, case, _), turn in zip(jobs, results):
        parts = turn.first_parts(categories)
        part = parts[0] if parts else None
        category = part["category"] if part else None
        tags = [tag.lower().lstrip("#") for tag in part["tags"]] if part else []
        category_ok = category == case["category"]
        category_hits.append(category_ok)
        tag_cell = "–"
        if case["tag"] is not None:
            tag_ok = case["tag"] in tags
            tag_hits.append(tag_ok)
            tag_cell = f"{'✓' if tag_ok else '✗'} {case['tag']}"
        lines.append(
            f"| {run + 1} | {case['id']} | {case['category']} | {'✓' if category_ok else '✗'} "
            f"{category or (_tool_cell(turn) if not part else 'none')} | {tag_cell} | "
            f"{_short(', '.join(tags), 40)} |"
        )
    category_share = sum(category_hits) / len(category_hits)
    tag_share = sum(tag_hits) / len(tag_hits) if tag_hits else 1.0
    lines += ["", "## Summary", ""]
    lines.append(f"- Expected category: {sum(category_hits)} of {len(category_hits)} ({category_share:.0%})")
    lines.append(f"- Existing tag reused where one fits: {sum(tag_hits)} of {len(tag_hits)} ({tag_share:.0%})")
    claimed = [t for t in results if claims_saved(t)]
    lines.append(f"- Replies that say the proposal was saved: {len(claimed)} of {len(results)}")
    for turn in claimed:
        lines.append(f"  - {_short(turn.text, 90)}")
    lines.append(f"- {_timing(list(results))}")
    return lines, category_share >= 0.8 and tag_share >= 0.8 and len(claimed) <= 0.05 * len(results)


# A reply after a proposal that says it was already saved.
CLAIMS_SAVED = re.compile(
    r"\b(i(.ve| have)? (just )?(noted|saved|added|filed|recorded|stored|logged)|"
    r"i(.ll| will) (remember|keep track|note|save|add|record)|"
    r"(?<!nothing )(?<!nothing\u2019s )(is|are|has been|have been) (now )?(saved|noted|added|filed|recorded|stored|logged))\b",
    re.IGNORECASE,
)


def claims_saved(turn: "Turn") -> bool:
    return bool(turn.proposals) and bool(CLAIMS_SAVED.search(turn.text))


# An answer that says nothing matched, and one that presents something as filed.
SAYS_NOTHING = re.compile(
    r"\b(no|none of your|nothing|not find|couldn.t find|could not find|didn.t find|did not find|"
    r"don.t see|do not see|don.t have|do not have|haven.t (filed|noted|saved)|no record|no match)",
    re.IGNORECASE,
)
CLAIMS_FILED = re.compile(
    r"\b(you (decided|noted|filed|wrote|saved|planned|chose)( down)? (that|to|on)|"
    r"according to your (notes?|thoughts?)|your notes? (say|says|mention))",
    re.IGNORECASE,
)


async def probe_nomatch(settings: Settings, runs: int) -> tuple[list[str], bool]:
    cases = yaml.safe_load((DATA / "nomatch.yaml").read_text())["cases"]
    jobs = [
        (
            run,
            case,
            run_turn(
                settings,
                transcript([{"user": case["message"]}]),
                None,
                forced=SEARCH_TOOL if case["pull"] else None,
            ),
        )
        for run in range(runs)
        for case in cases
    ]
    results = await asyncio.gather(*(job for _, _, job in jobs))

    lines = _header("No-match probe", settings, runs)
    lines += [f"Every search answers: {NO_MATCH}", ""]
    lines += ["| Run | Case | /pull | Searched | Says nothing matched | Claims filed content | Answer |"]
    lines += ["|---|---|---|---|---|---|---|"]
    passes: list[bool] = []
    for (run, case, _), turn in zip(jobs, results):
        searched = any(c["name"] == SEARCH_TOOL for c in turn.calls)
        says = bool(SAYS_NOTHING.search(turn.text))
        claims = bool(CLAIMS_FILED.search(turn.text))
        ok = not turn.error and searched and says and not claims
        passes.append(ok)
        lines.append(
            f"| {run + 1} | {case['id']} | {'yes' if case['pull'] else 'no'} | "
            f"{'✓' if searched else '✗'} | {'✓' if says else '✗'} | {'✗ yes' if claims else '✓ no'} | "
            f"{'✓ ' if ok else '✗ '}{_short(turn.error or turn.text, 90)} |"
        )
    share = sum(passes) / len(passes)
    lines += ["", "## Summary", ""]
    lines.append(f"- Searched, said nothing matched, and claimed nothing: {sum(passes)} of {len(passes)} ({share:.0%})")
    lines.append("- The checks are word patterns: read the answers above to confirm.")
    lines.append(f"- {_timing(list(results))}")
    return lines, share >= 0.95


PROBES = {
    "tools": probe_tools,
    "topic": probe_topic,
    "repeat": probe_repeat,
    "compact": probe_compact,
    "search": probe_search,
    "split": probe_split,
    "filing": probe_filing,
    "nomatch": probe_nomatch,
}


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("probe", choices=PROBES)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", default=None, help="reasoning_effort; not sent by default")
    parser.add_argument("--temperature", type=float, default=None, help="default: chat.yaml")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=8)
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--report", type=Path, help="write the Markdown report here")
    args = parser.parse_args()

    key = os.environ.get("NEBIUS_API_KEY")
    if not key:
        print("Set NEBIUS_API_KEY.", file=sys.stderr)
        return 2
    config = load_chat_config()
    settings = Settings(
        client=AsyncOpenAI(base_url=args.base_url, api_key=key, timeout=180.0, max_retries=3),
        model=args.model,
        temperature=config.temperature.default if args.temperature is None else args.temperature,
        max_tokens=config.reply_max_tokens,
        tool_rounds=config.tool_rounds,
        effort=args.effort,
        limit=asyncio.Semaphore(args.parallel),
    )
    lines, passed = await PROBES[args.probe](settings, args.runs)
    lines += ["", f"**Result: {'pass' if passed else 'fail'}**", ""]
    report = "\n".join(lines)
    if args.report:
        args.report.write_text(report)
    print(report)
    await settings.client.close()
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
