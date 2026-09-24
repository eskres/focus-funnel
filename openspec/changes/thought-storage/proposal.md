> **Planning status:** Proposal only. Write the specs, design, and tasks when this change is picked up. Depends on `model-providers` and `conversation-agent`.

## Why

The chat's two tools, `search_thoughts` and `propose_thought`, need somewhere durable to keep thoughts and a way to search them by meaning. `conversation-agent` ships both tools with stubs: the search tool answers that it is not available yet. A search index breaks when its embedding model changes, and providers can remove models. Per-user embedding models are also the first planned upgrade after the MVP. So storage must be rebuildable and must track which model built each index from the start.

## What Changes

- Add a `thoughts` table in Postgres. It is the source of truth for each thought: raw text, summary, title, tags, category, and created/updated timestamps. Every thought belongs to exactly one user.
- Give each user their own ChromaDB collection, named with a version (for example `thoughts__u_<user_id>__v1`). Never use one shared collection for all users.
- Add a `vector_collections` table with one row per collection: user, collection name, embedding provider and model, vector dimension, and status (`active`, `building`, or `retired`).
- Read the embedding model for queries from the collection record, not from global config. Global config is used only when a new collection is created.
- Pick the embedding model through one resolver. In the MVP it returns the system-wide default. The later upgrade adds a per-user override layer to this resolver.
- Embed the title and summary of each thought. Store `thought_id`, tags, `created_at`, and `embedding_model` in each vector's metadata.
- Before a search runs, check that the query's embedding model matches the collection. A mismatch returns a clear error instead of wrong results.
- Offer internal operations: store a thought, update a thought, delete a thought, and search by meaning with an optional tag filter and newest-first sort.
- Replace the `search_thoughts` stub from `conversation-agent` with a real search over the user's thoughts. The stub sits behind one function, so this change swaps that function. Saving a confirmed proposal is `push-and-pull-gates`, which uses the store operation from this change.
- Add an admin-only command-line re-embed job. It builds a new collection version from Postgres, checks the vector count, switches the user to the new collection, and marks the old one retired. It runs for one user or for all users, and search keeps working during the rebuild.
- Add a "delete my data" endpoint. It deletes the user's thoughts and collections, their provider keys, their model loadout and chat settings, and their conversations, messages, and usage records.

## Capabilities

### New Capabilities
- `thought-store`: Stores thoughts per user, with Postgres as the source of truth.
- `semantic-search`: Search by meaning with a tag filter and newest-first sort, per-user isolation, and the model-mismatch check.
- `embedding-management`: Embedding model selection, collection versions, and the admin re-embed-and-swap job.
- `account-data-deletion`: Deleting all of a user's stored data on request.

### Modified Capabilities
- `conversation-agent`: The search tool returns matching thoughts instead of "not available yet".

## Impact

- **Backend:** new `thoughts` and `vector_collections` tables and migrations, a ChromaDB client wrapper, the embedding resolver, the real `search_thoughts` function, the re-embed CLI (`python -m app.reembed`), and the data deletion endpoint.
- **Configuration:** a system-wide embedding provider and model setting.
- **External services:** an embeddings API from a provider in `model-providers`, called with each user's own key for that provider. A re-embed job needs a valid stored key for each affected user.
- **Data:** the deletion endpoint covers the `conversations`, `messages`, `usage_events`, `chat_models`, and `user_settings` tables from `conversation-agent` and the `provider_keys` table from `model-providers`. They cascade from the user.
- **Out of scope:** a UI for per-user embedding model selection. That is the first post-MVP upgrade, and this change must not block it.
