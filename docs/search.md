# Thought search

The chat finds a user's filed thoughts in two ways at once:

- **By meaning.** Each thought's title, tags, and summary, and its raw text in chunks, are turned into vectors by an embedding model. A search compares the question's vector with every one of the user's vectors.
- **By words.** Postgres full-text search matches the words themselves, which finds names, codes such as `ACME-4471`, and exact phrases that meaning alone misses.

The two rankings are merged, weak matches are left out, and the chat model gets a short list: titles, dates, tags, and summaries, within a fixed size budget.

Everything lives in Postgres, with the [pgvector](https://github.com/pgvector/pgvector) extension. There is no separate vector store.

## Postgres needs pgvector

The compose file runs `pgvector/pgvector:0.8.1-pg18-trixie`, which has it. It is the Debian 13 (trixie) build, like the `postgres:18` image, so a data directory from that image keeps its collation version. On your own Postgres, install pgvector 0.7 or later. The first migration runs `CREATE EXTENSION IF NOT EXISTS vector`, which needs a role allowed to create extensions; on a managed database you may have to enable it yourself first.

The backend refuses to start without the extension, or with a version before 0.7, and the message says which.

## The embedding model

One embedding model serves the whole instance. It is called with **each user's own API key** for its provider, like the chat model:

```sh
# .env
EMBEDDING_PROVIDER=nebius                 # a preset from backend/app/providers.yaml, not custom
EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B   # provisional until the embedding probe picks the default
EMBEDDING_DIMENSIONS=                     # optional, see below
```

The backend refuses to start with an unknown provider, with `custom` (its address differs per user), or with an empty model.

`EMBEDDING_DIMENSIONS` asks models that can shorten their vectors for fewer dimensions. Keep vectors at 1,024 dimensions or fewer: the search compares every vector a user has, and at 2,048 or more it no longer meets its speed target (a 95th percentile under 50 ms for 5,000 thoughts). Check with the evaluation below that the shorter vectors lose no accuracy.

### What users need

A user needs a saved key for the embedding provider to search by meaning. Without one:

- Filing still works. The thought is saved and found by its words.
- Search answers by words only, and the chat tells the user to add the key in Settings.

Once the key is there, the missing vectors are filled in during the user's next searches and saves, a few at a time, with no extra wait. Demo visitors hold their keys in the browser; the same applies to them.

Embedding calls appear in the usage section of Settings, like chat calls.

## Tuning

`backend/app/chat/chat.yaml` has a `search` section: how many results come back, the size budget of the result the chat model reads, and the two cut-offs:

- `min_similarity`: how close in meaning a thought must be. It depends on the model, so rules can set it per model.
- `min_word_share`: the share of the question's words a thought must hold to pass on words alone.

After changing the embedding model, rerun the evaluation to set `min_similarity` for it:

```sh
cd backend
NEBIUS_API_KEY=... uv run python -m scripts.search_eval \
    --database-url postgresql+asyncpg://focus_funnel:focus_funnel@localhost:55432/focus_funnel \
    --provider nebius --model Qwen/Qwen3-Embedding-8B --dimensions 1024 --report eval.md
```

It needs a Postgres with pgvector (the compose one with `docker-compose.dev.yml` exposes port 55432) and creates and drops its own scratch database there. The report compares search by meaning, by words, and both, and sweeps both cut-offs. Add `--write-fixture` to record the chosen model's vectors and scores for the regression test (`tests/test_search_quality.py`).

To check speed with a given vector size:

```sh
uv run python -m scripts.search_bench --database-url <same URL> --dimension 1024
```

## Rebuilding search indexes

Each user has their own search index, which records the model that built it. A user keeps searching with that model even after you change `EMBEDDING_MODEL`: only new users, and users whose first thought comes later, get the new one. To move everyone to the new model, rebuild:

```sh
docker compose exec backend python -m app.reembed --all
```

or one user with `--user <user id>`. For each user the job:

1. builds a new index version next to the current one, with that user's key,
2. keeps search on the current index meanwhile, while new and changed thoughts go into both,
3. switches to the new index in one transaction once every thought is in it, and deletes the old entries.

It prints one line per user. A user whose key is missing or refused keeps their current index, is reported as `failed`, and the job ends with exit status 1 after doing the others; run it again for them once they have a working key. Demo users and users with no thoughts are skipped.

If a run is interrupted, the next one stops at the user with the unfinished index and says so. Add `--restart` to start that user's rebuild again.

### When the provider retires a model

When the model that built an index stops working, searches for those users fall back to words only and the chat says the search index needs rebuilding. Set `EMBEDDING_MODEL` to a model that works, rerun the evaluation for its `min_similarity`, and rebuild with `--all`.
