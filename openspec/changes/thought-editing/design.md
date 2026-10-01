## Context

See `proposal.md` for why. This change builds on the `explore` change (thought origin). That change is merged into `main` in #22 (`2d091e1`) and archived (2026-10-01). What it adds, and this change relies on:

- `thoughts.proposal_id` (nullable, `ON DELETE SET NULL` to `proposals.id`).
- `get_thought_with_origin()` in `store.py`, and `origin` on `GET /api/thoughts/{id}`: null or `{conversation_id, conversation_title, archived, proposal_id, proposed_at}`.
- An origin section ("From") in `ThoughtSheet`, and `Thought.origin` in `lib/thoughts.ts`.

What exists on `main`:

- `update_thought()` changes only the fields it is given, runs `check_fields()`, and re-indexes only what changed. A new title, summary, or raw text replaces all the thought's entries. New tags replace only the head entry (chunk 0), because the head piece holds the title and tags. A new category, or no change, makes no embedding call. The old entries are deleted before the embedding call, so search by meaning never returns the old wording. An embedding failure is returned in `StoreOutcome.error`; the thought is still committed.
- `delete_thought()` deletes the row; its entries cascade in the same transaction. Missing and foreign thoughts both raise `not_found`.
- Confirm (`POST .../proposals/{id}/confirm`) checks the category inline: `clean_name()`, empty means none, and it must be in `user_categories()`. It ignores `outcome.error` and answers "Saved.": a failed embedding never fails a save.
- The proposal card keeps the proposed title from `proposals.parts`. Confirm writes only `thought_id` into the part, so a reopened saved card shows the model's title, not the title the user saved.
- `proposals.parts[*].thought_id` is also how the chat knows a part is filed: `prompt.py` (unsaved parts) and `proposal.py` (held proposal) both test it.
- The Next.js proxy `app/api/[...path]/route.ts` is a catch-all that already exports `PATCH` and `DELETE`.
- A sources list is built from the search results stored with the answer's tool message (`details.sources`: id, title, created_at, tags).
- `DeleteDialog` (`components/chat/delete-dialog.tsx`) is the confirmation dialog for deleting a conversation.

## Goals / Non-Goals

**Goals:**

- Reuse `update_thought()`, `delete_thought()`, and `check_fields()` without changing them.
- One category check for confirm and edit.
- No migration.

**Non-Goals:**

- Editing the raw text.
- Undo after a delete.
- Protecting against two tabs editing the same thought. The last save wins.
- Changing the store's re-embedding rules. Only the `thought-store` spec wording changes (decision 8).
- Adding to a filed thought from the chat. The `thought-appending` change plans it, on top of this one.

## Decisions

### 1. `PATCH` takes only the four fields; `raw_text` is refused

`PATCH /api/thoughts/{id}` takes a body with optional `title`, `summary`, `tags`, and `category`. The model forbids other fields, so a body with `raw_text` gets 422 `validation_error` naming `raw_text`. Only fields present in the body are passed to `update_thought()` (`model_dump(exclude_unset=True)`), so a missing field is kept and `"category": null` clears the category. The answer is the thought in the same shape as `GET`, with `origin`, so the sheet replaces its state from one answer.

`DELETE /api/thoughts/{id}` calls `delete_thought()` and answers 204.

Both use `get_current_user`, so the owner check and the 404 for a foreign thought come from the store functions.

**Alternatives:** `PUT` with all fields (rejected: the sheet would have to send the raw text back, and a stale copy could overwrite it); silently ignore `raw_text` (rejected: a client that thinks it changed the raw text gets no sign that it did not).

### 2. One category check, which keeps the thought's current category

Move confirm's inline check to `check_category(session, user, value, *, keep=None)` in `categories.py`. It cleans the name, maps empty to none, and accepts a name in `user_categories()` or equal to `keep`. Confirm calls it with no `keep`. `PATCH` calls it with the thought's current category, only when `category` is in the body.

A removed category stays on the thoughts that have it (`remove_category()` says so), and the card already shows it as a choice. Without `keep`, editing only the title of such a thought would fail on a field the user did not touch.

**Alternatives:** no category check on edit (rejected: the edit could then set any text as a category, which confirm refuses); check only when the category changed (same result as `keep`, but `keep` puts the rule in one place).

### 3. When an edit re-embeds, and what a failure does

The edit follows `update_thought()` as it is:

| Change | Embedding call |
|---|---|
| Title or summary | All pieces of the thought |
| Tags only | The head piece only |
| Category only | None |
| Nothing | None, and no row update, so `updated_at` stays |

The frontend sends only the fields the user changed, and sends nothing when no field changed. So Save with no change makes no request.

An embedding failure does not fail the edit, as for confirm. The change is committed, search finds it by its words at once, and the old entries are already deleted. `missing_thoughts()` sees the missing head entry, so the user's next store or search that reaches the provider fills it in. `PATCH` answers 200 with the thought and no warning, as confirm answers "Saved.". A provider error the user must fix (no key, rejected key) already shows on the next chat turn.

**Alternatives:** re-embed on any field (rejected: a category change would cost a call for nothing, and the store already avoids it); fail the edit when the provider is down (rejected: the thought-store spec says a provider failure never loses a thought, and confirm does not fail either); show a warning in the sheet (rejected for now: confirm shows none, and the user can do nothing with it; it can be added to both later).

### 4. Saved cards show the thought's current title, or "Deleted"

The conversation's messages answer adds two fields to each `ProposalPart`: `saved_title` (the thought's current title, or null) and `deleted` (true when `thought_id` is set but the thought is gone). The endpoint collects the `thought_id`s of all parts in the conversation and reads them in one query: `select(Thought.id, Thought.title).where(Thought.id.in_(ids), Thought.user_id == user.id)`. The same fields are set on `OfferedProposal` and on the proposal event from the stream, so the card has one shape. There, a new proposal has no saved part, so both are empty.

A saved card shows `saved_title ?? title`. A deleted card shows "Deleted:" with the proposed title, and no Open link.

In an open chat, the sheet changes the card at once. After a save or delete, `lib/thoughts.ts` dispatches a `thought-changed` window event with `{id, title}` or `{id, deleted: true}`. `ProposalCard` listens while it shows a saved thought and updates its own title or deleted state. This is the same pattern as the change event in `lib/thought-link.ts`, and it needs no shared state between `ThoughtSheet` and the message list.

Deleting a thought does not touch `proposals.parts`. Its `thought_id` stays, so the part still counts as filed, and the chat does not offer the proposal again.

This also fixes a gap on `main`: a reopened saved card shows the model's title, not the title the user saved.

**Alternatives:**

- Keep the proposed title and the Open link (rejected: after an edit the card names a thought that no longer has that title, and after a delete "Saved" with a link that leads to "This thought no longer exists" is a dead end).
- Write the new title into `proposals.parts` on each edit (rejected: the proposal is the record of what was proposed; the edit route would have to find the proposal, and a delete would have to choose between clearing `thought_id`, which offers the proposal again, and leaving it).
- Clear `thought_id` on delete (rejected: `prompt.py` and `proposal.py` would treat the part as unfiled and offer it to the user again).
- Refetch the whole conversation after an edit (rejected: reloads every message and loses the scroll position for a one-line change).

### 5. A sources list stays as it was

A sources list keeps the title, tags, and date from the search the answer ran. It does not change after an edit, and a deleted thought stays in the list. Its link then opens the sheet, which says the thought no longer exists.

The list is the record of what the answer read. The answer's text was written from those titles and summaries, so a renamed source would no longer match the answer above it. The saved card is different: it reports the state of the user's thought, so it follows the thought (decision 4).

**Alternatives:** update the list through the same `thought-changed` event and on load (rejected: the list would disagree with the answer's text, and on load it would need a lookup per answer for little gain); remove deleted sources from the list (rejected: the answer would cite a thought that is no longer shown).

### 6. The origin is not touched

`update_thought()` changes only the title, summary, tags, raw text, category, and search fields. It never writes `thoughts.proposal_id`, and `PATCH` has no field for it. An edited thought keeps its origin, and the sheet shows the same "From" section after a save. A deleted thought takes its `proposal_id` with it; the proposal row and the conversation stay.

### 7. Sheet layout: edit in place, reuse the card's fields

The sheet has a view mode (as now, plus Edit and Delete buttons under the header) and an edit mode. Edit mode shows the same fields as a proposal card: `Input` for the title, `Textarea` for the summary, `Input` for comma-separated tags, and the category `select` with "None", the user's categories from `useCategories()`, and the current category if it was removed. Move `parseTags()` and the category choices into a small shared module (`components/chat/thought-fields.tsx`) that both `ProposalCard` and `ThoughtSheet` use. The origin and raw text sections stay visible and read-only in edit mode.

Save sends the changed fields. On success the sheet shows the answer and returns to view mode. On an error the sheet stays in edit mode, keeps the text, and shows the server's message (which starts with the field name, such as `title: must not be empty`) in an alert under the buttons, as the card does. Save is disabled while the title or summary is empty, as on the card. The server still checks them.

Delete opens a dialog like `DeleteDialog`. Generalise it to take the dialog title and description, so the conversation and the thought share one component. On success the sheet calls `closeThought()`.

Closing the sheet in edit mode drops the unsaved edit, like Cancel.

**Alternatives:** a separate edit dialog (rejected: the user asked for fields in place, and a second overlay over a non-modal sheet is awkward); reuse `ProposalCard` whole (rejected: it carries confirm, parts, and merge logic that the sheet does not need).

### 8. The `thought-store` spec follows the code for tag updates

The `thought-store` spec said "Updating only tags or category SHALL NOT need a new embedding". `update_thought()` embeds the head piece again when tags change, because the head piece holds the title and the tags. This change keeps the code and changes the spec: a tags-only update embeds only the first entry again, and a category-only update needs no embedding. This change is the first to let a user edit tags, so the wording is fixed here. Task 1.3 checks it.

**Alternatives:** change the code to skip the embedding on a tags-only update (rejected: search by meaning would rank the thought by its old tags until a rebuild); leave the spec for a later change (rejected: this change's cost table would contradict a spec it relies on).

## Risks / Trade-offs

- [Depends on `explore`, merged and archived] → If `origin` or `get_thought_with_origin()` changes shape before this is built, re-read decisions 1 and 6.
- [A tags-only edit deletes the head entry before the call; if the call fails, search by meaning misses the thought until the next backfill] → Search by words still finds it, and this is the store's existing behaviour for confirm too.
- [Two tabs: an edit in one tab does not reach the card in another] → The other tab shows the change when the conversation is opened again. Acceptable.
- [The messages answer does one more query per load] → One indexed lookup by primary key over the conversation's saved thought ids.

## Migration Plan

1. No migration. Backend and frontend can ship apart: a frontend without the new fields shows the proposed title as now, and a backend without `PATCH`/`DELETE` gets a 405 that the sheet shows as an error.
2. Rollback: deploy the previous build. Edits already saved stay; nothing depends on the new fields.
