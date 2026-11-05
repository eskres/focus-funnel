"""The dates probe runs end to end with a fake model, and scores it (thought-dates task 2.5)."""

import asyncio
import json
from types import SimpleNamespace

import yaml

from scripts import probe_prompt
from tests.test_probe_prompt import FakeCompletions, _call

CASES = yaml.safe_load((probe_prompt.DATA / "dates.yaml").read_text())["cases"]


def answer_for(case: dict) -> tuple[str, dict]:
    """The call a model that gets every case right makes."""
    if "search" in case:
        search = case["search"]
        arguments = {"dated_from": search["dated_from"], "dated_to": search["dated_to"]}
        if search["words"]:
            arguments["query"] = search["words"][0]
        return probe_prompt.SEARCH_TOOL, arguments
    part = {"title": case["id"], "summary": case["message"], "tags": [], "category": "task"}
    if case.get("when_choices"):
        part["when_choices"] = case["when_choices"]
    elif case.get("when"):
        part["when"] = case["when"]
    return probe_prompt.PROPOSE_TOOL, {"thoughts": [part]}


class RightCompletions:
    """Answers each case as the data set expects, from its message and the
    date the system prompt names; then replies in words."""

    def __init__(self, wrong: set[str] = frozenset()):
        self.requests: list[dict] = []
        self.wrong = wrong

    async def create(self, **request):
        self.requests.append(request)
        messages = request["messages"]
        tool_calls = None
        if messages[-1]["role"] == "user":
            prompt = messages[0]["content"]
            [case] = [
                c for c in CASES
                if c["message"] == messages[-1]["content"] and f" {c['today']}. " in prompt
            ]
            name, arguments = answer_for(case)
            if case["id"] in self.wrong:
                # One date for an ambiguous day, or choices for a clear one.
                part = arguments["thoughts"][0]
                part["when"], part["when_choices"] = (
                    (part.pop("when_choices")[0], None)
                    if "when_choices" in part
                    else (None, [part["when"], {"start": "2026-10-09T19:00"}])
                )
            tool_calls = [_call(name, arguments)]
        message = SimpleNamespace(content=None if tool_calls else "Ready to check.", tool_calls=tool_calls)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
        )


def run_probe(completions, runs=1):
    settings = probe_prompt.Settings(
        client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
        model="fake/model",
        temperature=0.3,
        max_tokens=512,
        tool_rounds=3,
        effort=None,
        limit=asyncio.Semaphore(4),
    )
    return asyncio.run(probe_prompt.PROBES["dates"](settings, runs))


def test_the_data_set_holds_the_required_cases():
    ids = {case["id"] for case in CASES}
    assert {
        "plumber-monday", "dinner-friday", "oslo-trip", "meeting-tuesday", "podcast-idea",
        "dentist-tomorrow", "this-week", "dinners-this-month",
        "friday-said-on-friday", "next-friday", "friday-said-on-wednesday",
    } <= ids
    this_week = next(case for case in CASES if case["id"] == "this-week")
    # Said on Friday 2 October: Monday to Sunday.
    assert this_week["search"]["dated_from"] == "2026-09-28"
    assert this_week["search"]["dated_to"] == "2026-10-04"


class FirstPrompts(FakeCompletions):
    """Keeps the system prompt of each turn's first request, as it was sent."""

    def __init__(self):
        super().__init__()
        self.prompts: list[str] = []

    async def create(self, **request):
        if request["messages"][-1]["role"] == "user":
            self.prompts.append(request["messages"][0]["content"])
        return await super().create(**request)


def test_each_case_is_asked_on_its_own_day():
    completions = FirstPrompts()
    run_probe(completions)
    prompts = completions.prompts
    assert len(prompts) == len(CASES)
    for case, prompt in zip(CASES, prompts):
        assert f" {case['today']}. Weeks start on Monday." in prompt


def test_a_model_that_gets_every_case_right_passes():
    lines, passed = run_probe(RightCompletions(), runs=2)
    report = "\n".join(lines)
    assert passed
    assert f"{2 * len(CASES)} of {2 * len(CASES)} (100%)" in report
    assert "| 1 | friday-said-on-friday | Fri 2026-10-02 | 2026-10-02T19:00 or 2026-10-09T19:00 (choices) | ✓ " in report
    assert "| 1 | oslo-trip | Wed 2026-09-30 | 2026-11-03 to 2026-11-06 | ✓ 2026-11-03 to 2026-11-06 |" in report
    assert "Ambiguous days given one date: none" in report


def test_a_guessed_ambiguous_day_and_choices_for_a_clear_day_are_listed():
    lines, _ = run_probe(RightCompletions(wrong={"next-friday", "friday-said-on-wednesday"}))
    report = "\n".join(lines)
    assert "Ambiguous days given one date: run 1 next-friday" in report
    assert "Clear days given two choices: run 1 friday-said-on-wednesday" in report
    assert "| 1 | next-friday | Wed 2026-09-30 | 2026-10-02 or 2026-10-09 (choices) | ✗ 2026-10-02 |" in report


def test_the_fake_that_never_dates_fails_but_gets_the_undated_idea_right():
    lines, passed = run_probe(FakeCompletions())
    report = "\n".join(lines)
    assert not passed
    assert "| 1 | podcast-idea | Wed 2026-09-30 | no date | ✓ no date |" in report
    # It answers questions in words and never searches.
    assert "| 1 | this-week | Fri 2026-10-02 | search 2026-09-28 to 2026-10-04 | ✗ none |" in report


def test_a_search_with_a_question_for_a_query_fails():
    assert probe_prompt._query_ok(None, None)
    assert probe_prompt._query_ok(None, " ")
    assert not probe_prompt._query_ok(None, "events")
    assert probe_prompt._query_ok(["dinner"], "dinner")
    assert not probe_prompt._query_ok(["dinner"], "what dinners do I have?")
    assert json.dumps(answer_for(CASES[0])[1])
