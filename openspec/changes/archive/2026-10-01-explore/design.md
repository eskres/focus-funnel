## Context

See `proposal.md` for why. This change builds on `push-and-pull`, built on branch `push-and-pull-tasks` and not yet merged (checked 2026-09-25). What that change adds, and this one relies on:

- A `proposals` table: `id`, `conversation_id` (cascade), `user_id`, `position` (the tool message's position), `raw_text`, `parts` (JSON list, each with a `thought_id` once saved), `created_at`.
- `POST /api/conversations/{id}/proposals/{proposal_id}/confirm`, which saves a part through `add_thought()` in one transaction with the part's `thought_id`.
- The conversation's messages answer includes each proposal by id, and the chat rebuilds proposal cards in place from it.
- `GET /api/thoughts/{id}` and the thought detail sheet (`ThoughtSheet`), opened with `?thought=<id>` over the chat.
- `lib/thought-link.ts` changes `?thought` with `window.history.pushState` and a change event, and `useOpenThought()` reads it with `useSyncExternalStore`. It does not use `router.push`: a new conversation is still on the `/app` route (its address is set with `replaceState`), so a push to `/app/<id>…` would mount the page again and lose the scroll position and the composer's text.
- `ProposalGroup` renders a proposal's cards in the message list and also in the held-proposal dialog before archive and `/compact`. The frontend `Proposal` type carries `id`.
- `add_thought()` already takes a `conversation_id`. It is for the embedding's usage record, not a link.
- A sources list under every answer whose searches returned thoughts, in any mode. This covers the proposal's first bullet, so this change adds nothing for it.

What exists today:

- `/app/[id]` renders `<Chat key={id} conversationId={id} />`. A missing or foreign conversation shows the server's error message in the chat.
- `MessageList` scrolls to the end on every change to `messages`.
- `delete_user_content()` deletes thoughts, then search indexes, then conversations. `delete_user_data()` deletes the user, and every table cascades from it.
- `usage_events.conversation_id` already uses `ON DELETE SET NULL` for the same reason as here: the row outlives the conversation.

## Goals / Non-Goals

**Goals:**

- One nullable column links a thought to its origin, and the database clears it when the conversation goes.
- The origin shows the conversation as it is now: its current title and archived state.
- Opening an origin reuses the conversation page. No new page.

**Non-Goals:**

- Showing origins in the sources list or on anything other than the detail view.
- An origin for thoughts stored any way other than confirming a proposal. None exist yet.
- Keeping a copy of the discussion after the conversation is deleted. The thought's raw text is the kept copy.
- Restoring an archived conversation when its origin is opened.

## Decisions

### 1. `thoughts.proposal_id`, not a conversation id and a position

Add `thoughts.proposal_id` (uuid, null, foreign key to `proposals.id` with `ON DELETE SET NULL`, indexed). The confirm endpoint sets it in the same transaction that sets the part's `thought_id`. `add_thought()` takes an optional `proposal_id`, next to its existing `conversation_id` for usage.

The proposal already holds the conversation and the position. Deleting a conversation cascades to its proposals, and the cascade clears `proposal_id` on each thought. So "the thought loses only the link" needs no code.

**Alternatives:** `conversation_id` and `message_position` on `thoughts`, as the proposal first said (rejected: two columns that repeat the proposal row, and a position that means nothing without the proposal); no column, with a lookup through `proposals.parts` by `thought_id` (rejected: a search inside a JSON list on every detail view, and no index for it).

### 2. The detail answer carries the origin

`GET /api/thoughts/{id}` gains `origin`: null, or `{conversation_id, conversation_title, archived, proposal_id, proposed_at}`. It is one outer join from the thought through `proposals` to `conversations`. The join also filters on `conversations.user_id`, though a thought and its proposal always share an owner.

The title and archived state are read at request time, so a rename or an archive shows at once.

**Alternatives:** store the conversation title on the thought (rejected: goes stale on rename).

### 3. The origin address is `/app/<conversation_id>?proposal=<proposal_id>`

The sheet shows "From" with the conversation title, the proposal date, and "Archived" when it is. The link is a real link to `/app/<conversation_id>?proposal=<proposal_id>`, so it can be copied or opened in a new tab. A plain click is handled in the page, like `ThoughtLink`:

- **Same conversation:** change the address with `pushState`, as `lib/thought-link.ts` does, dropping `?thought` and setting `?proposal`. The sheet closes, and the chat stays mounted with the composer's text. This also works for a new conversation still on the `/app` route.
- **Other conversation:** `router.push` to the address. The route key changes, so `Chat` mounts fresh and loads the conversation.

In both cases Back returns to the thought. A `useProposalAnchor()` hook next to `useOpenThought()` reads `?proposal` the same way, with `useSyncExternalStore`, so a same-page change is seen.

`MessageList` gives each proposal group a `data-proposal-id` attribute; the held-proposal dialog does not, so the dialog's copy of a card is never the target. When `?proposal` names a group in the loaded messages, the chat scrolls it into view (`block: "center"`) and marks it with a ring for 2 seconds. Only then does it skip the scroll to the end, and only for that load. A new message scrolls to the end as usual. When the group is not there, the chat opens as usual.

Opening a conversation never changes its archived state, so no backend change is needed for "stays archived".

**Alternatives:** `router.push` for every click (rejected: remounts the chat in a new conversation, which `push-and-pull` already ran into); `useSearchParams` (rejected: the project reads address state with `useSyncExternalStore` after a `pushState`, and one pattern is simpler to test); an `id="proposal-<id>"` (rejected: the held-proposal dialog renders the same group, so the id would repeat); a `#proposal-<id>` hash (rejected: the card does not exist yet when the browser tries to jump); the message position in the address (rejected: the card is keyed by proposal).

### 4. Backfill from `proposals.parts`

The migration adds the column and then fills it: for each proposal row, for each part with a `thought_id`, set that thought's `proposal_id`. It runs in Python over the rows, so it works on SQLite and Postgres alike. A `thought_id` whose thought is gone is skipped. Downgrade drops the column.

**Alternatives:** no backfill (rejected: thoughts saved between the two changes would have no origin, though the data is there).

## Risks / Trade-offs

- [Depends on `push-and-pull`, built on branch `push-and-pull-tasks` and not yet merged] → The tasks start after it merges. If its `proposals` table or confirm route changes shape, re-read decisions 1 and 3 first.
- [Deleting a user cascades to proposals and to thoughts in one statement, and the `SET NULL` touches thoughts that are being deleted] → Postgres handles both actions in one delete. A test deletes an account that has linked thoughts, on Postgres.
- [A card marked for 2 seconds can be missed] → The card stays in view. The ring is a hint, not the only signal.
- [The origin address keeps `?proposal` after the user scrolls away] → A reload scrolls to the card again. This is acceptable for a link the user opened on purpose.

## Migration Plan

1. One Alembic migration with `down_revision` `3f9d1b7e5a28` (`push-and-pull`'s): add `thoughts.proposal_id` with its foreign key and index, then backfill from `proposals.parts`. Downgrade drops the column.
2. Backend and frontend can ship apart. The frontend shows no origin section when `origin` is missing.
3. Rollback: downgrade the migration and deploy the previous build. Thoughts are unchanged.
