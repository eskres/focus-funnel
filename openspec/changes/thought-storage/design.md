## Context

See `proposal.md` for why. What exists today:

- `app/chat/tools.py` has `search_thoughts(user, query)`, which returns "not available yet", and `save_thought(user, proposal)`, which `push-and-pull` replaces. `turn.py` calls `search_thoughts` from `_run_tool` and stores the returned text as the tool message, which the model reads on every later turn of the conversation.
- `app/providers.py` has the one client builder, `client_for(session, user, provider)`, which uses only that user's key. In demo mode the key comes from the request's held keys, never the database. `map_provider_error()` turns SDK errors into the `provider_*` codes.
- `app/chat/usage.py` records every model call in `usage_events` with a `kind` (`chat`, `compact`, `proposal`, `test`) and a cost estimated from the model list's prices.
- `app/user_data.py` has `delete_user_data(session, user)` from `auth-modes`. It deletes the user row and relies on `ON DELETE CASCADE`. Demo "End demo" and demo expiry both call it.
- `docker-compose.yml` runs `postgres:18.6` and an unused `chromadb/chroma:1.5.9`. Nothing talks to Chroma.
- Production runs on Postgres. Tests run on SQLite by default and on Postgres with `TEST_DATABASE_URL`. This container has Postgres 16 installed, and pgvector 0.8.1 was built for it from source (apt only offers 0.6.0, which has no `halfvec`), but it has no Docker.

Three goals drive the choices below: speed, accuracy, and few tokens in the chat model's context. They are why the app files thoughts instead of pointing a model at a notes folder.

## Goals / Non-Goals

**Goals:**

- One database: a thought and its search entries are written and deleted in one transaction.
- Hybrid search (meaning plus words), exact rather than approximate, in one SQL round trip.
- A search result the chat model can use in a few hundred tokens.
- Accuracy and speed measured against a fixed evaluation set and a fixed benchmark, not assumed.
- The embedding model is chosen in one place and recorded with each index, so a per-user choice later changes only that place.

**Non-Goals:**

- Saving a confirmed proposal, a thought detail view, sources in the chat, or a category in the proposal tool. Those are `push-and-pull`. This change adds the store operation they call.
- Any HTTP endpoint for thoughts other than deleting all of a user's data. The internal operations are Python functions.
- A per-user embedding model, or a local embedding model (see the proposal's future option).
- Reranking with a second model, and an approximate (HNSW) index. Both are measured against later if the evaluation or benchmark asks for them.
- Thought storage on SQLite.

## Decisions

### 1. pgvector in the existing Postgres, Chroma removed

The compose Postgres image becomes `pgvector/pgvector` for Postgres 18, pinned to a 0.8 release. The migration runs `CREATE EXTENSION IF NOT EXISTS vector`. pgvector 0.7 or later is required, for `halfvec` (decision 2); startup refuses an older one, naming the version. The Chroma service, `CHROMA_URL`, the `chroma_url` setting, and the demo overlay's Chroma `tmpfs` are removed. The backend adds the `pgvector` Python package for the SQLAlchemy type.

An operator on a managed Postgres must have the extension available; `docs/search.md` says so, and startup fails with a clear message if the extension is missing.

**Alternatives:** ChromaDB (rejected: a second store to keep in step with Postgres, hybrid search in the self-hosted server unconfirmed, and filters split across two systems); a Postgres BM25 extension such as ParadeDB `pg_search` (deferred: not in the pgvector image, and built-in full-text search is measured first).

### 2. Tables

One migration adds three tables. Each references `users.id` with `ON DELETE CASCADE`, like the tables before it.

- `thoughts`: `id` (uuid), `user_id`, `title`, `summary`, `raw_text` (null), `category` (null), `tags` (`text[]`, normalized lowercase), `search_tsv` (`tsvector`), `created_at`, `updated_at`. Indexes: `(user_id, created_at)`, GIN on `tags`, GIN on `search_tsv`.
- `search_indexes`: `id`, `user_id`, `version`, `embedding_provider`, `embedding_model`, `dimension` (int), `requested_dimensions` (int, null: the `dimensions` asked of the model, so later calls ask the same even if the setting changes), `status` (`building`, `active`, `retired`), `created_at`, `retired_at` (null). Partial unique indexes allow one `active` and one `building` row per user.
- `thought_embeddings`: `id`, `index_id` (cascade from `search_indexes`), `thought_id` (cascade from `thoughts`), `chunk` (int; 0 is the head, 1 and up are raw-text chunks), `start_char` and `end_char` (null for the head), `embedding` (`halfvec` with no fixed dimension, storage `MAIN`). Unique on `(index_id, thought_id, chunk)`, which also serves lookups by index and thought.

`search_tsv` is written by the store operation in the same statement as the row, not as a generated column, so it can combine the tags array with weights: title and tags weight A, summary B, raw text C.

The untyped column lets indexes with different models and dimensions live in one table, which the per-user upgrade needs. Exact search needs no typed column (decision 5). Half precision and `MAIN` storage came from the benchmark (decision 10): half precision halves what a search reads without changing the cosine ranking in a way that matters, and `MAIN` keeps each vector in its row instead of a TOAST table, which cut the vector scan from 75 ms to 33 ms before half precision. A vector above about 4,000 dimensions still does not fit in the row. `search_tsv` is deferred in the model, since only the database reads it.

The models use type variants (`JSON` for the array and the vector, `Text` for the tsvector) on SQLite, and the migration does the same, so the rest of the suite still creates every table on SQLite and cascades still test there. Storing and searching run only on Postgres.

**Alternatives:** a separate tags table (rejected: storage is Postgres-only now, and an array with a GIN index filters in the same query); a generated `search_tsv` column (rejected: combining the tags array needs a function Postgres may not accept in a generated column).

### 3. What gets embedded

- **Head (chunk 0):** `title`, then the tags, then `summary`. Every thought has one.
- **Raw-text chunks (1 and up):** only when `raw_text` is present and not the same as the summary. It is split into pieces of about 800 characters on paragraph, then sentence, boundaries, with about 100 characters of overlap. A 20,000-character maximum gives at most about 30 chunks.

A thought's score is its best entry's score. The chunk's character range gives the excerpt shown in a result (decision 7).

### 4. Embedding through the provider seam, with the user's key

The operator sets `EMBEDDING_PROVIDER` (a preset id, default `nebius`), `EMBEDDING_MODEL` (default from the probe in task 1.2), and optional `EMBEDDING_DIMENSIONS` (sent as `dimensions` to models that can shorten their vectors; set only if the probe shows the provider honors it and the evaluation shows no loss). Startup refuses an unknown provider, `custom`, or an empty model, naming the setting.

`embed_texts(session, user, provider_id, model, texts, *, kind, conversation_id=None)` builds the client with `client_for()`, so it uses only that user's key, and demo mode gets the held key as for chat. It calls `embeddings.create` with a 10-second timeout, maps errors with `map_provider_error(..., model_id=model)`, checks that every vector has the same length, and records one usage event of kind `embed` with the reported prompt tokens and no completion tokens. The cost uses the model list's prompt price when the provider lists one, else unknown. Texts go in batches of at most 64.

### 5. Exact hybrid search in one query

`search(session, user, query, *, tags=None, since=None, until=None, newest_first=False)`:

1. Load the user's active index. If the user has no thoughts, return an empty result with no provider call. If tags are given and none of the user's thoughts has any of them, likewise.
2. Build one embeddings call holding the query and up to `backfill_batch` texts of thoughts that lack entries in the active index (decision 6). If there is no active index yet, the call uses the resolver's choice and creates the index from the first vector. If the call fails, continue with words only and remember why.
3. Check the query vector's length against the index's `dimension`, and the index's model against the model used. A mismatch means words only, a "rebuild needed" note, and a warning log naming the index.
4. Run one SQL statement with two candidate lists and a merge:
   - **Meaning:** `SELECT thought_id, min(embedding <=> :q)` over `thought_embeddings` for the active index, joined to `thoughts` for the filters, grouped by thought, ordered by distance, limit `candidates`. There is no approximate index: the planner reads the user's rows through the `(index_id, thought_id)` index and compares each, so recall is complete.
   - **Words:** `thoughts` rows of the user matching the filters where `search_tsv @@ q`, ranked by `ts_rank_cd`, limit `candidates`. The query terms are OR-joined with the `english` configuration, so a query need not contain every word, stop words are dropped, and words match by their stem. For those candidates only, `word_share` is the share of the query's words the thought holds.
   - **Merge:** reciprocal rank fusion, `sum(1 / (rrf_k + rank))` over the lists a thought appears in. A thought passes if its similarity (`1 - distance`) is at least `min_similarity`, or its `word_share` is at least `min_word_share`. Order by the fused score, or by `created_at` descending for newest first. Limit `limit`.
5. Return the thoughts with their best chunk and whether the search used words only, and why.

The statement runs with `SET LOCAL plan_cache_mode = force_custom_plan`: asyncpg prepares it, and the generic plan Postgres switches to after five runs took twice as long in the benchmark.

The ranking step is its own function, `rank()`, which the evaluation calls with stored vectors.

Only step 2 leaves the database, and it is one call.

**Why exact:** a user's thoughts number in the hundreds or thousands. Comparing against each is fast enough (decision 10 measures it) and never misses a match that an approximate index could. An approximate per-index HNSW index is the fallback if the benchmark fails; it needs a typed column per dimension, created as a partial index per search index.

**Why `english` and OR:** the plan first used `simple`, which keeps every word as written, in any language. The evaluation's words-only results showed the cost: with no stop words, `for`, `the`, and `to` matched almost every thought, so `activities for the kids` ranked a Rust decision first and each search carried extra results into the model's context. The evaluation set is English (Norwegian was dropped on 2026-09-24), so `english` drops stop words and matches stems. Text in another language still matches word for word, without stemming. Changing the configuration later needs every `search_tsv` written again. AND-matching would drop a thought for one extra word in the query; `min_word_share` keeps OR-matching from letting in weak matches. It was set to 0.5 from the words-only sweep, which does not depend on the model: recall at 5 0.74, mean reciprocal rank 0.70, every "nothing" query empty, and 0.44 unexpected results per query, where 0.3 let a "nothing" query through and 0.6 lost recall.

**Alternatives:** meaning only (rejected: misses names, codes, and exact phrases); words only (rejected: misses paraphrases); a weighted sum of scores instead of rank fusion (rejected: cosine and `ts_rank_cd` scales differ per model and query, and rank fusion needs no calibration).

### 6. Writes and filling in missing embeddings

- **Store:** validate, then try one embeddings call for the new thought's head and chunks plus up to `backfill_batch` missing texts. Then, in one transaction, insert the thought with its `search_tsv` and, if the call worked, its entries for the active index (creating index version 1 from the resolver on a user's first vector). If a `building` index exists, embed for it too, with its own model, in a second call. A provider failure is logged and leaves the thought without entries; it is found by words at once. Only validation errors fail a store.
- **Update:** as store. A change to title, summary, tags, or raw text rewrites `search_tsv`. A change to title, summary, or raw text deletes the thought's entries and embeds again. Tags are part of the head text, so a tag change re-embeds the head only. A category change touches neither.
- **Delete:** delete the row. Entries cascade in the same transaction.
- **Filling in:** a thought "lacks entries" when the active index has no chunk-0 row for it. Store and search both take the oldest `backfill_batch` such thoughts (default 16 texts) into the call they already make, so filling in never adds a network round trip.

**Alternative:** a background worker that embeds after commit (rejected: another moving part, and piggy-backing on calls the user already waits for clears a backlog within a few requests).

### 7. Compact results for the chat model

The search tool (`app/chat/tools.py`) formats the result to use as few tokens as it can while still letting the model answer:

```
3 of your thoughts match (best first):
1. Oat milk · 2026-09-20 · #groceries #errands
   Buy oat milk on the way home.
2. Lisbon trip · 2026-08-02 · #travel
   Plan a long weekend in October.
   > "…the flat near Alfama was cheaper than the hotel…"
```

- No ids in the text: a UUID costs about 20 tokens and the model does not need it. The ids go in the `tool` event for `push-and-pull` to show as sources.
- Summaries over `summary_chars` (default 400) are cut at a word with `…`.
- An excerpt of at most `excerpt_chars` (default 240) is shown only when the match is in the raw text: the best entry by meaning was a raw-text chunk, or the raw text holds query words the title, tags, and summary lack. It is centered on the first query word it holds, else the chunk's start.
- Results are added best first until the next would pass `budget_chars` (default 2,400, about 600 tokens), and then a line says how many more matched and that tags or a start date would narrow the search.
- No match: `No filed thoughts match.` Words only: the matches, then one line saying why (for example, `Searched by words only: add your Nebius key in settings to search by meaning.`).

The tool takes `query` (described as the key words and names to look for, not a question), `tags` (optional list), and `since` (optional `YYYY-MM-DD`). Narrowing costs the model a few argument tokens and saves reading unrelated results. `turn.py` passes its session, conversation id, and http client at the one call site. So the model can work out a start date such as the first of this month, the system prompt now ends with today's date (`Today is Thursday 2026-09-24.`); this touches `conversation-agent`'s prompt, not its behavior otherwise.

`scripts/probe_prompt.py search` checks against a real model that searches use key words, a tag, and a start date when the user names them.

### 8. Search tuning in `chat.yaml`

```yaml
search:
  limit: 8
  candidates: 50
  rrf_k: 60
  min_similarity:
    default: <from the evaluation>
    models:            # similarity scales differ per model
      - match: <model id pattern>
        value: <from the evaluation>
  min_word_share: 0.5      # from the words-only sweep (decision 5)
  backfill_batch: 16
  budget_chars: 2400
  summary_chars: 400
  excerpt_chars: 240
```

Loaded and checked at startup like the rest of `chat.yaml`.

### 9. The evaluation set and probe

`backend/tests/fixtures/search_eval/` holds about 60 hand-written thoughts and about 40 queries with the thoughts each should find. They cover to-dos, ideas, decisions, names and codes, paraphrases, details only in raw text, queries that should find nothing, and date and tag filters.

`backend/scripts/search_eval.py` embeds the set with a given provider, model, and dimension (using a key from the environment), stores it in a scratch database, runs meaning-only, words-only, and hybrid search, and reports recall at 5, mean reciprocal rank, the rate of empty results for the "nothing" queries, noise (unexpected results per query, each of which costs tokens), and the median tool-result size in characters. It also sweeps `min_similarity` for hybrid search and `min_word_share` for words only. The probe runs it for the candidate models and dimensions and records the choice and the tuning in this decision and in `chat.yaml`. `--stand-in` runs it with the tests' stand-in embedder, with no key.

It also writes the chosen model's vectors to a compact fixture (`vectors.json`, float32 in base64), so a regression test runs the evaluation offline on Postgres and fails if hybrid recall at 5 or mean reciprocal rank drops more than 0.02 below the recorded baseline. Until task 6.4 runs, the fixture holds the stand-in embedder's vectors and says so.

### 10. The speed benchmark

`backend/scripts/search_bench.py` seeds a user with 5,000 thoughts (a third with raw text of three chunks, about 10,000 entries) and random vectors of the chosen dimension, then runs 100 searches with random query vectors and two content words, and times `rank()`: the statement of decision 5 and loading the matched thoughts. The vocabulary has 4,000 words drawn with a Zipf-like skew; queries leave out the 50 commonest, which stand in for stop words. The target is a 95th percentile under 50 ms on the compose stack. If it fails, the order of remedies is: fewer dimensions (if the evaluation allows), then a per-index HNSW index.

Run in this container (Postgres 16, pgvector 0.8.1, 4 cores at 2.8 GHz), the first version took 170 ms at 1024 dimensions. Four changes brought it to 49.8 ms:

| Change | Effect |
|---|---|
| Vectors kept in the row (`STORAGE MAIN`) | vector scan 75 → 33 ms |
| `halfvec` instead of `vector` | vector scan 33 → 12–16 ms |
| `word_share` only for the top candidates | words part 53 → 7 ms |
| `force_custom_plan` | statement 87 → 47 ms median |

Results after them, 95th percentile: 512 dimensions 40.8 ms, 1024 dimensions 49.8 ms, 2048 dimensions 62.3 ms, 4096 dimensions 128.9 ms. So `EMBEDDING_DIMENSIONS` should be 1024 or less for a model with larger vectors, if the evaluation shows no loss. The compose run is still to come.

### 11. One resolver, used only when an index is created

`resolve_embedding_model(user, settings) -> EmbeddingChoice(provider_id, model, dimensions)` returns the instance setting for every user. It is called only when a new index is created, by a user's first vector or by a rebuild. Every other operation reads the provider and model from the user's `search_indexes` row.

### 12. The rebuild job

`python -m app.reembed (--user <id> | --all) [--restart]` runs against the same database as the server, not through the API.

For each user, skipping demo users (issuer `demo`) and users with no thoughts:

1. Refuse if the user already has a `building` index, unless `--restart`, which deletes it first.
2. Create a `building` row with version `max + 1` and the resolver's choice.
3. Embed the user's thoughts in batches with that user's key and insert the entries, committing per batch. From here on, store and update also embed for this index (decision 6).
4. Repeat the fill until no thought lacks a chunk-0 entry in the new index.
5. In one transaction: lock the user's index rows, check again that no thought lacks entries (fill the few that do, if any), mark the old `active` row `retired` and the new one `active`, and delete the old index's entries.

A provider error for a user (missing, refused, or rate-limited key) deletes that user's building index, reports the user and the error code, and moves on. The job prints one line per user and exits non-zero if any user failed. Usage events are recorded against each user with kind `embed`.

### 13. Deleting a user's data

Everything is in Postgres and cascades from `users`, so `delete_user_data()` needs no change. The tests prove the cascade reaches the three new tables.

- `DELETE /api/me` calls it and answers 204. In demo mode it answers 404; "End demo" is the demo path.
- Settings gets a "Delete my data" section with a dialog listing what will be deleted. Confirming calls the endpoint through the proxy and then goes to `/auth/logout`. It is hidden when `/api/me` reports demo mode.

### 14. Tests on Postgres

Tests that store or search are marked `postgres`. The default `pytest` run deselects them. `pytest -m postgres` with `TEST_DATABASE_URL` pointing at a Postgres with pgvector runs them, and fails, rather than skips, when the variable is missing. The README gives both commands, and every task check that touches storage or search runs the second. In this container that is Postgres 16 with pgvector 0.8.1 built from source; the compose stack runs Postgres 18 with pgvector 0.8.1.

## Risks / Trade-offs

- [A user with no key for the embedding provider only gets search by words] → The tool result says so and names the provider. Words still find names and exact phrases. The local model option is recorded for later.
- [Exact search slows down as a user's collection grows] → The benchmark sets a 5,000-thought budget. Decision 10 lists the remedies in order, and the untyped column keeps them open.
- [OR-matched words let in weak matches] → The `english` configuration drops stop words, `min_word_share` sets the cut-off, and the evaluation's "nothing" queries and noise measure guard against it.
- [Stemming is English] → Other languages still match word for word, and meaning covers the rest. Switching the configuration needs `search_tsv` written again.
- [Vectors above about 4,000 dimensions no longer fit in the row] → They still work, stored out of line, but search slows (decision 10). `EMBEDDING_DIMENSIONS` shortens them.
- [Thresholds depend on the model] → Per-model `min_similarity` in `chat.yaml`, set from the evaluation; rank fusion needs no threshold for ordering.
- [The provider retires the embedding model] → Queries fall back to words only with a "rebuild needed" note. The operator sets a new model and runs the rebuild; `docs/search.md` explains this.
- [Search is Postgres-only, so the default test run does not cover it] → The `postgres` marker fails when its database is missing, and every relevant task check runs it.
- [A managed Postgres without pgvector, or with a version before 0.7] → Startup fails naming the extension or the version, and the docs list the requirement.
- [Embedding calls during a rebuild double for that user] → Only while it runs, and only for that user.

## Migration Plan

1. Switch the compose Postgres image to pgvector for Postgres 18. The data directory is compatible, since it is the same Postgres major version with an added extension.
2. The Alembic migration creates the extension and the three tables. It runs at startup like the others, and `downgrade -1` drops the tables; the extension stays, since other databases on the server may use it.
3. Remove the Chroma service and settings. `.data/chroma` can be deleted; it holds nothing.
4. Rollback: downgrade the migration and restore the previous compose file. No thought existed before this change.
