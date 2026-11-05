"""The similar-thought measurement job (thought-appending task 5.1).

These tests run the job with a fake embedder and a fake chat model, so they
prove that the rates and the exit status are computed correctly. They prove
nothing about a real model: that is the job's own run with a real key.
"""

import json
import random
from dataclasses import replace
from pathlib import Path

import pytest

from app.chat.config import load_chat_config
from app.chat.prompt import PROPOSE_TOOL
from app.evals import similar_thoughts as job
from app.thoughts.baseline import MAX_PAIRS
from tests.chat_helpers import FakeLLM, completion, tool_call
from tests.thought_helpers import EMBED_MODEL

DIM = 8


def basis(index: int, extra: dict[int, float] | None = None) -> list[float]:
    vector = [0.0] * DIM
    vector[index] = 1.0
    for other, value in (extra or {}).items():
        vector[other] = value
    return vector


# Each thought's vector, by its title (the first line of its head text).
VECTORS = {
    "Sourdough": basis(0),
    "Bread at home": basis(0),  # the same thing revisited: found
    "Standing desk": basis(1),
    "Back pain": basis(2),  # the same thing in words the model misses: not found
    "Guitar": basis(3),
    "Piano": basis(4),  # same topic, a different thing: no hint
    "Dentist 2024": basis(5),
    "Dentist 2025": basis(5),  # a repeated task: a candidate, never a hint
    "Other one": basis(6),
    "Other two": basis(7),
}


def embedder(vectors: dict[str, list[float]]):
    def embed(text: str) -> list[float]:
        return vectors[text.split("\n")[0]]

    return embed


def thought(title: str, category: str = "idea") -> dict:
    return {"title": title, "summary": f"About {title.lower()}.", "tags": ["test"], "category": category}


def write_set(path: Path, recall: float = 0.5, false_offers: float = 0.0) -> Path:
    data = {
        "targets": {"recall": recall, "false_offers": false_offers},
        "pairs": [
            {"id": "p1", "filed": thought("Sourdough"), "later": thought("Bread at home")},
            {"id": "p2", "filed": thought("Standing desk"), "later": thought("Back pain")},
        ],
        "near_misses": [
            {"id": "n1", "filed": thought("Guitar"), "later": thought("Piano")},
            {
                "id": "n2",
                "filed": {**thought("Dentist 2024", "task"), "filed": "2024-03-04"},
                "later": thought("Dentist 2025", "task"),
            },
        ],
        "background": [thought("Other one", "note"), thought("Other two", "task")],
    }
    target = path / "set.yaml"
    target.write_text(json.dumps(data))  # JSON is YAML
    return target


@pytest.fixture
def fake(monkeypatch) -> FakeLLM:
    monkeypatch.setenv("NEBIUS_API_KEY", "nb-test-key")
    llm = FakeLLM()
    llm.embedder = embedder(VECTORS)
    return llm


def run_job(fake: FakeLLM, *args: str) -> int:
    return job.main(["--model", EMBED_MODEL, *args], http_client=fake.http_client())


# ---------------------------------------------------------------- rates and exit status


def test_rates_and_targets_met(fake, tmp_path, capsys):
    report = tmp_path / "report.md"
    status = run_job(fake, "--test-set", str(write_set(tmp_path)), "--report", str(report))

    assert status == 0
    out = capsys.readouterr().out
    assert "| Recall (filed thought among the candidates) | 0.500 (1/2) | ≥ 0.50 | met |" in out
    # n2 is a task: the app never shows the hint for it, so only n1 counts.
    assert "| False offers (near-miss gets the hint) | 0.000 (0/1) | ≤ 0.00 | met |" in out
    assert "Overall: every target met." in out
    assert report.read_text() in out
    # Six thoughts in the corpus: fewer than min_thoughts, so no baseline,
    # and the cut-offs are the floor and the search cut-off for a model with
    # no chat.yaml rule (0.35).
    assert "p95 –, p99 –" in out
    assert "Candidate cut-off 0.250, strong cut-off 0.350." in out
    # Every text in one embedding request (10 < BATCH), with the app's dimensions.
    assert len(fake.embed_requests) == 1
    request = fake.embed_requests[0]
    assert request["model"] == EMBED_MODEL
    assert request["dimensions"] == 256
    assert len(request["input"]) == 10
    assert not fake.chat_requests


def test_recall_below_target_fails(fake, tmp_path, capsys):
    status = run_job(fake, "--test-set", str(write_set(tmp_path, recall=0.9)))

    assert status == 1
    out = capsys.readouterr().out
    assert "| 0.500 (1/2) | ≥ 0.90 | MISSED |" in out
    assert "Overall: a target was missed." in out


def test_false_offers_above_target_fails(fake, tmp_path, capsys):
    # The piano is now close to the guitar: past the strong cut-off.
    fake.embedder = embedder({**VECTORS, "Piano": basis(3, {4: 0.2})})

    status = run_job(fake, "--test-set", str(write_set(tmp_path, false_offers=0.1)))

    assert status == 1
    out = capsys.readouterr().out
    assert "| False offers (near-miss gets the hint) | 1.000 (1/1) | ≤ 0.10 | MISSED |" in out
    assert "| ✗ n1 Piano | near-miss | Guitar (0.981, 1) | Guitar (0.981) | Guitar | – |" in out


def test_native_dimensions_send_none(fake, tmp_path):
    assert run_job(fake, "--test-set", str(write_set(tmp_path)), "--dimensions", "native") == 0
    assert "dimensions" not in fake.embed_requests[0]


def test_cannot_run_without_a_key(fake, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("NEBIUS_API_KEY")

    assert run_job(fake, "--test-set", str(write_set(tmp_path))) == 2
    assert "Set NEBIUS_API_KEY." in capsys.readouterr().err
    assert not fake.embed_requests


def test_a_bad_test_set_or_provider_error_cannot_run(fake, tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("targets: {recall: 2, false_offers: 0.1}\npairs: []\n")
    assert run_job(fake, "--test-set", str(bad)) == 2
    assert "targets.recall must be a number from 0 to 1" in capsys.readouterr().err

    fake.embed_replies.append(lambda request: __import__("httpx2").Response(401, json={}))
    assert run_job(fake, "--test-set", str(write_set(tmp_path))) == 2
    assert "The embedding provider failed" in capsys.readouterr().err


# ---------------------------------------------------------------- baseline


def test_percentile_matches_postgres_percentile_cont():
    assert job.percentile_cont([1, 2, 3, 4, 5], 0.95) == pytest.approx(4.8)
    assert job.percentile_cont([5, 1, 3], 0.5) == 3
    assert job.percentile_cont([0.2], 0.99) == 0.2


def test_baseline_compares_every_pair_up_to_the_limit():
    rng = random.Random(1)
    heads = [job.normalized([rng.random() for _ in range(4)]) for _ in range(12)]

    baseline = job.measure_baseline(heads, min_thoughts=2)

    direct = [job.cosine(heads[i], heads[j]) for i in range(12) for j in range(i + 1, 12)]
    assert baseline.pairs == 66
    assert baseline.p95 == pytest.approx(job.percentile_cont(direct, 0.95))
    assert baseline.p99 == pytest.approx(job.percentile_cont(direct, 0.99))
    assert job.measure_baseline(heads, min_thoughts=13).p95 is None


def test_baseline_samples_past_the_limit():
    pairs = job.baseline_pairs(100, random.Random(0))
    assert len(pairs) == MAX_PAIRS
    assert all(i != j and 0 <= i < 100 and 0 <= j < 100 for i, j in pairs)
    assert pairs == job.baseline_pairs(100, random.Random(0))


def test_cutoffs_come_from_the_baseline(tmp_path):
    base = load_chat_config()
    config = replace(base, filing=replace(base.filing, similar=replace(base.filing.similar, min_thoughts=2)))
    test_set = job.load_test_set(write_set(tmp_path))
    # Unrelated corpus thoughts share a little of one dimension, so the
    # baseline is not zero.
    vectors = {key: [*embedder(VECTORS)(text), 0.5] for key, text in test_set.texts().items()}

    evaluation = job.evaluate(test_set, vectors, provider="nebius", model=EMBED_MODEL, config=config)

    heads = [job.normalized(vectors[item.key]) for item in test_set.corpus]
    direct = [job.cosine(a, b) for n, a in enumerate(heads) for b in heads[n + 1 :]]
    p95, p99 = job.percentile_cont(direct, 0.95), job.percentile_cont(direct, 0.99)
    assert evaluation.baseline.p95 == pytest.approx(p95)
    assert evaluation.limits.candidate == pytest.approx(max(p95 + 0.02, 0.25))
    assert evaluation.limits.strong == pytest.approx(max(p99 + 0.02, 0.25))


# ---------------------------------------------------------------- layer 2


def propose(**extra) -> dict:
    part = {"title": "T", "summary": "S.", "tags": [], "category": "idea", **extra}
    return completion(None, [tool_call(PROPOSE_TOOL, {"thoughts": [part]})], "tool_calls")


def test_layer2_counts_the_model_picking_right(fake, tmp_path, capsys):
    # Cases with candidates: p1 (pair, adds to T1) and n2 (repeated task, new).
    fake.queue(propose(add_to="T1"), propose(new=True))

    status = run_job(fake, "--test-set", str(write_set(tmp_path)), "--chat-model", "vendor/nano-model")

    assert status == 0
    out = capsys.readouterr().out
    assert "| Model picks right (layer 2) | 1.000 (2/2) | – | |" in out
    assert "right: add_to T1" in out and "right: new" in out
    first, second = fake.chat_requests
    assert first["tool_choice"] == {"type": "function", "function": {"name": PROPOSE_TOOL}}
    assert first["model"] == "vendor/nano-model"
    note = first["messages"][-1]["content"]
    assert first["messages"][-1]["role"] == "tool"
    assert "T1 · Sourdough · filed" in note
    assert "A repeated task is usually a new task." in second["messages"][-1]["content"]
    assert "T1 · Dentist 2024 · filed 2024-03-04" in second["messages"][-1]["content"]


def test_layer2_wrong_choices_are_counted_and_have_no_target(fake, tmp_path, capsys):
    # The pair kept new, the repeated task added to the old one.
    fake.queue(propose(new=True), propose(add_to="T1"))

    status = run_job(fake, "--test-set", str(write_set(tmp_path)), "--chat-model", "vendor/nano-model")

    assert status == 0
    out = capsys.readouterr().out
    assert "| Model picks right (layer 2) | 0.000 (0/2) | – | |" in out
    assert "wrong: new" in out and "wrong: add_to T1" in out


def test_layer2_without_a_call_is_wrong(fake, tmp_path, capsys):
    fake.queue(completion("I'd rather not."), propose(add_to="T7"))

    run_job(fake, "--test-set", str(write_set(tmp_path)), "--chat-model", "vendor/nano-model")

    out = capsys.readouterr().out
    assert "wrong: no propose_thought call" in out
    # A ref the conversation has not seen is not the filed thought.
    assert "wrong: add_to T7" in out


# ---------------------------------------------------------------- the shipped test set


def test_the_shipped_test_set():
    test_set = job.load_test_set()

    pairs = [case for case in test_set.cases if case.kind == job.PAIR]
    near = [case for case in test_set.cases if case.kind == job.NEAR_MISS]
    assert 25 <= len(pairs) <= 35
    assert 25 <= len(near) <= 35
    assert 180 <= len(test_set.background) <= 220
    # Repeated tasks are among the near-misses.
    assert sum(case.later.category == "task" for case in near) >= 8
    assert test_set.targets == job.Targets(recall=0.9, false_offers=0.1)
    texts = test_set.texts()
    assert len(texts) == len(test_set.corpus) + len(test_set.cases)
    assert len(set(texts.values())) == len(texts)
