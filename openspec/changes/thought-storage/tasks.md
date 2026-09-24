## 1. Probes

- [ ] 1.1 With a real key each, call `/embeddings` on Nebius, NVIDIA, and OpenRouter with two short texts. Check by recording in design decision 4 which presets serve embeddings, a recommended model for each with its dimension, whether the response reports `usage.prompt_tokens`, whether the model list shows the embedding model with a price, and the chosen `EMBEDDING_MODEL` default
- [ ] 1.2 Install `chromadb-client` pinned to the compose server's version and, against the compose Chroma, create a collection with no embedding function and cosine distance, upsert two vectors with metadata, query with a `$in` id filter, and delete the collection. Check by recording in design decision 3 the pinned version and that each call works, or switching the decision to raw HTTP if the client does not

## 2. Settings and data

- [ ] 2.1 Add `EMBEDDING_PROVIDER` and `EMBEDDING_MODEL` to `Settings` and `.env.example`, checked against the loaded presets at startup. Check with pytest that the defaults load, and that an unknown provider, `custom`, or an empty model each refuse to start naming the setting
- [ ] 2.2 Add the `Thought`, `ThoughtTag`, and `VectorCollection` models and one migration for the three tables, with the partial unique index for one active collection per user. Check that `alembic upgrade head` then `downgrade -1` runs cleanly on an empty SQLite database and on the compose Postgres, that there is a single Alembic head, and with pytest that a second active collection for one user is refused and that deleting a user cascades to all three tables
- [ ] 2.3 Add `search_results: 8` to `chat.yaml` and its loader. Check with pytest that it loads and that a value below 1 fails at startup

## 3. Vector store

- [ ] 3.1 Add the `VectorStore` protocol, `InMemoryVectorStore`, and `ChromaVectorStore` with the dependency from task 1.2, and a lifespan-created instance with a FastAPI dependency that tests override. Check with a contract test module that runs against the in-memory store always and against Chroma when `CHROMA_TEST_URL` is set: create, upsert, query ordered by distance, `$in` filter, delete a vector, list ids, delete a collection, and deleting a missing collection counts as done

## 4. Embeddings

- [ ] 4.1 Add `resolve_embedding_model()` and `embed_texts()` on top of `client_for()`, with batching, error mapping, the equal-length check, and a usage event of kind `embed`. Check with pytest and `FakeProvider` that the user's own key is used, that demo mode uses the held key, that each `provider_*` error maps as for chat, that a missing model gives `model_unavailable`, that 130 texts go in 3 calls, that one usage event per call records prompt tokens, no completion tokens, and no text, and that the resolver returns the instance setting for two different users

## 5. Thought store

- [ ] 5.1 Add store, update, get, and delete with the field checks and tag cleaning, creating version 1 of the user's collection on the first store (design decisions 1, 2, 5, 7). Check with pytest for each `thought-store` scenario: fields round-trip, the named-field refusals, tag cleaning, another user's thought treated as missing, a first store creating an active collection that records the provider, model, and dimension, a provider or Chroma failure storing nothing, an update of tags only making no embedding call, and a delete removing the vector
- [ ] 5.2 Check the write order with pytest: a Chroma upsert followed by a failed commit leaves a vector that search does not return, and a failed Chroma delete after a committed delete is logged and not raised

## 6. Search

- [ ] 6.1 Add the search in design decision 6. Check with pytest for each `semantic-search` scenario: a match by meaning (with a fake embedder that places related texts close), no thoughts giving an empty result and no provider call, the result limit, the tag filter and a tag nobody uses, newest-first order, two users never seeing each other's thoughts, `provider_key_missing` and `provider_rate_limited`, and `embedding_mismatch` for a changed dimension and for Chroma metadata naming another model
- [ ] 6.2 Replace the search tool stub with the formatted result from design decision 8 and pass the session, conversation id, and http client from `turn.py`. Check with pytest through the chat endpoint that a search returns the thought's date, title, tags, and summary to the model, that no match and no thoughts give the "No filed thoughts match" text, that a missing key gives a tool result naming the provider and the turn ends normally, and that the embedding usage event carries the conversation id

## 7. Rebuild job

- [ ] 7.1 Add `python -m app.reembed` from design decision 9. Check with pytest, calling its main function, each `embedding-management` rebuild scenario: one user rebuilt with a new model holds one entry per thought and the old collection is retired and deleted, search during the build uses the old collection, a thought stored and one deleted during the build are right in the new one, a user without a key keeps the old index and the job exits non-zero after doing the others, a count mismatch keeps the old index, demo users are skipped, and a leftover `building` collection is refused without `--restart` and dropped with it
- [ ] 7.2 Write `docs/search-index.md`: choosing the embedding provider and model, what users need (their own key for that provider), and when and how to run the rebuild, including after a model is retired. Link it from the README. Check by following it in task 9.3

## 8. Deleting a user's data

- [ ] 8.1 Extend `delete_user_data()` to delete the user's Chroma collections first and raise `service_unavailable` when Chroma cannot be reached, and make the demo cleanup loop retry such a user on its next run. Check with pytest that no row in any user-owned table and no collection remain for the user, that another user's data is unchanged, that an unreachable Chroma deletes nothing, and that "End demo" and demo expiry both drop the collections
- [ ] 8.2 Add `DELETE /api/me`, answering 404 in demo mode. Check with pytest that it answers 204 and deletes everything, that the next request with the same login starts a new empty user, and that an unreachable Chroma gives 503 `service_unavailable`
- [ ] 8.3 Add the "Delete my data" section to settings with a confirmation dialog listing what is deleted, then logging out, hidden in demo mode. Check with Vitest that cancel calls nothing, that confirm calls `DELETE /api/me` and then goes to `/auth/logout`, that an error keeps the user on the page with its message, and that the section is absent in demo mode

## 9. Full system check

- [ ] 9.1 Run the backend suite on SQLite and on the compose Postgres with `CHROMA_TEST_URL` set, and `npm run test`, `npm run lint`, and `npm run build` in `frontend/`. Check that all pass
- [ ] 9.2 With the compose stack and a real key for the embedding provider, store three thoughts with the store operation from a Python shell in the backend container (saving from the chat is `push-and-pull`), ask the chat about one of them, and check that the model answers from it, that the usage section shows the embedding calls, and that a user without that key is told to add it
- [ ] 9.3 Change `EMBEDDING_MODEL` to a second model from task 1.1, run the rebuild for all users, and check that search still works, that the new collections record the new model, and that the old Chroma collections are gone
- [ ] 9.4 Use "Delete my data" in settings and check that the user is logged out, and that Postgres and Chroma hold nothing for that user
