## Context

See `proposal.md` for why. What exists today:

- `app/chat/tools.py` has `search_thoughts(user, query)`, which returns "not available yet", and `save_thought(user, proposal)`, which `push-and-pull` replaces. `turn.py` calls `search_thoughts` from `_run_tool` and stores the returned text as the tool message.
- `app/providers.py` has the one client builder, `client_for(session, user, provider)`, which uses only that user's key. In demo mode the key comes from the request's held keys, never the database. `map_provider_error()` turns SDK errors into the `provider_*` codes.
- `app/chat/usage.py` records every model call in `usage_events` with a `kind` (`chat`, `compact`, `proposal`, `test`) and a cost estimated from the model list's prices.
- `app/user_data.py` has `delete_user_data(session, user)` from `auth-modes`. It deletes the user row and relies on `ON DELETE CASCADE`. Demo "End demo" and demo expiry both call it. Its docstring leaves Chroma to this change.
- `docker-compose.yml` already runs `chromadb/chroma:1.5.9`, and `Settings.chroma_url` exists, but nothing talks to Chroma yet. The backend has no Chroma client dependency.
- Tests run on SQLite with pytest. This container has no Docker, so earlier changes left their Postgres and compose checks for a machine that has it.

## Goals / Non-Goals

**Goals:**

- Postgres holds every thought. Chroma can be deleted and rebuilt from it.
- The embedding model is chosen in one place and recorded with each index, so a later per-user choice changes only that place.
- Every write and every deletion path keeps Chroma in step, or leaves only entries that search ignores.

**Non-Goals:**

- Saving a confirmed proposal, a thought detail view, sources in the chat, or a category in the proposal tool. Those are `push-and-pull`. This change adds the store operation they call.
- Any HTTP endpoint for thoughts other than deleting all of a user's data. The internal operations are Python functions.
- A per-user embedding model, or a local embedding model (see the proposal's future option).
- Keyword or hybrid search.

## Decisions

### 1. Tables

One migration adds three tables. Every table references `users.id` with `ON DELETE CASCADE`, like the tables before it.

- `thoughts`: `id` (uuid), `user_id`, `title` (text), `summary` (text), `raw_text` (text, null), `category` (text, null), `created_at`, `updated_at`. Index on `(user_id, created_at)`.
- `thought_tags`: `thought_id` (cascade from `thoughts`), `user_id`, `tag` (text, normalized lowercase). Primary key `(thought_id, tag)`, index on `(user_id, tag)`. A separate table rather than a JSON column, so a tag filter is one indexed query on SQLite and Postgres alike, and `push-and-pull` can list a user's tags for reuse.
- `vector_collections`: `id`, `user_id`, `name` (unique), `version` (int), `embedding_provider`, `embedding_model`, `dimension` (int), `status` (`building`, `active`, `retired`), `created_at`, `retired_at` (null). A partial unique index on `user_id` where `status = 'active'` keeps one active index per user; SQLite and Postgres both support it.

Field limits (title 200, summary 4,000, raw text 20,000, 20 tags of 50 characters) are checked in the store operation, not by column types, so the error names the field.

**Alternative:** tags in a JSON column (rejected: filtering needs database-specific JSON operators, and tags cannot be listed cheaply).

### 2. One Chroma collection per user and version

A collection is named `thoughts__u_<user id hex>__v<version>`, for example `thoughts__u_3f2a…__v1`. It is created when the user stores their first thought, with the provider, model, and dimension of the first embedding. Chroma's own embedding function is turned off (`embedding_function=None`), since vectors always come from the provider, and the distance is cosine. The collection's Chroma metadata repeats the provider, model, and dimension from its `vector_collections` row, so the mismatch check (decision 6) can compare the two.

Each vector's id is the thought id. Its metadata holds `thought_id`, `created_at` (epoch seconds), `tags` (comma-joined, for inspection only), and `embedding_model`. The document embedded is `title + "\n\n" + summary`.

**Alternatives:** one shared collection with a `user_id` filter (rejected: one missing filter leaks thoughts across users, and a rebuild would touch everyone); a collection per user without versions (rejected: a rebuild would have to delete the index that search is using).

### 3. A small wrapper around Chroma

`app/thoughts/vector_store.py` defines a `VectorStore` protocol with the few calls this change needs: create, get, and delete a collection, upsert, delete, query with an optional id filter, and list ids. `ChromaVectorStore` implements it with the `chromadb-client` package (the HTTP-only client, no ONNX runtime), pinned to the server's minor version. `InMemoryVectorStore` implements it for tests with exact cosine search.

One contract test module runs against both: always against the in-memory store, and against a real Chroma when `CHROMA_TEST_URL` is set (the compose service). That keeps the SQLite suite fast and still proves the wrapper against the real server.

**Alternative:** raw HTTP calls to Chroma's v2 API (kept as the fallback if task 1.2 finds the client package does not work with the pinned server; the protocol hides which is used).

### 4. Embedding through the provider seam, with the user's key

The operator sets `EMBEDDING_PROVIDER` (a preset id, default `nebius`) and `EMBEDDING_MODEL` (default chosen by the probe in task 1.1). Startup refuses an unknown provider, `custom`, or an empty model, naming the setting. The model itself is not checked at startup, since that needs a key.

`embed_texts(session, user, provider_id, model, texts, *, kind, conversation_id=None)` builds the client with `client_for()`, so it uses only that user's key, and demo mode gets the held key as for chat. It calls `embeddings.create`, maps errors with `map_provider_error(..., model_id=model)`, checks that every vector has the same length, and records one usage event of kind `embed` with the reported prompt tokens and no completion tokens. The cost uses the model list's prompt price when the provider lists one, else unknown. Texts are sent in batches of at most 64.

**Alternatives:** an operator-owned key (rejected: the app is bring-your-own-key, and one key would pay for every user); a local model in the backend (deferred; see the proposal).

### 5. One resolver, used only when an index is created

`resolve_embedding_model(user, settings) -> EmbeddingChoice(provider_id, model)` returns the instance setting for every user. It is called only when a new collection is created, by the first store or by a rebuild. Every other operation reads the provider and model from the user's `vector_collections` row. The per-user upgrade adds a lookup to the resolver and nothing else.

### 6. Search

`search_thoughts(session, user, query, *, tags=None, newest_first=False, limit)`:

1. Find the user's active collection. With none, return an empty result without calling a provider.
2. With tags, select the ids of the user's thoughts carrying any of them from `thought_tags`. With none, return an empty result.
3. Embed the query with the collection's provider and model.
4. Check for a mismatch: the Chroma collection's metadata must name the same provider, model, and dimension as the row, and the query vector's length must equal the row's dimension. Otherwise raise `409 embedding_mismatch` ("The search index was built with another embedding model. Ask the operator to rebuild it.") and log the collection name.
5. Query Chroma for `limit` results, filtered to the tag ids when tags are set.
6. Load the matching thoughts from Postgres with `user_id = user.id`. Drop any id not found, so a leftover vector is never returned.
7. Order by distance, or by `created_at` descending when `newest_first` is set.

`limit` comes from `search_results` in `chat.yaml` (default 8).

**Alternative:** filter tags after the vector query (rejected: the top results may all lack the tag, which returns too few).

### 7. Writes: Postgres first, then Chroma, then commit

- **Store:** validate, embed, insert the thought and its tags and flush, upsert the vector into every non-retired collection of the user (the active one and a building one, each embedded with its own model), then commit. If no collection exists, create version 1 from the resolver first. A provider error or a Chroma failure rolls back, so nothing is stored. A Chroma failure maps to `503 service_unavailable`.
- **Update:** as store. Only a changed title or summary embeds again and upserts; tag, category, or raw text changes only touch Postgres (and the vector's `tags` metadata through a metadata-only update).
- **Delete:** delete the row and commit, then delete the vector from every non-retired collection. A Chroma failure there is logged and not raised: the leftover vector is ignored by step 6 of search and disappears at the next rebuild.

If the commit fails after a Chroma upsert, the vector has no row and is ignored the same way. This order means Postgres is never missing a thought that Chroma has promised, and Chroma is at worst ahead with entries search drops.

**Alternative:** a transactional outbox that indexes in the background (rejected for now: it adds a worker, and a user filing one thought at a time can wait for one embedding call).

### 8. The search tool

`app/chat/tools.search_thoughts(user, query)` becomes `search_tool_result(session, user, query, conversation_id, http_client)`. It calls the search in decision 6 and formats the result for the model as a short list, one thought per entry: its date, title, tags, and summary. No match gives "No filed thoughts match this search." An `ApiError` gives its message in plain words and a line telling the model to pass it on, so the turn goes on as the spec requires; it is not re-raised. `turn.py` passes its session, conversation id, and http client at the one call site. The tool's parameters stay `query` only; `push-and-pull` decides whether the model gets tag and order options.

### 9. The rebuild job

`python -m app.reembed (--user <id> | --all) [--restart]` runs against the same database and Chroma as the server, not through the API.

For each user, skipping demo users (issuer `demo`) and users with no thoughts:

1. Refuse if the user already has a `building` collection, unless `--restart`, which drops it first. This keeps two jobs from racing.
2. Create a `building` row with version `max + 1` and the resolver's choice, and its Chroma collection.
3. Page through the user's thoughts in batches, embed them with that user's key, and upsert. From here on, store, update, and delete also write to this collection (decision 7).
4. Compare the id sets of Postgres and the new collection. Upsert any missing and delete any extra, then compare again. If they still differ, drop the new collection, mark it `retired`, and report the user.
5. In one transaction, mark the old active row `retired` and the new row `active`. Then delete the old Chroma collection. The retired row stays as a record.

A provider error for a user (missing, refused, or rate-limited key) drops that user's building collection, reports the user and the error code, and moves on. The job prints one line per user and exits non-zero if any user failed. Usage events are recorded against each user with kind `embed`.

**Alternative:** switch by renaming Chroma collections (rejected: Chroma has no atomic rename-and-swap, and the row flip is one Postgres transaction).

### 10. Deleting a user's data

`delete_user_data(session, user)` first lists the user's `vector_collections` names and deletes each Chroma collection; one that is already gone counts as deleted. If Chroma cannot be reached, it raises `503 service_unavailable` before touching Postgres, so the user can retry and nothing is half-deleted. Then it deletes the user row, which cascades to everything else, including the new tables.

- `DELETE /api/me` calls it and answers 204. In demo mode it answers 404; "End demo" is the demo path.
- The demo cleanup loop catches the 503 per user, logs it, and tries again on its next run. An expired demo user is already refused, so waiting is safe.
- Settings gets a "Delete my data" section with a dialog listing what will be deleted. Confirming calls the endpoint through the proxy and then goes to `/auth/logout`. It is hidden when `/api/me` reports demo mode.

## Risks / Trade-offs

- [A user with no key for the embedding provider cannot search or, later, save] → The tool result and the error name the provider and point to settings. The operator picks a provider most users will have. The local model option is recorded for later.
- [The provider retires the embedding model] → Existing indexes fail with `model_unavailable` on their next query. The operator sets a new model and runs the rebuild; `docs/` explains this.
- [Dual writes during a rebuild double the embedding calls for that user] → Only while a rebuild runs, and only for that user.
- [Chroma client and server versions drift] → The client is pinned to the server's minor version in `pyproject.toml`, and the contract test runs against the compose server.
- [A tag filter with thousands of ids makes a large Chroma `$in` query] → Personal thought counts are small. If it shows up, filter after a larger vector query instead.
- [Orphan vectors after a failed Chroma delete] → Search drops them (decision 6) and a rebuild removes them. They hold only a title and summary of a thought already deleted from Postgres; the user's data deletion drops the whole collection.
- [Stale `building` row after a crashed job] → The next run refuses and says to use `--restart`.

## Migration Plan

1. The Alembic migration adds the three tables. It runs at startup like the others, and `downgrade -1` drops them.
2. Chroma starts empty. No existing data needs moving: no thought has been stored before this change.
3. Rollback: downgrade the migration and, if any collections were created, delete `.data/chroma` (it holds nothing else).
