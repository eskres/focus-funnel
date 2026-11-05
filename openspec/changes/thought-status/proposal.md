## Why

A filed `task` can never be closed. No thought has a status today, so "call the plumber" stays a to-do forever, and a question about open tasks gets back the ones already done. A thought needs an open or done status that the user sets, from the chat or from the sheet.

## What Changes

- Every thought has a status: `open` or `done`. A new thought is `open`. Existing thoughts become `open`. The time of the last status change is kept.
- A status change touches nothing else. It does not change the thought's title, summary, tags, category, raw text, or "changed" date, and it makes no embedding call.
- `propose_thought` gains an optional `marks` list beside `thoughts`. Each mark names a thought the conversation has seen by its ref (`T1`, `T2`, … from the `thought-appending` change), to mark it done. "I called the plumber" makes the model propose marking that task done. A mark is written as one more part of the same proposal as any new thought or addition, so one answer still shows one proposal. The new-thought part schema does not change.
- When the task is not among the thoughts the conversation has seen, the model first searches the user's open thoughts for it, then proposes. A turn gets four model calls instead of three, so this fits.
- The card for a status part says "Mark done: <title>". Nothing changes until the user confirms it. A confirmed card says "Marked done: <title>" with a link. A confirm of a thought that was deleted says it no longer exists. Reopening is done in the sheet, not from the chat.
- A confirmed status part does not count as a filed thought: the discussion before it is still offered before `/compact` and archive. A status part whose thought was deleted no longer holds the proposal.
- The thought detail sheet gets a Done toggle. It saves at once, and the sheet shows when the thought was marked done. It also sets a done thought back to open.
- `PATCH /api/thoughts/{id}` takes `status`; `GET` answers `status` and `status_changed_at`.
- `search_thoughts` takes two optional filters: `status` and `category`. "What tasks are still open?" searches with `status: open` and `category: task`, and leaves out done ones. With either filter, the query is optional. Without a status filter, search still finds done thoughts, and the result marks each done one.
- The note of seen thoughts and the held-proposal note tell the model which thoughts are done.
- The Upcoming page (from `thought-dates`) leaves out done thoughts.
- `archived` is not a status in this change. A later change that adds archiving adds it as a third value of the same status. Every "open" list here asks for `open` by name, so an archived thought drops out of it with no change (design decision 2).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `thought-store`: new requirements: every thought has an open or done status, and a status change leaves the rest of the thought and its search entries alone.
- `thought-filing`: new requirements: a proposal part can mark a filed thought done, which is applied only when the user confirms it; such a part does not count as filing, and does not stay held once its thought is deleted.
- `conversation-agent`: new requirements: the model proposes marking a thought done by ref, searches open thoughts first when the thought is not seen, does not say it was done before the user confirms, and is told which thoughts are done; the search tool filters by status and category.
- `thought-search`: modified requirement "Filters and order": search filters by status and by category, and needs no query with either.
- `chat-interface`: new requirement: the status-change card.
- `thought-detail-view`: new requirement: the sheet's Done toggle.
- `upcoming-thoughts` (added by `thought-dates`): new requirement: done thoughts are not listed.

## Impact

- Backend: `app/models/thought.py` and one Alembic migration (two columns); `app/thoughts/store.py` (`set_status()`); `app/routers/thoughts.py` (`status` in `GET` and `PATCH`, Upcoming filter); `app/thoughts/search.py` (status and category filters, a list with no query); `app/chat/prompt.py` and `app/chat/tools.py` (marks, search filters, notes, result marks, `PROPOSAL_SHOWN_STATUS`, `ToolRefusal`); `app/chat/turn.py` (refusals passed through as they are); `app/chat/proposal.py` and `app/routers/conversations.py` (marks in the payload, the offer, and confirm; what counts as filed and as held); `app/chat/chat.yaml` (`tool_rounds: 4`).
- Frontend: `lib/thoughts.ts` and `lib/sse.ts` (types), `components/chat/thought-sheet.tsx` (Done toggle), `components/chat/proposal-card.tsx` (status card).
- API: `status` and `status_changed_at` on `GET /api/thoughts/{id}`; `status` on `PATCH`; `mark` on proposal parts.
- Cost: none on the user's key for a status change. A search with only status or category filters makes no embedding call, and a call with only marks makes no similar-thought check. "I called the plumber" for a thought the conversation has not seen costs one search round. The fourth call per turn is used only by a turn that needs it, or by a model that loops.
- Depends on `thought-editing` (built on this branch: `PATCH`, `saved_title`), `thought-appending` (planned: refs, the seen-thoughts note, `target` on proposal parts, the similar-thought check), and `thought-dates` (planned: the optional search query, "Filters and order", the Upcoming page). Archive after all three (design decision 15).
