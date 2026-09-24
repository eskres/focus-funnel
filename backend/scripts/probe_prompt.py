"""Probe the chat's system prompt and tools against a real model.

Four probes, each with its data set in scripts/probe_data/:

  tools    labelled messages: does the model pick the tool the label names?
  topic    a held proposal, then an unrelated or a related message: does the
           model offer the held summary only on the unrelated one?
  repeat   a held proposal, then the user keeps going on the same topic: does
           the model propose the same conclusion again?
  compact  long conversations summarised as /compact does: do the checklist
           items survive in the summary?

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
    tool_arguments,
)
from app.chat.tools import PROPOSAL_SHOWN, ToolArgumentError, parse_proposal
from app.models import Message

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
    held: dict[str, Any] | None = None

    @property
    def first_tool(self) -> str | None:
        return self.calls[0]["name"] if self.calls else None

    @property
    def proposals(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["name"] == PROPOSE_TOOL]


# ---------------------------------------------------------------- transcript


def _message(position: int, role: str, content: str | None = None, **extra: Any) -> Message:
    return Message(
        id=uuid.uuid4(), position=position, role=role, content=content, compacted=False, **extra
    )


def transcript(turns: list[dict[str, Any]]) -> list[Message]:
    """Stored messages from a data set's turns.

    A turn is {user: text}, {assistant: text}, or {proposal: {title, summary,
    tags}, reply: text}, which is stored as the chat stores a proposal: a tool
    call, its result, and the model's short reply.
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


def held_from(turns: list[dict[str, Any]]) -> dict[str, Any] | None:
    held = None
    for turn in turns:
        if "proposal" in turn:
            held = turn["proposal"]
    return held


# ---------------------------------------------------------------- model calls


def _valid(name: str, raw: str) -> bool:
    try:
        arguments = tool_arguments(raw)
        if name == PROPOSE_TOOL:
            parse_proposal(arguments)
            return True
        if name == SEARCH_TOOL:
            query = arguments.get("query")
            return isinstance(query, str) and bool(query.strip())
    except (ValueError, ToolArgumentError):
        return False
    return False


def _tool_result(name: str, valid: bool) -> str:
    if not valid:
        return "Error: the arguments do not fit the tool. Call the tool again with valid arguments."
    if name == SEARCH_TOOL:
        return "No filed thoughts match."
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
    settings: Settings, messages: list[Message], held: dict[str, Any] | None
) -> Turn:
    """Run one user turn the way the chat does: with tools, running each call
    and calling the model again, up to the round limit. The search tool finds
    nothing and a proposal is shown."""
    turn = Turn(held=held)
    context = build_context(messages, held)
    async with settings.limit:
        for round_number in range(settings.tool_rounds):
            started = time.monotonic()
            try:
                completion = await _create(settings, context, tools=TOOLS)
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
        title = json.loads(turn.proposals[0]["arguments"]).get("title", "") if proposed else ""
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
        held_title = held_from(item["turns"])["title"]
        for index, turn in enumerate(played, start=1):
            titles = []
            for call in turn.proposals:
                try:
                    titles.append(json.loads(call["arguments"]).get("title", ""))
                except ValueError:
                    titles.append("(invalid)")
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


PROBES = {
    "tools": probe_tools,
    "topic": probe_topic,
    "repeat": probe_repeat,
    "compact": probe_compact,
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
