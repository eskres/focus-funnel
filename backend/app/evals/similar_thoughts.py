"""Measure the similar-thought check for an embedding model (thought-appending
design decision 6).

Run by the operator from backend/, never through the API:

  uv run python -m app.evals.similar_thoughts [--provider nebius]
      [--model Qwen/Qwen3-Embedding-8B] [--dimensions 256|native]
      [--chat-provider nebius --chat-model <id>] [--test-set <yaml>]
      [--report report.md]

The provider, model, and dimensions default to the app's embedding settings.
The key comes from <PROVIDER>_API_KEY in the environment, for example
NEBIUS_API_KEY (and the chat provider's key the same way).

It reads the labelled test set in backend/evals/similar_thoughts.yaml, embeds
every thought's head entry (title, tags, summary, as the app embeds it and the
check's query) in one in-memory index, measures the baseline as the app does
(design decision 5: the 95th and 99th percentile of similarity between every
pair of head entries, or 2,000 random pairs past that many), and sets the
check's two cut-offs from it and chat.yaml. Then, for each case, the later
thought's candidates are the corpus thoughts past the candidate cut-off, best
first, at most three. It reports:

  recall        share of pairs whose filed thought is among the candidates
  false offers  share of near-misses that are not tasks whose best candidate
                passes the strong cut-off: the card's "Similar" hint (the app
                never shows the hint for a task)

and whether each meets its target from the file. Matching runs by meaning
only: the words half of the check does not depend on the model, so recall
here is a lower bound. With --chat-model it also runs layer 2 for each case
that has candidates (the candidate round's tool result, then a call forced
to propose_thought) and reports how often the model picks right: add_to the
filed thought for a pair, new for a near-miss. That rate has no target.

It exits 0 when every target is met, 1 when one is missed, and 2 when it
cannot run (no key, an unknown provider, a bad test set, a provider error).
"""

import argparse
import asyncio
import json
import math
import os
import random
import sys
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import httpx2
import openai
import yaml
from openai import AsyncOpenAI

from app.chat.config import ChatConfig, load_chat_config
from app.chat.prompt import (
    PROPOSE_TOOL,
    SYSTEM_PROMPT,
    forced_tool,
    propose_tool_schema,
)
from app.chat.refs import Refs, normal_ref
from app.chat.similar import (
    MAX_CANDIDATES,
    TASK,
    Candidate,
    Check,
    PartCheck,
    candidates_note,
    check_query,
)
from app.chat.tools import ProposalPart, ToolArgumentError, parse_proposal
from app.config import Settings
from app.models import SearchIndex
from app.provider_config import load_providers_config
from app.thoughts.baseline import MAX_PAIRS, Cutoffs, cutoffs, pair_count
from app.thoughts.categories import FIXED_CATEGORIES

TEST_SET = Path(__file__).resolve().parents[2] / "evals" / "similar_thoughts.yaml"
# Texts per embeddings request.
BATCH = 64
# The random pairs of a large corpus are drawn with this seed, so a run is
# repeatable.
SEED = 0
# A thought with no `filed` date, as the chat model reads it.
DEFAULT_FILED = date(2025, 1, 15)
PAIR = "pair"
NEAR_MISS = "near_miss"


class TestSetError(ValueError):
    """The test set file is missing or malformed."""


class JobError(RuntimeError):
    """The job cannot run: a provider refused or failed."""


# ---------------------------------------------------------------- test set


@dataclass(frozen=True)
class Item:
    """One thought of the test set."""

    key: str
    title: str
    summary: str
    tags: list[str]
    category: str | None
    filed: date = DEFAULT_FILED

    @property
    def text(self) -> str:
        """What is embedded: the head entry's text, which is also the check's query."""
        return check_query(self.title, self.tags, self.summary)


@dataclass(frozen=True)
class Case:
    id: str
    kind: str  # PAIR or NEAR_MISS
    filed: Item
    later: Item


@dataclass(frozen=True)
class Targets:
    recall: float
    false_offers: float


@dataclass(frozen=True)
class TestSet:
    targets: Targets
    cases: list[Case]
    background: list[Item]

    @property
    def corpus(self) -> list[Item]:
        """Every thought in the index: each case's filed thought, then the background."""
        return [case.filed for case in self.cases] + self.background

    def texts(self) -> dict[str, str]:
        """Every text to embed, by item key: the corpus, then each later thought."""
        items = self.corpus + [case.later for case in self.cases]
        return {item.key: item.text for item in items}


def _text(raw: dict, name: str, where: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise TestSetError(f"{where}.{name} must be a non-empty string")
    return value.strip()


def _item(raw: Any, key: str, where: str) -> Item:
    if not isinstance(raw, dict):
        raise TestSetError(f"{where} must be a mapping")
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise TestSetError(f"{where}.tags must be a list of strings")
    category = raw.get("category")
    if category is not None and category not in FIXED_CATEGORIES:
        raise TestSetError(f"{where}.category must be one of {', '.join(FIXED_CATEGORIES)}")
    filed = raw.get("filed", DEFAULT_FILED)
    if isinstance(filed, str):
        try:
            filed = date.fromisoformat(filed)
        except ValueError as exc:
            raise TestSetError(f"{where}.filed must be a date") from exc
    if not isinstance(filed, date):
        raise TestSetError(f"{where}.filed must be a date")
    return Item(
        key=key,
        title=_text(raw, "title", where),
        summary=_text(raw, "summary", where),
        tags=list(tags),
        category=category,
        filed=filed,
    )


def _share(raw: dict, name: str) -> float:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int | float) or not 0 <= value <= 1:
        raise TestSetError(f"targets.{name} must be a number from 0 to 1")
    return float(value)


def load_test_set(path: Path = TEST_SET) -> TestSet:
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise TestSetError(f"Cannot read the test set {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise TestSetError("The test set must be a mapping")
    targets = raw.get("targets")
    if not isinstance(targets, dict):
        raise TestSetError("targets must be a mapping with recall and false_offers")
    goals = Targets(recall=_share(targets, "recall"), false_offers=_share(targets, "false_offers"))
    cases: list[Case] = []
    seen: set[str] = set()
    for section, kind in (("pairs", PAIR), ("near_misses", NEAR_MISS)):
        entries = raw.get(section) or []
        if not isinstance(entries, list):
            raise TestSetError(f"{section} must be a list")
        for index, entry in enumerate(entries):
            where = f"{section}[{index}]"
            if not isinstance(entry, dict):
                raise TestSetError(f"{where} must be a mapping")
            case_id = entry.get("id")
            if not isinstance(case_id, str) or not case_id.strip():
                raise TestSetError(f"{where}.id must be a non-empty string")
            if case_id in seen:
                raise TestSetError(f"{where}.id {case_id} is used twice")
            seen.add(case_id)
            cases.append(
                Case(
                    id=case_id,
                    kind=kind,
                    filed=_item(entry.get("filed"), f"{case_id}:filed", f"{where}.filed"),
                    later=_item(entry.get("later"), f"{case_id}:later", f"{where}.later"),
                )
            )
    background_raw = raw.get("background") or []
    if not isinstance(background_raw, list):
        raise TestSetError("background must be a list")
    background = [
        _item(entry, f"background:{index + 1}", f"background[{index}]")
        for index, entry in enumerate(background_raw)
    ]
    if not any(case.kind == PAIR for case in cases):
        raise TestSetError("The test set needs at least one pair")
    return TestSet(
        targets=goals,
        cases=cases,
        background=background,
    )


# ---------------------------------------------------------------- similarity


def normalized(vector: Sequence[float]) -> list[float]:
    length = math.sqrt(sum(value * value for value in vector))
    return [value / length for value in vector] if length else list(vector)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors already normalized."""
    return math.fsum(x * y for x, y in zip(a, b))


def percentile_cont(values: Sequence[float], fraction: float) -> float:
    """The percentile as Postgres's percentile_cont computes it: linear
    interpolation between the two closest ranks."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def baseline_pairs(heads: int, rng: random.Random) -> list[tuple[int, int]]:
    """The pairs of heads the baseline compares, as the app's SQL does: every
    pair while there are at most MAX_PAIRS, else MAX_PAIRS random pairs of
    two different heads (a pair can repeat)."""
    if pair_count(heads) <= MAX_PAIRS:
        return [(i, j) for i in range(heads) for j in range(i + 1, heads)]
    pairs = []
    for _ in range(MAX_PAIRS):
        i = rng.randrange(heads)
        j = rng.randrange(heads - 1)
        pairs.append((i, j + 1 if j >= i else j))
    return pairs


@dataclass(frozen=True)
class Baseline:
    heads: int
    pairs: int
    p95: float | None
    p99: float | None


def measure_baseline(
    heads: Sequence[Sequence[float]], min_thoughts: int, rng: random.Random | None = None
) -> Baseline:
    """The 95th and 99th percentile of similarity between head pairs, or none
    below `min_thoughts` heads, as app.thoughts.baseline measures it."""
    if len(heads) < min_thoughts or len(heads) < 2:
        return Baseline(heads=len(heads), pairs=0, p95=None, p99=None)
    pairs = baseline_pairs(len(heads), rng or random.Random(SEED))
    similarities = [cosine(heads[i], heads[j]) for i, j in pairs]
    return Baseline(
        heads=len(heads),
        pairs=len(pairs),
        p95=percentile_cont(similarities, 0.95),
        p99=percentile_cont(similarities, 0.99),
    )


# ---------------------------------------------------------------- evaluation


@dataclass(frozen=True)
class Found:
    item: Item
    similarity: float


@dataclass
class CaseResult:
    case: Case
    # The candidates for the later thought, best first, at most three.
    candidates: list[Found]
    # The best candidate past the strong cut-off, None for a task.
    strong: Found | None
    # The filed thought's similarity to the later one, and its rank among all.
    filed_similarity: float
    filed_rank: int
    # Layer 2, with a chat model: whether it chose right, and what it did.
    model_right: bool | None = None
    model_answer: str | None = None

    @property
    def found(self) -> bool:
        return any(found.item.key == self.case.filed.key for found in self.candidates)

    @property
    def counts_for_offers(self) -> bool:
        """A near-miss the app could show the hint for: not a task."""
        return self.case.kind == NEAR_MISS and self.case.later.category != TASK


@dataclass
class Evaluation:
    provider: str
    model: str
    dimensions: int | None
    baseline: Baseline
    search_cutoff: float
    limits: Cutoffs
    targets: Targets
    results: list[CaseResult]
    chat: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def pairs(self) -> list[CaseResult]:
        return [result for result in self.results if result.case.kind == PAIR]

    @property
    def offer_cases(self) -> list[CaseResult]:
        return [result for result in self.results if result.counts_for_offers]

    @property
    def recall(self) -> float:
        pairs = self.pairs
        return sum(result.found for result in pairs) / len(pairs)

    @property
    def false_offers(self) -> float:
        cases = self.offer_cases
        if not cases:
            return 0.0
        return sum(result.strong is not None for result in cases) / len(cases)

    @property
    def recall_met(self) -> bool:
        return self.recall >= self.targets.recall

    @property
    def false_offers_met(self) -> bool:
        return self.false_offers <= self.targets.false_offers

    @property
    def passed(self) -> bool:
        return self.recall_met and self.false_offers_met

    @property
    def model_cases(self) -> list[CaseResult]:
        return [result for result in self.results if result.model_right is not None]

    @property
    def model_rate(self) -> float | None:
        cases = self.model_cases
        if not cases:
            return None
        return sum(bool(result.model_right) for result in cases) / len(cases)


def evaluate(
    test_set: TestSet,
    vectors: dict[str, Sequence[float]],
    *,
    provider: str,
    model: str,
    config: ChatConfig,
    dimensions: int | None = None,
    rng: random.Random | None = None,
) -> Evaluation:
    """Layer 1 and layer 3 for every case, from the vectors of every item key."""
    corpus = test_set.corpus
    unit = {key: normalized(vector) for key, vector in vectors.items()}
    heads = [unit[item.key] for item in corpus]
    baseline = measure_baseline(heads, config.filing.similar.min_thoughts, rng)
    index = SearchIndex(
        embedding_provider=provider,
        embedding_model=model,
        similarity_p95=baseline.p95,
        similarity_p99=baseline.p99,
        baseline_thoughts=baseline.heads,
    )
    limits = cutoffs(index, config)
    results = []
    for case in test_set.cases:
        query = unit[case.later.key]
        scored = sorted(
            (Found(item, cosine(query, head)) for item, head in zip(corpus, heads)),
            key=lambda found: found.similarity,
            reverse=True,
        )
        candidates = [found for found in scored if found.similarity >= limits.candidate]
        candidates = candidates[:MAX_CANDIDATES]
        best = candidates[0] if candidates else None
        strong = (
            best
            if best is not None
            and best.similarity >= limits.strong
            and case.later.category != TASK
            else None
        )
        filed_rank = next(
            rank for rank, found in enumerate(scored, start=1) if found.item.key == case.filed.key
        )
        results.append(
            CaseResult(
                case=case,
                candidates=candidates,
                strong=strong,
                filed_similarity=scored[filed_rank - 1].similarity,
                filed_rank=filed_rank,
            )
        )
    return Evaluation(
        provider=provider,
        model=model,
        dimensions=dimensions,
        baseline=baseline,
        search_cutoff=config.search.min_similarity_for(model),
        limits=limits,
        targets=test_set.targets,
        results=results,
    )


# ---------------------------------------------------------------- providers


def provider_key(provider_id: str) -> str:
    return f"{provider_id.upper().replace('-', '_')}_API_KEY"


def provider_client(
    provider_id: str, key: str, http_client: httpx2.AsyncClient | None
) -> AsyncOpenAI:
    provider = load_providers_config().get(provider_id)
    if provider is None:
        raise JobError(f"Unknown provider '{provider_id}'.")
    return AsyncOpenAI(
        base_url=provider.base_url,
        api_key=key,
        timeout=60.0,
        max_retries=3,
        http_client=http_client,
    )


async def embed_all(
    client: AsyncOpenAI, model: str, texts: dict[str, str], dimensions: int | None
) -> dict[str, list[float]]:
    keys, values = list(texts), list(texts.values())
    extra = {"dimensions": dimensions} if dimensions else {}
    vectors: list[list[float]] = []
    for start in range(0, len(values), BATCH):
        try:
            response = await client.embeddings.create(
                model=model, input=values[start : start + BATCH], encoding_format="float", **extra
            )
        except openai.OpenAIError as exc:
            raise JobError(f"The embedding provider failed: {exc}") from exc
        rows = sorted(response.data, key=lambda row: row.index)
        vectors.extend(list(row.embedding) for row in rows)
    if len(vectors) != len(keys):
        raise JobError(f"The provider returned {len(vectors)} vectors for {len(keys)} texts.")
    if len({len(vector) for vector in vectors}) != 1:
        raise JobError("The provider returned vectors of different lengths.")
    return dict(zip(keys, vectors))


# ---------------------------------------------------------------- layer 2


@dataclass(frozen=True)
class EvalThought:
    """A corpus thought as the candidate note reads a filed thought."""

    id: uuid.UUID
    title: str
    summary: str
    tags: list[str]
    category: str | None
    created_at: datetime
    updated_at: datetime
    # The corpus has no thought dates (thought-dates); the note reads them.
    starts_on: date | None = None
    starts_at: time | None = None
    ends_on: date | None = None
    ends_at: time | None = None


def _thought(item: Item) -> EvalThought:
    filed = datetime.combine(item.filed, time(9), tzinfo=UTC)
    return EvalThought(
        id=uuid.uuid5(uuid.NAMESPACE_URL, item.key),
        title=item.title,
        summary=item.summary,
        tags=item.tags,
        category=item.category,
        created_at=filed,
        updated_at=filed,
    )


def _part(item: Item) -> ProposalPart:
    return ProposalPart(title=item.title, summary=item.summary, tags=item.tags, category=item.category)


def layer2_messages(result: CaseResult, config: ChatConfig) -> tuple[list[dict[str, Any]], Refs]:
    """The conversation the model sees in a candidate round: the user's words
    (the later thought's summary), its first propose_thought call, and the
    tool result listing the candidates by ref, as the turn builds it."""
    part = _part(result.case.later)
    refs = Refs([], {}, [])
    check = Check(
        parts=[
            PartCheck(
                candidates=[
                    Candidate(thought=_thought(found.item), similarity=found.similarity)  # type: ignore[arg-type]
                    for found in result.candidates
                ]
            )
        ]
    )
    note, _ = candidates_note([part], check, refs, config.filing.seen_summary_chars)
    arguments = {
        "thoughts": [
            {"title": part.title, "summary": part.summary, "tags": part.tags, "category": part.category}
        ]
    }
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": result.case.later.summary},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": PROPOSE_TOOL, "arguments": json.dumps(arguments)},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": note},
    ]
    return messages, refs


def judge(result: CaseResult, refs: Refs, arguments: str | None) -> tuple[bool, str]:
    """Whether the model's second call is right, and what it did: add_to the
    filed thought for a pair, a new thought for a near-miss."""
    if arguments is None:
        return False, "no propose_thought call"
    try:
        parts = parse_proposal(json.loads(arguments), list(FIXED_CATEGORIES))
    except (ValueError, ToolArgumentError) as exc:
        return False, f"bad call: {exc}"
    add_to = parts[0].add_to
    if add_to is None:
        return result.case.kind == NEAR_MISS, "new"
    target = refs.resolve(add_to)
    expected = _thought(result.case.filed).id
    answer = f"add_to {normal_ref(add_to) or add_to}"
    return result.case.kind == PAIR and target is not None and target.id == expected, answer


async def run_layer2(
    evaluation: Evaluation, client: AsyncOpenAI, model: str, config: ChatConfig
) -> None:
    """Ask the chat model for every case with candidates, as the round after
    a candidate round does (forced to call propose_thought)."""
    tools = [{"type": "function", "function": propose_tool_schema(list(FIXED_CATEGORIES), [])}]
    for result in evaluation.results:
        if not result.candidates:
            continue
        messages, refs = layer2_messages(result, config)
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tools,
                tool_choice=forced_tool(PROPOSE_TOOL),
                temperature=config.temperature.default,
                max_tokens=config.reply_max_tokens,
            )
        except openai.OpenAIError as exc:
            raise JobError(f"The chat provider failed: {exc}") from exc
        calls = (response.choices[0].message.tool_calls or []) if response.choices else []
        arguments = next(
            (call.function.arguments for call in calls if call.function.name == PROPOSE_TOOL), None
        )
        result.model_right, result.model_answer = judge(result, refs, arguments)


# ---------------------------------------------------------------- report


def _mark(met: bool) -> str:
    return "met" if met else "MISSED"


def _value(value: float | None) -> str:
    return "–" if value is None else f"{value:.3f}"


def report(evaluation: Evaluation) -> str:
    e = evaluation
    pairs, offer_cases = e.pairs, e.offer_cases
    found = sum(result.found for result in pairs)
    offered = sum(result.strong is not None for result in offer_cases)
    lines = [
        f"# Similar-thought check: {e.provider} / {e.model}",
        "",
        f"Dimensions: {e.dimensions or 'native'}. Chat model for layer 2: {e.chat or 'none'}.",
        "",
        "## Result",
        "",
        "| Measure | Value | Target | |",
        "|---|---|---|---|",
        (
            f"| Recall (filed thought among the candidates) | {e.recall:.3f} "
            f"({found}/{len(pairs)}) | ≥ {e.targets.recall:.2f} | {_mark(e.recall_met)} |"
        ),
        (
            f"| False offers (near-miss gets the hint) | {e.false_offers:.3f} "
            f"({offered}/{len(offer_cases)}) | ≤ {e.targets.false_offers:.2f} "
            f"| {_mark(e.false_offers_met)} |"
        ),
    ]
    if e.model_rate is not None:
        right = sum(bool(result.model_right) for result in e.model_cases)
        lines.append(
            f"| Model picks right (layer 2) | {e.model_rate:.3f} ({right}/{len(e.model_cases)}) "
            "| – | |"
        )
    lines += [
        "",
        "Overall: " + ("every target met." if e.passed else "a target was missed."),
        "",
        "## Baseline and cut-offs",
        "",
        f"- Corpus: {e.baseline.heads} head entries, {e.baseline.pairs} pairs compared.",
        f"- p95 {_value(e.baseline.p95)}, p99 {_value(e.baseline.p99)}.",
        f"- Search cut-off for this model (chat.yaml): {e.search_cutoff:.3f}.",
        f"- Candidate cut-off {e.limits.candidate:.3f}, strong cut-off {e.limits.strong:.3f}.",
        "- Matching by meaning only; the words half would only add candidates.",
        *[f"- {note}" for note in e.notes],
        "",
        "## Cases",
        "",
        "| Case | Kind | Filed (similarity, rank) | Candidates | Hint | Model |",
        "|---|---|---|---|---|---|",
    ]
    for result in e.results:
        case = result.case
        kind = "pair" if case.kind == PAIR else "near-miss"
        if case.later.category == TASK:
            kind += " (task)"
        ok = result.found if case.kind == PAIR else result.strong is None
        candidates = ", ".join(
            f"{found.item.title} ({found.similarity:.3f})" for found in result.candidates
        )
        hint = result.strong.item.title if result.strong else "–"
        model = "–"
        if result.model_right is not None:
            model = f"{'right' if result.model_right else 'wrong'}: {result.model_answer}"
        lines.append(
            f"| {'✓' if ok else '✗'} {case.id} {case.later.title} | {kind} "
            f"| {case.filed.title} ({result.filed_similarity:.3f}, {result.filed_rank}) "
            f"| {candidates or '–'} | {hint} | {model} |"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- command


def _dimensions(value: str) -> int | None:
    if value == "native":
        return None
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive, or 'native'")
    return number


def parser() -> argparse.ArgumentParser:
    defaults = Settings.model_fields
    result = argparse.ArgumentParser(
        prog="python -m app.evals.similar_thoughts",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    result.add_argument("--provider", default=defaults["embedding_provider"].default)
    result.add_argument("--model", default=defaults["embedding_model"].default)
    result.add_argument(
        "--dimensions",
        type=_dimensions,
        default=defaults["embedding_dimensions"].default,
        help="sent as dimensions; 'native' sends none (default: the app's setting)",
    )
    result.add_argument("--chat-provider")
    result.add_argument("--chat-model")
    result.add_argument("--test-set", type=Path, default=TEST_SET)
    result.add_argument("--report", type=Path, help="also write the Markdown report here")
    return result


async def run(
    argv: list[str] | None = None, http_client: httpx2.AsyncClient | None = None
) -> int:
    args = parser().parse_args(argv)
    if args.chat_model and not args.chat_provider:
        args.chat_provider = args.provider
    keys = {provider_key(args.provider)}
    if args.chat_model:
        keys.add(provider_key(args.chat_provider))
    missing = sorted(name for name in keys if not os.environ.get(name))
    if missing:
        print(f"Set {', '.join(missing)}.", file=sys.stderr)
        return 2
    try:
        test_set = load_test_set(args.test_set)
        config = load_chat_config()
        client = provider_client(args.provider, os.environ[provider_key(args.provider)], http_client)
        vectors = await embed_all(client, args.model, test_set.texts(), args.dimensions)
        evaluation = evaluate(
            test_set,
            vectors,
            provider=args.provider,
            model=args.model,
            config=config,
            dimensions=args.dimensions,
        )
        if args.chat_model:
            chat = provider_client(
                args.chat_provider, os.environ[provider_key(args.chat_provider)], http_client
            )
            evaluation.chat = f"{args.chat_provider} / {args.chat_model}"
            await run_layer2(evaluation, chat, args.chat_model, config)
    except (TestSetError, JobError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    text = report(evaluation)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return 0 if evaluation.passed else 1


def main(argv: list[str] | None = None, http_client: httpx2.AsyncClient | None = None) -> int:
    return asyncio.run(run(argv, http_client))


if __name__ == "__main__":
    sys.exit(main())
