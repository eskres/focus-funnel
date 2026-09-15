> **Planning status:** Proposal only. Write the specs, design, and tasks when this change is picked up. Depends on `platform-foundation`.

## Why

The /push, /pull, and /explore gates need somewhere durable to keep thoughts and a way to search them by meaning. A search index breaks when its embedding model changes, and Nebius can remove models. Per-user embedding models are also the first planned upgrade after the MVP. So storage must be rebuildable and must track which model built each index from the start.

## What Changes

- Add a `thoughts` table in Postgres. It is the source of truth for each thought: raw text, summary, title, tags, category, and created/updated timestamps. Every thought belongs to exactly one user.
- Give each user their own ChromaDB collection, named with a version (for example `thoughts__u_<user_id>__v1`). Never use one shared collection for all users.
- Add a `vector_collections` table with one row per collection: user, collection name, embedding model, vector dimension, and status (`active`, `building`, or `retired`).
- Read the embedding model for queries from the collection record, not from global config. Global config is used only when a new collection is created.
- Pick the embedding model through one resolver. In the MVP it returns the system-wide default. The later upgrade adds a per-user override layer to this resolver.
- Embed the title and summary of each thought. Store `thought_id`, tags, `created_at`, and `embedding_model` in each vector's metadata.
- Before a search runs, check that the query's embedding model matches the collection. A mismatch returns a clear error instead of wrong results.
- Offer internal operations for the gates: store a thought, update a thought, delete a thought, and search by meaning with an optional tag filter and newest-first sort.
- Add an admin-only command-line re-embed job. It builds a new collection version from Postgres, checks the vector count, switches the user to the new collection, and marks the old one retired. It runs for one user or for all users, and search keeps working during the rebuild.
- Add a "delete my data" endpoint. It deletes the user's thoughts, collections, stored API key, and gate overrides.

## Capabilities

### New Capabilities
- `thought-store`: Stores thoughts per user, with Postgres as the source of truth.
- `semantic-search`: Search by meaning with a tag filter and newest-first sort, per-user isolation, and the model-mismatch check.
- `embedding-management`: Embedding model selection, collection versions, and the admin re-embed-and-swap job.
- `account-data-deletion`: Deleting all of a user's stored data on request.

### Modified Capabilities
- None expected.

## Impact

- **Backend:** new `thoughts` and `vector_collections` tables and migrations, a ChromaDB client wrapper, the embedding resolver, the re-embed CLI (`python -m app.reembed`), and the data deletion endpoint.
- **Configuration:** a system-wide embedding model setting.
- **External services:** the Nebius embeddings API, called with each user's own key. A re-embed job needs a valid stored key for each affected user.
- **Out of scope:** a UI for per-user embedding model selection. That is the first post-MVP upgrade, and this change must not block it.
