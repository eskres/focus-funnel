"""The status probe and the status steering (thought-status task 3.10)."""

import asyncio
import json
import re
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import yaml

from app.chat.prompt import (
    MARKS_DESCRIPTION,
    OFFER_NOTE,
    SEARCH_TOOL_SCHEMA,
    SYSTEM_PROMPT,
    propose_tool_schema,
)
from app.chat.refs import Refs
from app.chat.similar import (
    REPEATED_TASK,
    SEND_MARKS_AGAIN,
    Candidate,
    Check,
    PartCheck,
    candidates_note,
)
from app.chat.tools import parse_proposal
from app.thoughts.categories import FIXED_CATEGORIES
from scripts import probe_prompt
from tests.test_probe_prompt import _call

DATA = yaml.safe_load((probe_prompt.DATA / "status.yaml").read_text())
CASES = {case["id"]: case for case in DATA["cases"]}
OAT_MILK = {"title": "Buy oat milk", "summary": "Buy oat milk.", "tags": ["groceries"], "category": "task"}
HELD_HEAD = "A proposal from this conversation was shown to the user"


def flat(text: str) -> str:
    return " ".join(text.split())


# --- the steering ---


def test_the_prompt_and_tool_descriptions_hold_each_rule():
    prompt = flat(SYSTEM_PROMPT)
    for rule in (
        "When the user says they finished something",
        "propose marking it done: put its ref in marks of propose_thought",
        "Send a mark only with a ref this conversation has seen",
        "never guess a ref",
        "first search for it with status open, before any proposal in this turn, then make "
        "one proposal with the mark on the ref the search gives and anything new to file",
        "When that search finds no open thought for it, propose no mark",
        "mark only the most recently filed one, and name the older ones in your reply",
        "When a list of similar thoughts holds a thing the user says they finished, mark that "
        "ref done instead of proposing it as new or as an addition, also after /push",
        "Nothing changes until the user confirms a mark, so never say a thought was marked done",
        "When the user asks what is open, left, or still to do, search with status open, and "
        "with category task for tasks",
        "When they ask about a thing whatever its status, such as whether they did it, pass no status",
    ):
        assert rule in prompt, rule
    marks = flat(MARKS_DESCRIPTION)
    assert "Give only a ref this conversation has seen" in marks
    assert "put an addition or a date in its own entry in thoughts" in marks
    schema = propose_tool_schema(list(FIXED_CATEGORIES), [])["function"]
    assert schema["parameters"]["properties"]["marks"]["description"] == MARKS_DESCRIPTION
    assert "put its ref in marks" in schema["description"]
    search = SEARCH_TOOL_SCHEMA["function"]
    assert "pass status open (and category task)" in flat(search["description"])
    status = flat(search["parameters"]["properties"]["status"]["description"])
    assert "Pass it for what is open, left, or still to do" in status
    assert "Leave it out to find done thoughts too" in status


def test_the_offer_note_leaves_out_a_finished_task():
    assert "A finished task this conversation already proposed to mark done needs no new thought." in OFFER_NOTE


@pytest.mark.parametrize(
    "reply, claims",
    [
        ("I've marked it done.", True),
        ("I marked the plumber task as done.", True),
        ("Call the plumber is now done.", True),
        ("The task has been marked complete.", True),
        ("I've closed the plumber task for you.", True),
        ("Marked it as done!", True),
        ("The change is ready for you to confirm.", False),
        ("Confirm the card to mark it done.", False),
        ("Once you confirm, Call the plumber will be marked done.", False),
    ],
)
def test_claims_done_catches_a_reply_that_says_it_was_marked(reply, claims):
    assert probe_prompt.claims_done(reply) is claims


# --- a fake model ---


def _ref(text: str, title: str, newest: bool = False) -> str | None:
    found = re.findall(rf"(T\d+) · {re.escape(title)} · filed (\d{{4}}-\d{{2}}-\d{{2}})", text)
    if not found:
        return None
    return max(found, key=lambda item: item[1])[0] if newest else found[0][0]


class StatusModel:
    """Answers each status case as the steering asks. `wrong` names the
    mistakes to make: `oldest` marks the first of several open matches,
    `claim` says the thought was marked done, `add_to` answers a candidate
    round for the plumber with an addition."""

    def __init__(self, wrong: frozenset[str] = frozenset()):
        self.wrong = wrong
        self.requests: list[dict] = []

    def _answer(self, request) -> tuple[str | None, dict | None, str | None]:
        messages = request["messages"]
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        said = messages[last_user]["content"].lower()
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        results = [m["content"] for m in messages[last_user:] if m["role"] == "tool"]
        last = results[-1] if results else None
        held = HELD_HEAD in system
        oat_milk = "oat milk" in said and "bought" not in said and "did i" not in said
        new_parts = ([OAT_MILK] if oat_milk or held else [])

        if "The user is about to archive or compact" in system:
            return None, None, "nothing"
        if last is not None and last.startswith("Nothing was proposed yet"):
            plumber = _ref(last, "Call the plumber")
            if plumber is not None:
                if "add_to" in self.wrong:
                    part = {**OAT_MILK, "title": "Called the plumber", "summary": "Called him.", "add_to": plumber}
                    return probe_prompt.PROPOSE_TOOL, {"thoughts": [part]}, None
                return probe_prompt.PROPOSE_TOOL, {"thoughts": [], "marks": [{"ref": plumber}]}, None
            asked = json.loads(messages[-2]["tool_calls"][0]["function"]["arguments"])
            marks = asked.get("marks", [])
            return probe_prompt.PROPOSE_TOOL, {"thoughts": [{**OAT_MILK, "new": True}], "marks": marks}, None
        if last is not None and "is already done" in last:
            return probe_prompt.PROPOSE_TOOL, {"thoughts": [OAT_MILK]}, None
        if last is not None and "is not a thought this conversation has seen" in last:
            return probe_prompt.SEARCH_TOOL, {"query": "plumber", "status": "open"}, None
        if last is not None and last.startswith("The proposal is now shown"):
            reply = "I've marked it done." if "claim" in self.wrong else "It is ready for you to confirm."
            return None, None, reply
        if last is not None:  # a search result
            if "?" in said or last.startswith("No filed thoughts"):
                text = "That card was never filed; you can pass it over." if held else "Nothing open matches."
                return None, None, text if last.startswith("No filed") else "Here is what I found."
            title = "Buy oat milk" if "oat milk" in said and "bought" in said else "Call the plumber"
            ref = _ref(last, title, newest="oldest" not in self.wrong)
            return probe_prompt.PROPOSE_TOOL, {"thoughts": new_parts, "marks": [{"ref": ref}]}, None
        # The turn's first call.
        if "still open" in said:
            return probe_prompt.SEARCH_TOOL, {"status": "open", "category": "task"}, None
        if said.startswith("did i"):
            return probe_prompt.SEARCH_TOOL, {"query": "oat milk"}, None
        forced = (request.get("tool_choice") or {}).get("function", {}).get("name")
        if forced == probe_prompt.PROPOSE_TOOL:
            if "oat milk" in said:
                return probe_prompt.PROPOSE_TOOL, {"thoughts": [OAT_MILK]}, None
            note = {"title": "Called the plumber", "summary": "The user called the plumber.", "tags": ["home"], "category": "task"}
            return probe_prompt.PROPOSE_TOOL, {"thoughts": [note]}, None
        seen = _ref(system.split("Thoughts this conversation has seen")[-1], "Call the plumber") if (
            "Thoughts this conversation has seen" in system
        ) else None
        if seen is not None:
            return probe_prompt.PROPOSE_TOOL, {"thoughts": new_parts, "marks": [{"ref": seen}]}, None
        query = "plumber" if "plumber" in said else "oat milk"
        return probe_prompt.SEARCH_TOOL, {"query": query, "status": "open"}, None

    async def create(self, **request):
        self.requests.append(request)
        name, arguments, text = self._answer(request)
        tool_calls = [_call(name, arguments)] if name else None
        message = SimpleNamespace(content=None if tool_calls else text, tool_calls=tool_calls)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
        )


def settings_for(completions, tool_rounds=4):
    return probe_prompt.Settings(
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        model="fake/model",
        temperature=0.3,
        max_tokens=512,
        tool_rounds=tool_rounds,
        effort=None,
        limit=asyncio.Semaphore(4),
    )


def run_probe(completions, runs=2):
    return asyncio.run(probe_prompt.probe_status(settings_for(completions), runs))


def share_of(lines, case_id) -> str:
    [line] = [line for line in lines if line.startswith(f"- {case_id} (")]
    return line


def tool_texts(completions) -> list[str]:
    return [
        m["content"]
        for request in completions.requests
        for m in request["messages"]
        if m["role"] == "tool"
    ]


# --- the probe on a fake model ---


def test_the_data_set_has_a_case_per_scenario():
    assert {case["scenario"] for case in DATA["cases"]} >= {
        "I called the plumber",
        "Done and something new",
        "Only a finished task at /compact",
        "Mark kept through a similar-thought question",
        "Reply before confirm",
        "Task filed in another conversation",
        "Nothing open matches",
        "Unseen finished task and something new",
        "Push a finished task the conversation has not seen",
        "Finished task listed as a similar thought",
        "Several open matches",
        "Finished task question for a task part",
        "Finished before it was filed",
        "Held proposal and an unseen finished task",
        "Held proposal and a seen finished task",
        "Refused mark beside a new thought",
        "What tasks are still open",
        "Did I do it",
        "Repeated task",
    }


def test_a_right_model_passes_end_to_end_and_gets_the_canned_results():
    completions = StatusModel()

    lines, passed = run_probe(completions)

    report = "\n".join(lines)
    assert passed, report
    for case in DATA["cases"]:
        assert share_of(lines, case["id"]).endswith("2 of 2 (100%)"), report
    texts = tool_texts(completions)
    # The canned search result, by the app's own formatter, with refs.
    assert any(t.startswith("1 of your thoughts match (newest first):\n1. T1 · Call the plumber · filed 2026-10-28") for t in texts)
    assert any("1. T1 · Buy oat milk · filed 2026-10-05" in t and "2. T2 · Buy oat milk · filed 2026-11-04" in t for t in texts)
    # The canned candidate round, with the marks line, and the refusal.
    assert any(t.startswith("Nothing was proposed yet") and t.rstrip().endswith(SEND_MARKS_AGAIN) for t in texts)
    assert any(
        t == "Error: T1 is already done. Do not propose marking it done; tell the user it is "
        "already done.\nNothing was proposed. Call propose_thought again with the call's "
        "other parts, without T1."
        for t in texts
    )
    assert "Replies after a mark that say it was marked done: 0 of" in report


def test_the_task_part_round_is_the_formatters_own():
    case = CASES["task-part-question"]
    world = probe_prompt.StatusWorld(DATA, case)

    context, _, forced = world.context()

    assert forced == probe_prompt.PROPOSE_TOOL
    prior = context[-1]["content"]
    plumber = world.thoughts["plumber"]
    parts = parse_proposal(case["prior_call"], list(FIXED_CATEGORIES))
    expected, _ = candidates_note(
        parts,
        Check(parts=[PartCheck(candidates=[Candidate(thought=plumber, similarity=None)])]),
        Refs([], {}, []),
        world.config.filing.seen_summary_chars,
        ZoneInfo("UTC"),
    )
    assert prior == expected
    assert REPEATED_TASK in prior
    assert REPEATED_TASK == "A repeated task is usually a new task, unless the user says they finished it."


def test_marking_the_older_of_several_open_matches_fails_that_case_and_the_probe():
    lines, passed = run_probe(StatusModel(wrong=frozenset({"oldest"})))

    assert not passed
    assert share_of(lines, "several-open").endswith("0 of 2 (0%)")
    # Every other case passes: the share over all runs is above 80%.
    [total] = [line for line in lines if line.startswith("- All cases: ")]
    right, of = (int(n) for n in re.findall(r"(\d+) of (\d+)", total)[0])
    assert right / of > 0.8


def test_a_reply_that_says_it_was_marked_done_fails():
    lines, passed = run_probe(StatusModel(wrong=frozenset({"claim"})))

    assert not passed
    assert any(line.startswith("  - run 1 called-plumber: I've marked it done.") for line in lines)


def test_a_forced_push_answered_with_add_to_fails():
    lines, passed = run_probe(StatusModel(wrong=frozenset({"add_to"})))

    assert not passed
    assert share_of(lines, "push-unseen").endswith("0 of 2 (0%)")
    assert share_of(lines, "similar-finished").endswith("0 of 2 (0%)")
