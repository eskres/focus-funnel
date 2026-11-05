## Why

A filed `task` can never be closed. No thought has a status today, so "call the plumber" stays a to-do forever, and a question about open tasks gets back the ones already done. A thought needs an open or done status that the user sets, from the chat or from the sheet.

## What Changes

- Every thought has a status: `open` or `done`. A new thought is `open`. Existing thoughts become `open`. The time of the last status change is kept.
- A status change touches nothing else. It does not change the thought's title, summary, tags, category, raw text, or "changed" date, and it makes no embedding call. So it does not count as a change to the thought when an addition proposed before it is confirmed, or when the last addition is undone, and neither of those changes the status.
- `propose_thought` gains an optional `marks` list beside `thoughts`; a call with only `marks` may leave `thoughts` out, and two marks with the same ref count as one. Each mark names a thought the conversation has seen by its ref (`T1`, `T2`, … from the `thought-appending` change), to mark it done. "I called the plumber" makes the model propose marking that task done. A mark is written as one more part of the same proposal as any new thought or addition, so one answer still shows one proposal. The new-thought part schema does not change.
- When the task is not among the thoughts the conversation has seen, the model first searches the user's open thoughts for it, then proposes. A turn gets four model calls instead of three, so this fits.
- The card for a status part says "Mark done: <title>". Nothing changes until the user confirms it. A confirmed card says "Marked done: <title>" with a link. A confirm of a thought that was deleted says it no longer exists. Reopening is done in the sheet, not from the chat.
- A confirmed status part does not count as a filed thought: the discussion before it is still offered before `/compact` and archive. A status part never keeps a proposal held: an unconfirmed mark is not offered again on a change of topic, at archive, or at `/compact`, and a later proposal does not fold its card away, so it stays confirmable in the chat. The offer before archive and `/compact` holds no marks.
- The thought detail sheet gets a Done toggle. It saves at once, and the sheet shows when the thought was marked done. It also sets a done thought back to open.
- `PATCH /api/thoughts/{id}` takes `status`; `GET` answers `status` and `status_changed_at`.
- `search_thoughts` takes two optional filters: `status` and `category`. "What tasks are still open?" searches with `status: open` and `category: task`, and leaves out done ones. With either filter, the query is optional. Without a status filter, search still finds done thoughts, and the result marks each done one.
- The note of seen thoughts and the list of similar thoughts tell the model which thoughts are done. The chat's tool summaries name a status proposal, a refused mark, and a search with no query in their own words.
- The Upcoming page (from `thought-dates`) lists only open thoughts.
- `archived` is not a status in this change. A later change that adds archiving adds it as a third value of the same status. Every "open" list here asks for `open` by name, so an archived thought drops out of it with no change (design decision 2).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `thought-store`: new requirements: every thought has an open or done status, and a status change leaves the rest of the thought and its search entries alone.
- `thought-filing`: new requirements: a proposal part can mark a filed thought done, which is applied only when the user confirms it; such a part does not count as filing; a status change does not block confirming or undoing an addition. Modified requirement "A message with several thoughts is split": merging is not offered, and a merge confirm is refused, when a part marks a thought done.
- `conversation-agent`: new requirements: the model proposes marking a thought done by ref, searches open thoughts first when the thought is not seen, does not say it was done before the user confirms, and is told which thoughts are done, in search results, the seen-thoughts note, and the similar-thought question; the search tool filters by status and category. Modified requirement "A proposal is held while the conversation carries on": a status part does not keep a proposal held, is not offered again, and is not folded away.
- `thought-search`: modified requirement "Filters and order": search filters by status and by category, and needs no query with either; a search with no query lists and counts only the user's own thoughts.
- `chat-interface`: new requirements: the status-change card, and its state when the thought is deleted after the mark.
- `thought-detail-view`: new requirement: the sheet's Done toggle. Modified requirement "A thought opens in a side sheet": the sheet shows whether the thought is done and when, and Done joins Edit and Delete as a way the sheet changes the thought.
- `upcoming-thoughts` (added by `thought-dates`): modified requirement "The Upcoming page lists dated thoughts from today on": it lists only open dated thoughts.

## Impact

- Backend: `app/models/thought.py` and one Alembic migration (two columns); `app/thoughts/store.py` (`set_status()`); `app/routers/thoughts.py` (`status` in `GET` and `PATCH`, Upcoming filter); `app/thoughts/search.py` (status and category filters, a list with no query); `app/chat/prompt.py` and `app/chat/tools.py` (marks, search filters, notes, result marks, `PROPOSAL_SHOWN_STATUS`, `ToolRefusal`); `app/chat/turn.py` (refusals passed through as they are, the held note dropped only after a proposal row is written, the tool summaries); `app/chat/proposal.py` and `app/routers/conversations.py` (marks in the payload, the offer, and confirm; what counts as filed and as held; marks left out of the offer, logged by count with no thought's title or category; done markers on similar-thought candidates); `app/chat/chat.yaml` (`tool_rounds: 4`).
- Frontend: `lib/thoughts.ts` and `lib/sse.ts` (types), `components/chat/thought-sheet.tsx` (Done toggle), `components/chat/proposal-card.tsx` (status card; status cards of a replaced proposal not folded away), `components/chat/proposal-dialog.tsx` (status parts left out of the offer dialog).
- API: `status` and `status_changed_at` on `GET /api/thoughts/{id}`; `status` on `PATCH`; `mark` on proposal parts.
- Cost: none on the user's key for a status change. A search with only status or category filters makes no embedding call, and a call with only marks makes no similar-thought check. "I called the plumber" for a thought the conversation has not seen costs one search round. The fourth call per turn is used only by a turn that needs it, or by a model that loops.
- Depends on `thought-editing` (built on this branch: `PATCH`, `saved_title`), `thought-appending` (planned: refs, the seen-thoughts note, `target` on proposal parts, the similar-thought check), and `thought-dates` (planned: the optional search query, "Filters and order", the Upcoming page). Archive after all three (design decision 15).
- Overlaps `mcp-connectors` (planned) in `_run_tool()`'s propose branch and error handling; whichever is built second moves this change's refusal pass-through and result texts into its `BuiltinTools` (design Risks).
