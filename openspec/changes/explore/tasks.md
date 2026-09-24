## 1. Data

- [ ] 1.1 Add `thoughts.proposal_id` from design decision 1 in one migration after `push-and-pull`'s (`3f9d1b7e5a28`), with the backfill from design decision 4. Check that `alembic upgrade head` then `downgrade -1` runs cleanly on SQLite and on Postgres with pgvector, that there is a single Alembic head, that `alembic check` is clean, and with pytest that the backfill links each saved part's thought and skips a `thought_id` whose thought is gone
- [ ] 1.2 Check the deletions with pytest on Postgres: deleting a conversation with `/delete` keeps its thoughts with every field and a null `proposal_id`, and search still finds them by title; "Delete content" and account deletion both run cleanly for a user with linked thoughts; another user's thoughts keep their `proposal_id`

## 2. Backend

- [ ] 2.1 Give `add_thought()` an optional `proposal_id` and set it from the confirm endpoint. Check with pytest that a confirmed `/push` part, a confirmed discussion part, and a merged confirm each store the proposal's id, that two parts saved from one proposal share it, and that `store_thought()` without it stores null
- [ ] 2.2 Add `origin` to `GET /api/thoughts/{id}` from design decision 2. Check with pytest that it holds the conversation's current title after a rename, `archived` true after an archive, the proposal id and date, that it is null for a thought with no proposal and after the conversation is deleted, and that the query count for the endpoint does not grow

## 3. Frontend

- [ ] 3.1 Add the origin section to the thought detail sheet from design decision 3: "From" with the conversation title, the proposal date, "Archived" when it is, and a link to `/app/<conversation_id>?proposal=<proposal_id>` that uses `pushState` for the open conversation and `router.push` for another. Check with vitest that it shows each field, shows "Archived" only when archived, is absent when `origin` is null or missing, and that a click in the open conversation closes the sheet and keeps the composer's text, including in a new conversation on the `/app` route
- [ ] 3.2 Add `useProposalAnchor()` next to `useOpenThought()`, give each proposal group in `MessageList` a `data-proposal-id`, and make the chat scroll to and mark the group named by `?proposal` from design decision 3. Check with vitest that the named card is scrolled into view and marked, that the end scroll is skipped for that load only, that a compacted card is still found, that an unknown proposal opens the conversation as usual, that a change of `?proposal` in the same conversation scrolls again without reloading the messages, and that the held-proposal dialog's copy of a card is never the target

## 4. End to end

- [ ] 4.1 In the running app with a real key: discuss something and confirm the card, `/push` a thought, archive the first conversation, ask `/pull` about both, open each source, click its origin, press Back, copy an origin address into a new tab, then `/delete` one conversation and open its thought again. Check that every step matches the `thought-origin` spec, that the archived conversation stays archived, and save screenshots of the origin section and the marked card under `.context/`
