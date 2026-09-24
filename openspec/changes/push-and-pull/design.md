## Context

See `proposal.md` for why. What exists today:

- `app/chat/tools.py` has `save_thought(user, proposal)`, which answers "not available yet", and `format_search_result()`, which returns the result text and the ids of the thoughts shown (`SearchToolResult.thought_ids`). `turn.py` puts those ids in the `tool` event's `end` phase. Nothing stores them.
- `propose_thought` takes one `title`, `summary`, and `tags`. `turn.py` holds it in `conversations.held_proposal` (a JSON column with the proposal and the message position) and sends a `proposal` event. `PROPOSAL_SHOWN` tells the model not to propose again in the turn. `app/chat/proposal.py` offers the held proposal before archive and `/compact`, with a forced call when none is held.
- `POST /api/conversations/{id}/proposal/confirm` takes the card's text, calls `save_thought`, and clears `held_proposal` on success. The browser sends everything; the server keeps no record of what it proposed.
- The chat rebuilds answers from stored messages in `chat.tsx`. Stored answers have no proposal card and no sources: both exist only in the live stream.
- `app/thoughts/store.py` has `store_thought()`, `get_thought()`, `update_thought()`, and `delete_thought()`. `store_thought()` commits by itself. Thoughts have `category` and `raw_text` columns, unused so far. A missing or foreign thought raises 404 `not_found`.
- The thought-storage design, decisions 5 to 7 and 13, fixes the search, the compact tool result with no ids in the text, and the three deletions. This change keeps all of them.
- `scripts/probe_prompt.py` checks prompts against a real model, with `tools`, `discussions`, `compact`, and `search` probes.

## Goals / Non-Goals

**Goals:**

- The server decides what was proposed and what the raw text is. The browser sends only the user's edits and which parts a card covers.
- A confirm stores one thought, however many times the request arrives.
- Cards and sources come back when a conversation is opened again.
- No extra model call for merging, sorting, or filtering.

**Non-Goals:**

- Editing or deleting a thought from the detail view, and a list of all thoughts. Both come in a later change.
- Filtering by category in search or in the sources list.
- Renaming a category, or changing the five fixed kinds.
- Taking the raw text from the model's own words, or quoting a part's slice of the message.

## Decisions

### 1. A `proposals` table replaces `conversations.held_proposal`

Each `propose_thought` call, and each forced proposal before archive or `/compact`, writes one row:

- `proposals`: `id` (uuid), `conversation_id` (cascade), `user_id` (cascade), `position` (the tool message's position, for ordering and for the card's place in the chat), `from_position` and `to_position` (the user messages the raw text came from), `raw_text`, `parts` (JSON list of `{title, summary, tags, category, thought_id}`; `thought_id` is null until saved), `created_at`.
- `conversations.held_proposal_id` (null, `ON DELETE SET NULL`) replaces the `held_proposal` column. The held-proposal note lists only the held proposal's parts with no `thought_id`.

The tool message for `propose_thought` stores `{"proposal_id": ...}` in a new `messages.details` JSON column, and the conversation's messages answer includes each proposal by id. So a reopened conversation shows each card in place, saved or not.

**Why a table:** the server needs a stable id to confirm against (decision 4), the raw text must come from the server (decision 3), and the saved state must survive a reload. A JSON column on the conversation holds only one proposal and loses the older cards. Rows cascade with the conversation, so "Delete content" and `/delete` remove them with no new code.

**Alternatives:** keep `held_proposal` and add a JSON list of past proposals on the conversation (rejected: a growing blob rewritten on every confirm, and no row to lock); store the proposal only in the tool message's `details` (rejected: confirming would search messages for it, and the held pointer would point into a message).

### 2. One call proposes all parts

`propose_thought` takes `thoughts`: a list of 1 to 8 items, each with `title`, `summary`, `tags`, and `category`. One call makes one proposal and one group of cards. A call in the old flat shape (`title`, `summary`, `tags` at the top) is read as one part, so a model that ignores the list still files.

The tool schema is built per turn: `category` is an `enum` of the user's categories (decision 5), and the `tags` description lists the user's known tags (decision 6). The system prompt says to split a message into parts only when it holds separate things to keep, and that the summary of a discussion includes the model's points the user agreed with.

**Alternatives:** one `propose_thought` call per part (rejected: `PROPOSAL_SHOWN` stops a second call in the turn for good reason, the held note would need to track several proposals, and merge needs a group); a separate `propose_split` tool (rejected: two tools for one job, and the model must first decide which to call).

### 3. The raw text is fixed when the proposal is made

The server computes the raw text when it writes the proposal row, never from the browser:

- **`/push`:** the turn's user message without its command.
- **Anything else:** the user messages from `from_position` to `to_position`, each without its command, joined with a blank line. `to_position` is the latest user message. `from_position` is the message after the `to_position` of the latest proposal in this conversation that has a saved part, or the conversation's first message. Compacted messages count; `summary` messages do not.
- **Too long:** keep the most recent whole messages within 20,000 characters (the thought store's limit). If the latest message alone is longer, keep its first 20,000 characters.

Every part of a proposal gets the same raw text. The merged card does too.

The raw text is a snapshot: a later `/compact` or a deleted message does not change it, and a proposal made before an earlier one is saved keeps the range it had.

**Why "since the last saved proposal":** the user saves at the end of a discussion, so a save marks its end. A proposal the user never saved does not, because its discussion may still be going on. The cost is in Risks.

**Alternatives:** since the latest proposal, saved or not (rejected: a held proposal re-offered on a change of topic would lose the discussion it summarises); the whole conversation (rejected: grows without bound and mixes topics).

### 4. Confirming a part

`POST /api/conversations/{id}/proposals/{proposal_id}/confirm` takes `parts` (the part indexes the card covers: one, or all of them after a merge), `title`, `summary`, `tags`, and `category`. The old `/proposal/confirm` route goes. In one transaction the server:

1. Loads the conversation (404 for another user's) and the proposal, locking the proposal row (`SELECT … FOR UPDATE`).
2. If every listed part already has the same `thought_id`, returns that thought: a repeated request stores nothing. If some listed parts are saved and others are not, answers 409 `proposal_part_saved`; the card only offers merge before any part is saved, so this means another tab got there first.
3. Checks the category is one of the user's or null (422 `validation_error` naming `category`).
4. Adds the thought with the proposal's raw text through `add_thought()`, sets `thought_id` on the listed parts, and clears `held_proposal_id` when this was the held proposal and no part is left unsaved.
5. Commits once.

`store_thought()` splits into `add_thought()`, which validates, embeds, and flushes, and `store_thought()`, which calls it and commits. The confirm needs the thought and the part's `thought_id` in the same commit, or a double click between them could store two thoughts. The answer is `{saved, thought_id, message}`; the card links to `?thought=<thought_id>`.

**Alternatives:** an idempotency key from the browser (rejected: the proposal row is already the key); saving on the client's text alone as today (rejected: no raw text, no dedupe).

### 5. Categories

The five fixed kinds live in code (`app/thoughts/categories.py`). A `user_categories` table (`id`, `user_id` cascade, `name`, `created_at`, unique on `(user_id, name)`) holds the ones a user adds, at most 20.

- `GET /api/settings/categories` answers `{fixed: [...], added: [...]}`. `POST` adds one (trimmed, lowercased, 1 to 30 characters; 409 `category_exists` for a repeat, fixed or added; 422 past 20). `DELETE /api/settings/categories/{name}` removes an added one; a fixed kind answers 422.
- The settings page gets a "Categories" section: the fixed kinds as plain badges, added ones with a remove button, and an input to add one.
- The card's category is a `Select` with the user's categories and "None". It loads the list once per chat page.
- A category the model names that is not the user's becomes null when the proposal is written, so the card shows "None".
- "Delete content" leaves `user_categories` alone: they are settings. Deleting the account removes them by cascade.

`thoughts.category` stays free text, so removing a category leaves old thoughts as they were.

**Alternatives:** a JSON list on `chat_settings` (rejected: no uniqueness from the database, and a read-modify-write for each add); an `is_fixed` row per user for the five kinds (rejected: five rows per user that never change).

### 6. Known tags in the tool schema

Each turn runs one query for the user's tags, most used first: `SELECT tag, count(*) FROM thoughts, unnest(tags) AS tag WHERE user_id = :u GROUP BY tag ORDER BY count(*) DESC, tag LIMIT :n`. `chat.yaml` gets `filing.known_tags` (default 40). The list goes into the `tags` description of `propose_thought`: "Reuse one of the user's tags where it fits: groceries, work, …". A user with no thoughts gets the plain description.

**Why in the tool schema:** the schema already changes per user for the category enum, and it keeps the system prompt the same for every user. 40 tags is about 100 tokens.

**Alternatives:** a system message (rejected: another note in the context for the model to weigh against the held-proposal note); every tag (rejected: unbounded tokens).

The query uses `unnest`, so it runs on Postgres only, like search; on SQLite it answers no tags, and its tests carry the `postgres` marker.

### 7. Sources in the event and on the stored message

`format_search_result()` returns `sources`: `{id, title, created_at, tags}` for each thought shown, in order, in place of `thought_ids`. The `tool` event's `end` phase carries `sources`, and `turn.py` stores the same list in the tool message's `details`. The text the model reads stays as it is: no ids.

The browser collects the sources of every search in an answer, keeps each id once in first-seen order, and shows them under the answer. On reload it rebuilds them from `details`. The title, date, and tags are a snapshot from the search; the detail view shows the thought as it is now.

The sources list is a client component under the answer: a relevance / newest-first toggle, tag chips from the sources' tags (any picked tag matches), and one link per source. Sorting and filtering run in the browser on the listed sources only.

**Alternatives:** only ids in the event, with a lookup endpoint (rejected: one more request per answer, and every reload); storing sources on the assistant message (rejected: the tool message is where the search ran, and an answer may have several).

### 8. The detail view is a side sheet

`GET /api/thoughts/{id}` answers `{id, title, summary, tags, category, raw_text, created_at, updated_at}` through `get_thought()`, so another user's thought is 404 `not_found`. The Next.js proxy already forwards `/api/*`.

The chat page reads `?thought=<id>`. When it is set, a shadcn `Sheet` opens on the right over the chat, fetches the thought, and shows its fields. Links use `router.push`, so Back closes the sheet; closing the sheet also pushes the address without the parameter. The chat stays mounted, so the scroll position and the composer's text stay. A 404 shows "This thought no longer exists." The raw text section is hidden when it is empty or the same as the summary.

**Alternatives:** a page at `/app/thoughts/[id]` (rejected by the user: leaves the chat); a modal dialog (rejected: covers the chat the user is checking against).

### 9. No invented answers

`NO_MATCH` becomes `No filed thoughts match. Say so plainly, and do not answer as if the user had filed something.` The system prompt gets one sentence to the same effect for answers built from search results. The frontend shows no sources list when an answer's searches returned none.

### 10. Probes

`scripts/probe_prompt.py` gets three probes, and `tools` and `discussions` run again for regressions:

- `split`: messages with one, two, and three things to keep. Pass: the right number of parts in 90% of runs, and no single-thing message split.
- `filing`: category and tag reuse. Pass: the expected category in 80%, and an existing tag reused where one fits in 80%.
- `nomatch`: recall questions whose search returns nothing. Pass: the answer says nothing matched and claims no filed content, in 95%.

The results go in this design, as for the earlier changes, with `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` on Nebius as the reference model.

## Risks / Trade-offs

- [A discussion the user never saved joins the next proposal's raw text] → The raw text only feeds search chunks and the detail view, so the cost is a weaker match, not a wrong summary. The detail view shows the raw text, so the user can see it. A later change can let the user trim it.
- [Each part of a split keeps the whole message, so a word from one part finds all of them] → Raw text is weight C in `search_tsv` and ranks below title and summary; the evaluation set from thought-storage gets split thoughts added to measure it.
- [Small models may put several things in one part, or ignore the list shape] → The flat shape is still accepted, the `split` probe measures it, and the user can still edit and merge.
- [A per-user tool schema changes when a new tag or category appears, which breaks a provider's prompt cache for that turn] → It changes only on a new tag or category, and the known tags are sorted by use, so the list is stable between turns.
- [Sources show the title and tags from the time of the search] → The detail view shows the current thought. Editing thoughts comes later, and that change decides whether to refresh them.
- [Dropping `held_proposal` loses held proposals in existing conversations] → Their cards already disappeared on reload. The migration writes no proposal rows for them.

## Migration Plan

1. One Alembic migration: create `proposals` and `user_categories`; add `messages.details` and `conversations.held_proposal_id`; drop `conversations.held_proposal`. Downgrade reverses it, and held proposals are not restored.
2. Backend and frontend ship together: the confirm route and the event shape change at once.
3. Rollback: downgrade the migration and deploy the previous build. Thoughts saved in the meantime stay; they are ordinary thoughts.
