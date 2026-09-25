"""Every prompt probe runs end to end against a fake model (push-and-pull task 7.1)."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from scripts import probe_prompt


def _call(name: str, arguments: dict) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"call_{name}",
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


class FakeCompletions:
    """Proposes when the proposal tool is forced, searches when the search
    tool is, and otherwise answers in words that say nothing matched."""

    def __init__(self):
        self.requests: list[dict] = []

    async def create(self, **request):
        self.requests.append(request)
        forced = (request.get("tool_choice") or {}).get("function", {}).get("name")
        tool_calls = None
        text = "I found nothing filed about that."
        if forced == probe_prompt.PROPOSE_TOOL:
            part = {"title": "Oat milk", "summary": "Buy oat milk.", "tags": ["groceries"], "category": "task"}
            tool_calls = [_call(forced, {"thoughts": [part]})]
        elif forced == probe_prompt.SEARCH_TOOL:
            tool_calls = [_call(forced, {"query": "boat"})]
        message = SimpleNamespace(content=None if tool_calls else text, tool_calls=tool_calls)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
        )


@pytest.mark.parametrize("name", list(probe_prompt.PROBES))
def test_each_probe_runs_with_a_fake_model(name, settings_env):
    completions = FakeCompletions()

    async def run():
        settings = probe_prompt.Settings(
            client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
            model="fake/model",
            temperature=0.3,
            max_tokens=512,
            tool_rounds=3,
            effort=None,
            limit=asyncio.Semaphore(4),
        )
        return await probe_prompt.PROBES[name](settings, 1)

    lines, passed = asyncio.run(run())

    assert completions.requests
    assert any(line.startswith("|") for line in lines) or name == "compact"
    assert isinstance(passed, bool)


def test_the_fake_model_passes_the_new_probes_it_is_built_for(settings_env):
    completions = FakeCompletions()

    async def run(name):
        settings = probe_prompt.Settings(
            client=SimpleNamespace(chat=SimpleNamespace(completions=completions)),
            model="fake/model",
            temperature=0.3,
            max_tokens=512,
            tool_rounds=3,
            effort=None,
            limit=asyncio.Semaphore(4),
        )
        return await probe_prompt.PROBES[name](settings, 1)

    # Every /pull and plain question ends in an answer that says nothing matched.
    lines, _ = asyncio.run(run("nomatch"))
    assert "| boat | yes | ✓ | ✓ | ✓ no |" in "\n".join(lines)
    # One part for every message: right for single things, wrong for the rest.
    lines, passed = asyncio.run(run("split"))
    assert not passed  # 12 of 28 right is below the 90% bar
    assert "Single-thing messages split: none" in "\n".join(lines)


@pytest.mark.parametrize(
    "reply, claims",
    [
        ("I've noted those three items for you.", True),
        ("I've added those grocery tasks for you.", True),
        ("Your task has been saved.", True),
        ("Okay, I'll remember to buy oat milk tomorrow.", True),
        ("It is ready for you to check and confirm.", False),
        ("Here is a card to review; nothing is saved until you confirm.", False),
    ],
)
def test_a_reply_that_says_the_proposal_was_saved_is_caught(reply, claims):
    assert bool(probe_prompt.CLAIMS_SAVED.search(reply)) is claims
