"""Evaluate thought search on the evaluation set (thought-storage task 6.4).

Embeds tests/fixtures/search_eval/ with one embedding model, stores it in a
scratch Postgres database, and runs every query three ways: by meaning only,
by words only, and hybrid (what the app does). It reports, for each:

  recall@5    share of the expected thoughts found in the top 5
  MRR         mean reciprocal rank of the first expected thought
  empty       share of the "nothing" queries that correctly return nothing
  noise       mean number of results that were not expected, per query with
              expected thoughts (each one costs tokens)
  chars       median size of the search tool's result, in characters

and a sweep of min_similarity for hybrid search, to choose the threshold.

Run from backend/ against a Postgres with pgvector. The script creates a
scratch database next to the one in the URL and drops it afterwards. The key
comes from <PROVIDER>_API_KEY, for example NEBIUS_API_KEY:

  uv run python -m scripts.search_eval \\
      --database-url postgresql+asyncpg://focus_funnel:focus_funnel@localhost:55432/focus_funnel \\
      --provider nebius --model Qwen/Qwen3-Embedding-8B [--dimensions 1024] \\
      [--report eval.md] [--write-fixture]

--write-fixture stores the model's vectors and the hybrid scores in
tests/fixtures/search_eval/vectors.json, which the regression test
(tests/test_search_quality.py) runs offline. --stand-in uses the tests'
stand-in embedder instead of a provider, needs no key, and only checks that
the script works.
"""

import argparse
import asyncio
import base64
import json
import os
import statistics
import sys
import uuid
from array import array
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.chat.config import SearchConfig, load_chat_config
from app.chat.tools import format_search_result
from app.db import create_engine
from app.models import Base, SearchIndex, Thought, ThoughtEmbedding, User
from app.provider_config import load_providers_config
from app.thoughts.chunking import pieces
from app.thoughts.search import SearchResult, rank
from app.thoughts.store import clean_tags, search_vector
from tests.search_eval import EVAL_DIR, load_eval_set

FIXTURE = EVAL_DIR / "vectors.json"
TOP = 5
MODES = ("meaning", "words", "hybrid")
BATCH = 64


# ---------------------------------------------------------------- vectors


@dataclass
class EvalVectors:
    provider: str
    model: str
    dimensions: int | None
    # "t01:0" -> vector, for each thought piece; "q01" -> vector, for each query.
    entries: dict[str, list[float]]
    queries: dict[str, list[float]]
    baseline: dict[str, float] = field(default_factory=dict)
    note: str = ""

    @property
    def dimension(self) -> int:
        return len(next(iter(self.entries.values())))


def _pack(vector: list[float]) -> str:
    return base64.b64encode(array("f", vector).tobytes()).decode()


def _unpack(packed: str) -> list[float]:
    values = array("f")
    values.frombytes(base64.b64decode(packed))
    return list(values)


def write_fixture(vectors: EvalVectors, path: Path = FIXTURE) -> None:
    data = {
        "provider": vectors.provider,
        "model": vectors.model,
        "dimensions": vectors.dimensions,
        "note": vectors.note,
        "baseline": vectors.baseline,
        "entries": {key: _pack(value) for key, value in vectors.entries.items()},
        "queries": {key: _pack(value) for key, value in vectors.queries.items()},
    }
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")


def read_fixture(path: Path = FIXTURE) -> EvalVectors:
    data = json.loads(path.read_text())
    return EvalVectors(
        provider=data["provider"],
        model=data["model"],
        dimensions=data["dimensions"],
        note=data.get("note", ""),
        baseline=data["baseline"],
        entries={key: _unpack(value) for key, value in data["entries"].items()},
        queries={key: _unpack(value) for key, value in data["queries"].items()},
    )


def texts_to_embed() -> tuple[dict[str, str], dict[str, str]]:
    """Every piece of every thought, keyed "t01:0", and every query, keyed "q01"."""
    thoughts, queries = load_eval_set()
    entries = {}
    for thought in thoughts:
        for piece in pieces(
            thought["title"], clean_tags(thought["tags"]), thought["summary"], thought.get("raw_text")
        ):
            entries[f"{thought['id']}:{piece.chunk}"] = piece.text
    return entries, {query["id"]: query["query"] for query in queries}


async def embed_with_provider(
    provider_id: str, model: str, dimensions: int | None, key: str
) -> EvalVectors:
    provider = load_providers_config().get(provider_id)
    if provider is None:
        raise SystemExit(f"Unknown provider '{provider_id}'.")
    client = AsyncOpenAI(base_url=provider.base_url, api_key=key, timeout=60.0, max_retries=3)
    entries, queries = texts_to_embed()
    keys, texts = list(entries) + list(queries), list(entries.values()) + list(queries.values())
    vectors: list[list[float]] = []
    extra = {"dimensions": dimensions} if dimensions else {}
    for start in range(0, len(texts), BATCH):
        response = await client.embeddings.create(
            model=model, input=texts[start : start + BATCH], encoding_format="float", **extra
        )
        vectors.extend(row.embedding for row in sorted(response.data, key=lambda row: row.index))
    by_key = dict(zip(keys, vectors))
    return EvalVectors(
        provider=provider_id,
        model=model,
        dimensions=dimensions,
        entries={key: by_key[key] for key in entries},
        queries={key: by_key[key] for key in queries},
    )


def embed_with_stand_in() -> EvalVectors:
    from tests.thought_helpers import concept_embedder

    embed = concept_embedder()
    entries, queries = texts_to_embed()
    return EvalVectors(
        provider="stand-in",
        model="stand-in",
        dimensions=None,
        entries={key: embed(value) for key, value in entries.items()},
        queries={key: embed(value) for key, value in queries.items()},
        note="Provisional: the tests' stand-in embedder, not a real model. Replace with task 6.4.",
    )


# ---------------------------------------------------------------- corpus


async def load_corpus(session: AsyncSession, vectors: EvalVectors) -> tuple[User, SearchIndex, dict]:
    """Store the evaluation thoughts and their entries for a new user."""
    thoughts, _ = load_eval_set()
    user = User(issuer="search-eval", subject=uuid.uuid4().hex)
    session.add(user)
    await session.flush()
    index = SearchIndex(
        user_id=user.id,
        version=1,
        embedding_provider=vectors.provider,
        embedding_model=vectors.model,
        dimension=vectors.dimension,
        status="active",
    )
    session.add(index)
    await session.flush()
    ids: dict[str, uuid.UUID] = {}
    for item in thoughts:
        tags = clean_tags(item["tags"])
        thought = Thought(
            id=uuid.uuid4(),
            user_id=user.id,
            title=item["title"],
            summary=item["summary"],
            tags=tags,
            raw_text=item.get("raw_text"),
            search_tsv=search_vector(item["title"], tags, item["summary"], item.get("raw_text")),
            created_at=datetime.combine(item["created"], time(12), tzinfo=UTC),
        )
        session.add(thought)
        ids[item["id"]] = thought.id
        for piece in pieces(item["title"], tags, item["summary"], item.get("raw_text")):
            session.add(
                ThoughtEmbedding(
                    index_id=index.id,
                    thought_id=thought.id,
                    chunk=piece.chunk,
                    start_char=piece.start_char,
                    end_char=piece.end_char,
                    embedding=vectors.entries[f"{item['id']}:{piece.chunk}"],
                )
            )
    await session.commit()
    return user, index, {thought_id: name for name, thought_id in ids.items()}


# ---------------------------------------------------------------- scoring


@dataclass
class Scores:
    recall_at_5: float
    mrr: float
    empty: float
    noise: float
    chars: float
    rows: list[dict[str, Any]]

    def as_dict(self) -> dict[str, float]:
        return {
            "recall_at_5": round(self.recall_at_5, 4),
            "mrr": round(self.mrr, 4),
            "empty": round(self.empty, 4),
            "noise": round(self.noise, 4),
            "chars": self.chars,
        }


async def score(
    session: AsyncSession,
    user: User,
    index: SearchIndex,
    names: dict[uuid.UUID, str],
    vectors: EvalVectors,
    config: SearchConfig,
    mode: str,
) -> Scores:
    _, queries = load_eval_set()
    recalls, reciprocal, empties, noise, sizes, rows = [], [], [], [], [], []
    for query in queries:
        result: SearchResult = await rank(
            session,
            user,
            query["query"],
            index=None if mode == "words" else index,
            query_vector=None if mode == "words" else vectors.queries[query["id"]],
            config=config,
            tags=query.get("tags"),
            since=query.get("since"),
            use_words=mode != "meaning",
        )
        found = [names[hit.thought.id] for hit in result.hits]
        expected = query["expect"]
        if expected:
            top = found[:TOP]
            recalls.append(sum(item in top for item in expected) / len(expected))
            first = next((i for i, item in enumerate(found) if item in expected), None)
            reciprocal.append(0.0 if first is None else 1 / (first + 1))
            noise.append(sum(item not in expected for item in found))
        else:
            empties.append(1.0 if not found else 0.0)
        sizes.append(len(format_search_result(result, config, _SETTINGS).text))
        rows.append(
            {
                "id": query["id"],
                "kind": query["kind"],
                "query": query["query"],
                "expect": expected,
                "found": found,
                "similarity": [
                    None if hit.similarity is None else round(hit.similarity, 3)
                    for hit in result.hits
                ],
                "keyword_rank": [
                    None if hit.keyword_rank is None else round(hit.keyword_rank, 3)
                    for hit in result.hits
                ],
            }
        )
    return Scores(
        recall_at_5=statistics.mean(recalls),
        mrr=statistics.mean(reciprocal),
        empty=statistics.mean(empties) if empties else 1.0,
        noise=statistics.mean(noise),
        chars=statistics.median(sizes),
        rows=rows,
    )


class _EvalSettings:
    """format_search_result reads only the embedding provider, for a note the
    evaluation never shows (it never searches by words only by accident)."""

    embedding_provider = "nebius"


_SETTINGS: Any = _EvalSettings()


def eval_config(
    base: SearchConfig, min_similarity: float | None = None, min_word_share: float | None = None
) -> SearchConfig:
    config = replace(base, limit=max(base.limit, TOP))
    if min_similarity is not None:
        config = replace(config, min_similarity=min_similarity, similarity_rules=())
    if min_word_share is not None:
        config = replace(config, min_word_share=min_word_share)
    return config


# ---------------------------------------------------------------- scratch database


async def with_scratch_database(url: str, work):
    base, _, _ = url.rpartition("/")
    name = f"ff_search_eval_{os.getpid()}"
    admin = create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with admin.connect() as connection:
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(f"{base}/{name}", poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            return await work(session)
    finally:
        await engine.dispose()
        async with admin.connect() as connection:
            await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        await admin.dispose()


# ---------------------------------------------------------------- report


def report(
    vectors: EvalVectors,
    results: dict[str, Scores],
    sweep: list[tuple[float, Scores]],
    keyword_sweep: list[tuple[float, Scores]],
    config: SearchConfig,
) -> str:
    lines = [
        "# Search evaluation",
        "",
        f"Model: `{vectors.provider}` `{vectors.model}`, {vectors.dimension} dimensions"
        + (f" (requested {vectors.dimensions})" if vectors.dimensions else "")
        + ".",
        f"Thresholds from chat.yaml: min_similarity {config.min_similarity_for(vectors.model)}, "
        f"min_word_share {config.min_word_share}.",
        "",
        "| Mode | recall@5 | MRR | empty on 'nothing' | noise | median chars |",
        "|---|---|---|---|---|---|",
    ]
    for mode, scores in results.items():
        lines.append(
            f"| {mode} | {scores.recall_at_5:.3f} | {scores.mrr:.3f} | {scores.empty:.2f} | "
            f"{scores.noise:.2f} | {scores.chars:.0f} |"
        )
    lines += [
        "",
        "## min_similarity sweep (hybrid)",
        "",
        "| min_similarity | recall@5 | MRR | empty on 'nothing' | noise |",
        "|---|---|---|---|---|",
    ]
    for threshold, scores in sweep:
        lines.append(
            f"| {threshold:.2f} | {scores.recall_at_5:.3f} | {scores.mrr:.3f} | "
            f"{scores.empty:.2f} | {scores.noise:.2f} |"
        )
    lines += [
        "",
        "## min_word_share sweep (words only; the same for every model)",
        "",
        "| min_word_share | recall@5 | MRR | empty on 'nothing' | noise |",
        "|---|---|---|---|---|",
    ]
    for threshold, scores in keyword_sweep:
        lines.append(
            f"| {threshold:.2f} | {scores.recall_at_5:.3f} | {scores.mrr:.3f} | "
            f"{scores.empty:.2f} | {scores.noise:.2f} |"
        )
    lines += [
        "",
        "## Hybrid, per query",
        "",
        "| Query | Kind | Expected | Found (similarity / keyword rank) |",
        "|---|---|---|---|",
    ]
    for row in results["hybrid"].rows:
        found = ", ".join(
            f"{name} ({'–' if sim is None else sim} / {'–' if rank_ is None else rank_})"
            for name, sim, rank_ in zip(row["found"], row["similarity"], row["keyword_rank"])
        )
        missing = [item for item in row["expect"] if item not in row["found"][:TOP]]
        mark = "✓" if not missing and (row["expect"] or not row["found"]) else "✗"
        lines.append(f"| {mark} {row['id']} `{row['query']}` | {row['kind']} | {', '.join(row['expect']) or '–'} | {found or '–'} |")
    return "\n".join(lines) + "\n"


async def run(vectors: EvalVectors, database_url: str):
    base = load_chat_config().search
    config = eval_config(base)

    async def work(session):
        user, index, names = await load_corpus(session, vectors)
        results = {mode: await score(session, user, index, names, vectors, config, mode) for mode in MODES}
        sweep = []
        for step in range(0, 13):
            threshold = round(0.15 + step * 0.05, 2)
            sweep.append(
                (threshold, await score(session, user, index, names, vectors, eval_config(base, threshold), "hybrid"))
            )
        keyword_sweep = []
        for threshold in (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0):
            keyword_config = eval_config(base, min_word_share=threshold)
            keyword_sweep.append(
                (threshold, await score(session, user, index, names, vectors, keyword_config, "words"))
            )
        return results, sweep, keyword_sweep

    results, sweep, keyword_sweep = await with_scratch_database(database_url, work)
    return results, sweep, keyword_sweep, config


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--provider", default="nebius")
    parser.add_argument("--model")
    parser.add_argument("--dimensions", type=int)
    parser.add_argument("--stand-in", action="store_true", help="use the tests' stand-in embedder")
    parser.add_argument("--report", type=Path, help="write the Markdown report here")
    parser.add_argument("--write-fixture", action="store_true")
    args = parser.parse_args()

    if args.stand_in:
        vectors = embed_with_stand_in()
    else:
        if not args.model:
            parser.error("--model is required unless --stand-in is set")
        variable = f"{args.provider.upper()}_API_KEY"
        key = os.environ.get(variable)
        if not key:
            print(f"Set {variable}.", file=sys.stderr)
            return 2
        vectors = await embed_with_provider(args.provider, args.model, args.dimensions, key)

    results, sweep, keyword_sweep, config = await run(vectors, args.database_url)
    text_report = report(vectors, results, sweep, keyword_sweep, config)
    if args.report:
        args.report.write_text(text_report)
    print(text_report)
    if args.write_fixture:
        vectors.baseline = results["hybrid"].as_dict()
        write_fixture(vectors)
        print(f"Wrote {FIXTURE}.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
