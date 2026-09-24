> Depends on `model-providers` and `conversation-agent` (both archived), and on `auth-modes` for `delete_user_data()` and demo keys.

## Why

The chat's two tools, `search_thoughts` and `propose_thought`, need somewhere durable to keep thoughts and a way to find them again. `conversation-agent` ships both tools with stubs: the search tool answers that it is not available yet.

Recall is the reason this app exists instead of a notes folder: it must find the right thought quickly, and hand the chat model only what it needs, in as few tokens as possible. Search by meaning alone misses names, acronyms, and exact phrases, and search by words alone misses paraphrases. So search combines both, in the database that already holds the thoughts.

A search index breaks when its embedding model changes, and providers can remove models. Per-user embedding models are also the first planned upgrade after the MVP. So the index must be rebuildable and must record which model built it from the start.

## What Changes

- Add a `thoughts` table in Postgres, the source of truth for each thought: raw text, summary, title, tags, category, and created/updated timestamps. Every thought belongs to exactly one user.
- Keep the search index in the same Postgres database with the pgvector extension, so a thought and its index entries are written and deleted in one transaction. Drop the unused ChromaDB service.
- Search combines two rankings: by meaning (embedding similarity, computed exactly over the user's own entries, not approximately) and by words (Postgres full-text search). A thought that matches neither well enough is not returned.
- Embed each thought's title and summary, and its raw text in chunks when there is any, so a detail only in the raw text can still be found.
- Filter by tags and by date, and order by relevance or newest first. The chat model can pass tags and a start date, so it narrows the search instead of reading more results.
- Return compact results to the chat model: best first, within a fixed size budget, summaries rather than raw text, and a short matching excerpt only when the match came from the raw text.
- Add a `search_indexes` table with one row per index version: user, embedding provider and model, vector dimension, and status (`building`, `active`, or `retired`). Store and search use the model recorded with the user's index, not global config. Global config is used only when a new index is created, through one resolver that the per-user upgrade later extends.
- Never lose a thought to a provider failure: storing always succeeds for valid input. A thought whose embedding call failed is found by words at once and gets its embeddings on the user's next store or search, or from the rebuild job. When the query cannot be embedded, search answers by words alone and says so.
- Replace the `search_thoughts` stub from `conversation-agent` with the real search. Saving a confirmed proposal is `push-and-pull`, which uses the store operation from this change.
- Add an admin-only command-line rebuild job. It builds a new index version from the thoughts table, switches the user to it in one transaction, and deletes the old one. It runs for one user or for all users, and search keeps working during the rebuild.
- Add a probe that picks the default embedding model and the search tuning from a small set of test thoughts and queries, and keep that set as a regression test for search quality.
- Record every embedding call in usage, like any other model call.
- Add three deletions to settings, each with its own endpoint and confirmation: delete content (thoughts, search indexes, conversations, and messages; the user stays logged in), delete usage history (usage records only), and delete account (everything above plus provider keys, model loadout, and chat settings, then log out without a sign-out confirmation).

## Capabilities

### New Capabilities
- `thought-store`: Stores thoughts per user, with Postgres as the source of truth and the search index in the same transaction.
- `thought-search`: Hybrid search by meaning and by words, with tag and date filters, a relevance cut-off, per-user isolation, the model-mismatch check, and compact results.
- `embedding-management`: Embedding model selection, index versions, filling in missing embeddings, and the admin rebuild job.
- `account-data-deletion`: Deleting a user's content, usage history, or whole account on request.

### Modified Capabilities
- `conversation-agent`: The search tool returns matching thoughts instead of "not available yet", takes optional tags and a start date, and keeps its result small.
- `usage-tracking`: Embedding calls are recorded like chat calls.

## Impact

- **Backend:** new `thoughts`, `search_indexes`, and `thought_embeddings` tables and one migration, the embedding resolver, the hybrid search, the real `search_thoughts` tool, the rebuild CLI (`python -m app.reembed`), and the data deletion endpoint. Thought storage and search need Postgres; SQLite stays for the tests of everything else.
- **Infrastructure:** the compose Postgres image changes to one with pgvector, and the Chroma service, `CHROMA_URL`, and the `chroma_url` setting are removed.
- **Frontend:** a "Your data" section in settings with three delete buttons, each with a confirmation step.
- **Configuration:** a system-wide embedding provider, model, and optional vector size, and search tuning in `chat.yaml`.
- **External services:** an embeddings API from a provider in `model-providers`, called with each user's own key for that provider. A rebuild needs a valid stored key for each affected user.
- **Data:** the deletion endpoint covers the `conversations`, `messages`, `usage_events`, `chat_models`, and `user_settings` tables from `conversation-agent` and the `provider_keys` table from `model-providers`. They cascade from the user.
- **Out of scope:** a UI for per-user embedding model selection. That is the first post-MVP upgrade, and this change must not block it. Reranking with a second model is left for later; the evaluation set from the probe will show whether it is worth its cost.
- **Future option:** a small local embedding model run inside the backend (for example an ONNX model through fastembed). It needs no key and no per-call cost, and works in demo mode and air-gapped installs. It was considered and deferred on 2026-09-24; the resolver and the index record leave room for it as another provider.
