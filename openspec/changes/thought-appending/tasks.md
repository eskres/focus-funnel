Start after `thought-editing` is merged into `main`. `explore` is merged into `main` in #22 (`2d091e1`) and archived. See design.md, Context.

## 1. Data and store

- [ ] 1.1 Add the migration from design Migration Plan step 1: `thought_additions` (decision 9) and the three baseline columns on `search_indexes` (decision 5). Check that `alembic upgrade head` then `downgrade -1` runs cleanly on SQLite and on Postgres with pgvector, that there is a single head, and that `alembic check` is clean
- [ ] 1.2 Split `update_thought()` into `apply_update()`, which does not commit, and the committing wrapper, from design decision 7. Check that every existing `test_thought_store.py` test passes unchanged, and with pytest that `apply_update()` followed by a rollback leaves the thought and its entries as they were
- [ ] 1.3 Add the raw text rule from design decision 8 as a pure function over blocks and messages. Check with pytest: a plain append with the dated separator; no repeat when two additions cover the same messages; no change when no message is left; the first block kept and cut at 10,000; the newest block cut at its start when it alone does not fit; oldest additions left out with the one marker line; and the result never over 20,000

## 2. Refs and the seen-thoughts note

- [ ] 2.1 Compute refs from design decision 2 from the loaded messages and proposals. Check with pytest that numbering follows first appearance across filed parts, additions, `details.sources`, and `details.similar`; that deleting a thought leaves every other ref unchanged and never reuses its number; and that another user's thought id in a crafted row gets no ref
- [ ] 2.2 Add the seen-thoughts note to `build_context()` and to the offer, with refs in search tool text, capped by `filing.seen_thoughts` and `filing.seen_summary_chars` in `chat.yaml`. Check with pytest that the note lists the most recently seen thoughts first, skips deleted ones, is absent with no seen thoughts, holds no thought ids, comes before the held-proposal note, and replaces `FILED_NOTE`'s titles in the offer while `OFFER_NOTE` stays
- [ ] 2.3 Add `add_to` and `new` to the tool schema and to `parse_proposal()`, and resolve refs in `write_proposal()` into `add_to` and `based_on` from design decision 3. Check with pytest that a seen ref becomes an addition part, that an unknown, deleted, or foreign ref becomes a new part, that two parts with one ref are refused as a tool argument error, and that an addition's title from the model is ignored

## 3. The similar-thought check

- [ ] 3.1 Add a search function that takes a vector, and embed all new parts' queries in one request, from design decision 4 layer 1. Check with pytest and a counting fake embedder that three new parts make one embedding call, that results match the existing search for the same query, that age does not change the order, and that with no key the words half still returns a candidate
- [ ] 3.2 Add the baseline from design decision 5: measure p95 and p99 from up to 2,000 random head-entry pairs, on activation in `app/reembed.py` and on growth after a store, with the fallback under `filing.similar.min_thoughts` and the floor. Check with pytest on Postgres that the percentiles match a direct calculation on a seeded index, that no embedding call is made, that growth re-measures at 1.5 times, that a failure keeps the old baseline, and that a model with no `chat.yaml` rule gets working cut-offs
- [ ] 3.3 Add layers 2 and 3 to the turn and the offer, from design decision 4. Check with pytest and a scripted model: candidates cause no proposal, a tool result listing refs, and the tool event summary "Checked for similar thoughts"; the second call is shown and not checked again by layer 2; a task part gets the repeated-task line and no `similar`; a strong match on a new idea sets `similar`; a candidate round does not trip the one-proposal-per-turn refusal, and a third call does; the offer makes a second asked call only when candidates exist, and a decline offers nothing; and the round limit still ends a looping model

## 4. Confirm, additions, and undo

- [ ] 4.1 Add `mode: "add"` to confirm, from design decision 7. Check with pytest: the summary, tags, category, and raw text change and the title and `proposal_id` do not; a `thought_additions` row holds the fields before; a deleted target gives 404 with the file-as-new message; a changed target gives 409 `thought_changed` with its current fields and nothing changes; a repeated confirm answers the same thought without a second addition; the held proposal clears when every part is saved; and with the embedding provider unreachable the addition commits and word search finds the new summary
- [ ] 4.2 Add `target` and `similar` to the proposal payload and `additions` to `GET /api/thoughts/{id}`, from design decisions 3 and 9. Check with pytest that `target` holds the current fields or `deleted`, that additions list newest first with the conversation's current title, that a deleted conversation's additions are gone, and that neither endpoint's query count grows with the number of parts or additions
- [ ] 4.3 Add undo from design decision 9. Check with pytest that undo restores the fields and raw text and re-embeds; that it is refused with 409 when the thought changed after the addition or when a newer addition is not undone; that another user's thought gives 404; and that the proposal is not offered again after an undo

## 5. Measurement job

- [ ] 5.1 Add `python -m app.evals.similar_thoughts` and a first `backend/evals/similar_thoughts.yaml` from design decision 6, with about 30 pairs, 30 near-misses including repeated tasks, and 200 background thoughts. Check with pytest and a fake embedder that the rates and exit status are computed correctly, then run it with a real key on the default embedding model and record the numbers in this task. The project owner reviews the test set before this task is ticked

## 6. Frontend

- [ ] 6.1 Add `lib/word-diff.ts` from design decision 12. Check with vitest on added, removed, and moved words, and that a 4,000-character summary diffs in under 50 ms
- [ ] 6.2 Add the addition card and the "Similar" hint to `proposal-card.tsx`, and hide merge when a part is an addition. Check with vitest: "Add to" with the current title and no title field; Now and After with the marks following edits; pre-filled tags and category; Add sends `mode: "add"`; File as new turns it into a normal card; a 404 offers File as new; a 409 updates the Now column; "Added to" and "Addition undone" after reload; the hint names the match and turns the card into an addition card
- [ ] 6.3 Add the additions list and "Undo last addition" to `ThoughtSheet`, from the `thought-detail-view` spec. Check with vitest that the list shows newest first with links to `?proposal=`, that it is absent with no additions, that undo asks for confirmation and shows the restored fields, and that a 409 shows why

## 7. End to end

- [ ] 7.1 In the running app with a real key: `/push` "Buy new bike lock", discuss colours and prices, confirm the addition; archive and check the offer; in a new conversation a day later (move the clock or the rows), discuss the lock again and check the check finds it; `/push` a repeated task; undo the addition. Check every step against the specs in this change, record the prompt tokens of a turn with and without the seen-thoughts note, and save screenshots of the addition card, the hint, and the additions list under `.context/`
