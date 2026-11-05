## Context

See `proposal.md` for why. This change sits on top of other changes, and plans against their specs and design.

Built on this branch:

- `thought-editing`: `PATCH /api/thoughts/{id}` with a closed field list (`ThoughtPatch`, `extra="forbid"`), `update_thought()` that re-indexes only what changed, `saved_title` and `deleted` on proposal parts (one query in `saved_titles()`, filtered by `Thought.user_id`), the `ff:thought-changed` window event, and Edit and Delete in `ThoughtSheet`.
- `event-category`: `event` is the sixth fixed kind. The Alembic head is `4d7a1c9e2b60` (`self-hosting-setup`).

Planned, not built here, and treated as in place:

- `thought-dates`: the `when` date columns, `dated_from`/`dated_to` on the search tool, a search with no query when a date range is given (a plain select in date order, no embedding call), and the Upcoming page with `GET /api/thoughts/upcoming`. It adds the `upcoming-thoughts` capability, and modifies `thought-search` "Filters and order".
- `thought-appending`: refs (`T1`, `T2`, …) for every thought a conversation has seen, the seen-thoughts note on every turn, `add_to` parts resolved from a ref in `write_proposal()`, `target` on proposal parts (the thought's current fields, read in the `saved_titles()` query), the similar-thought check (layers 1 to 3, also in the offer), the `based_on` and `after_updated_at` checks against `updated_at`, and `mode` on confirm. A bad `add_to` ref becomes a new thought; a tool argument error goes back to the model for another round.
- `background-turns` and `mcp-connectors`: no overlap with this change (Risks). `mcp-connectors` adds its own `connectors.tool_rounds` (5) for conversations with a connector on.

What exists on this branch, and matters here:

- `thoughts` has no status. `updated_at` has `onupdate=func.now()`, so any ORM update of the row moves it. The sheet shows it as the "changed" date.
- `parse_proposal()` in `app/chat/tools.py` reads each entry of `thoughts` as title, summary, tags, and category, and refuses an entry with no title or summary as a `ToolArgumentError`. The tool schema requires all four, and `thoughts` has `minItems: 1`.
- `Turn._run_tool()` in `app/chat/turn.py` sends every `ToolArgumentError` back as `Error: <message>. Call the tool again with valid arguments.` After a written proposal, the tool result is `PROPOSAL_SHOWN`, which calls the card editable and lists the words the reply must avoid (saved, noted, added, recorded).
- `Turn.events()` makes at most `chat.yaml` `tool_rounds` (3) model calls. The reply after the last tool call needs a call of its own, so a turn has at most two rounds of tool calls before it answers; a third ends in `tool_loop_limit`.
- A part counts as saved when it has a `thought_id`. `prompt.py` (`unsaved_parts()`, the held note), `proposal.py` (`held_parts()`, `discussion_start()`, `filed_titles()`, the offer), and confirm all rely on it. `discussion_start()` sets where the raw text of a later proposal starts, and whether the offer before archive and `/compact` asks the model at all.
- The offer (`offer_proposal()`) makes one asked call and passes its parts to `write_proposal()`. `asked_proposal()` catches only parse errors; there is no next round.
- Confirm (`POST .../proposals/{id}/confirm`) locks the proposal row, answers a repeated confirm with the saved `thought_id` and the message `Saved.` before anything else, and clears the held proposal once every part is saved.

## Goals / Non-Goals

**Goals:**

- One status field, set the same way from a confirmed card and from the sheet.
- A status change costs no embedding call and changes nothing else about the thought.
- No new tool, no new proposal kind outside `proposals.parts`, no change to the new-thought part schema, and no change to the one-proposal-per-answer rule.
- The later features (library, export, weekly review, resurfacing) read status from one column with no further migration for open and done.

**Non-Goals:**

- `archived` as a status, and any archive action (decision 2).
- Reopening from the chat. The sheet's toggle reopens. A later change can add it as a field on a stored status part with no migration, because parts are JSON.
- The thoughts library page, export, the weekly review, and resurfacing of untouched ideas. They build on this status later.
- Filing a new thought as done. A new thought is always open.
- Marking a thought done from its date passing, from an addition, or in bulk.
- A history of status changes. Only the last change's time is kept.
- Showing the status in the sources list under an answer. It stays the record of what the answer read (`thought-editing` decision 5).
- Leaving done thoughts out of the similar-thought check. A done task is still a candidate; `thought-appending` already tells the model a repeated task is usually new.
- An undo on a confirmed status card. The sheet's toggle sets it back.

## Decisions

### 1. Every thought has a status: `open` or `done`

A status belongs to every thought, not only to `task`. A new thought is `open`; existing thoughts become `open` in the migration.

Categories are the user's own and can change: a user may add `errand` or `chore`, or change a task to a note. A status tied to `task` would vanish or need rules each time. The library filter and export later read status from every thought. Most ideas and notes simply stay `open`, which costs nothing.

**Alternatives:** status only on `task` thoughts, null on others (rejected: a category edit would have to create or drop the status, and added task-like categories would get none); a boolean `done` (rejected: decision 2 needs a third value later).

### 2. `archived` is not a status in this change; a later change adds it to the same column

Feature 7 (resurfacing untouched ideas with keep, archive, or delete) needs "archive". It is out of scope here. When it is built, it adds `archived` as a third value of `thoughts.status`, with its own migration that widens the check constraint, and its own UI. It needs no new column: `status_changed_at` (decision 3) already says when the thought was archived.

So that this costs nothing later, every "open" list in this change asks for `status = 'open'` by name, never `status != 'done'`. An archived thought then drops out of the open search filter and the Upcoming page with no change. A search with no status filter will still find archived thoughts, as it finds done ones.

**Alternatives:**

- Add `archived` now, with no way to set it (rejected: a value no request can set and no spec scenario can test is scope creep).
- A separate `archived_at` column, now or later (rejected: two columns for one state, and every open list would have to check both; a thought could be done and archived at once, which no feature asks for).
- Delete instead of archive (rejected for feature 7: the user asked for archive and delete as two choices).

### 3. Two columns, and a status change keeps `updated_at`

`thoughts` gains:

- `status TEXT NOT NULL DEFAULT 'open'`, with a check constraint `status IN ('open', 'done')`.
- `status_changed_at TIMESTAMPTZ NULL`: the time of the last change of status, null while it never changed.

A status change does not move `updated_at`. Three reasons:

- The sheet's "changed" date is the date the content changed. A done date is shown on its own (decision 13).
- `thought-appending` compares `updated_at` with the part's `based_on` before an addition, and with `after_updated_at` before an undo. If marking a task done moved `updated_at`, an addition proposed before it would get a 409 for a field it does not touch, and the last addition could no longer be undone.
- Feature 7's "untouched" can read content changes from `updated_at` and status changes from `status_changed_at`, and decide which count.

The mechanism is a Core `UPDATE` that sets `updated_at` to the column itself (decision 4, step 4). When a statement gives a value for `updated_at`, SQLAlchemy does not add the column's `onupdate`, and a column expression keeps the stored value as it is. Setting the attribute to its own value on the ORM instance does not work: tested on the backend's SQLAlchemy, an unchanged value is dropped from the `SET` clause, and the statement becomes `UPDATE thoughts SET status=?, updated_at=CURRENT_TIMESTAMP`.

**Alternatives:** let `updated_at` move (rejected: the two `thought-appending` checks above); `flag_modified(thought, "updated_at")` on the ORM path (rejected: it writes back the value Python holds, so it depends on that value being loaded and round-tripping exactly, while the Core statement never leaves the database); `done_at` only, with the status read from it (rejected: decision 2's `archived` would need another column, and every filter becomes a null test); a status history table (rejected: no feature reads the history).

### 4. One store function, used by confirm and by `PATCH`

`set_status(session, user, thought_id, status)` in `app/thoughts/store.py`:

1. Loads the thought with `get_thought()`, so another user's thought and a missing one raise `not_found` with the same body.
2. Refuses any value but `open` or `done` with `validation_error` and the message `status: must be open or done`.
3. Returns the thought unchanged when the status is the same.
4. Otherwise runs `update(Thought).where(Thought.id == thought.id, Thought.user_id == user.id).values(status=status, status_changed_at=func.now(), updated_at=Thought.updated_at)` and then refreshes the instance, so the caller reads the new status and change time and the old `updated_at` (decision 3). It does not commit, so confirm can commit it with the part's `thought_id`, as `add_thought()` does.

It touches no search entry and makes no provider call. Status is not in `search_tsv` or in any embedded piece, so nothing in search needs to change.

`ThoughtPatch` gains `status`. The route calls `set_status()` first when `status` is in the body, then `update_thought()` for the other fields when there are any. `update_thought()` commits both; with `status` alone, the route commits. A refused field after the status rolls the status back with it, since the session closes without a commit. `GET` and `PATCH` answer `status` and `status_changed_at`. The status path is a new place that answers 404, so it gets its own check that another user's thought gives the same body as an unknown id.

**Alternatives:** a separate `POST /api/thoughts/{id}/done` (rejected: `PATCH` already owns changes to a thought, its errors, and the proxy test); a `status` argument on `update_thought()` (rejected: its every path commits and moves `updated_at`, and confirm needs a write it commits itself).

### 5. Status changes as `marks` on `propose_thought`

`propose_thought` gains an optional array beside `thoughts`: `marks`, each entry `{"ref": "T3"}`, a thought the conversation has seen that the user finished. A mark always means "mark done"; there is no status field (Non-Goals). The new-thought part schema is left exactly as it is, with all four fields required. `thoughts` stays required but loses `minItems: 1`, so a call that only marks a task done sends `"thoughts": []`. `parse_proposal()` reads `marks` on its own, and refuses:

- a call with no entry in `thoughts` and none in `marks`: `propose_thought needs at least one entry in thoughts or marks`;
- more than `MAX_PARTS` entries in both together;
- a mark with no `ref` string, naming `marks[0].ref`;
- a mark that also carries `add_to`, `new`, or `summary`: `marks[0]: a mark only names a ref; send an addition as its own entry in thoughts`. So "I called the plumber, he comes Tuesday" cannot lose the addition without a word.

One answer still shows one proposal. "I called the plumber, and I need to buy oat milk" is one call with one entry in `thoughts` and one in `marks`, written as one proposal with two parts. `write_proposal()` resolves each mark with the refs from `thought-appending` and stores it in `proposals.parts`, after the new and addition parts:

```
{"mark": "<thought id>", "title": "<the thought's title now>", "summary": "",
 "tags": [], "category": "<the thought's category now>", "thought_id": null}
```

The stored title and category come from the thought. They name the part in the held note, as `Mark T3 done: Call the plumber`, and on the card if the thought is later deleted. So the held proposal, the offer, the one-proposal-per-answer rule, confirm, and the card group handle a status part as one more part. A mark needs no new ref rule: it can only name a thought the conversation has already seen.

**The similar-thought check leaves marks out.** `thought-appending`'s layers 1 to 3 run on the call's new entries in `thoughts` only. A mark is not embedded and is never given `similar`, and the thought it names is excluded from the candidates of the other parts, as `thought-appending` excludes a thought named by `add_to`. A call with only marks makes no embedding call and has no candidate round. Without this, a mark would read as a new part (no `add_to`, no `new`), its best candidate would be the marked thought itself, and the card would be withheld for a candidate round.

**The tool result after a proposal with a status part.** `PROPOSAL_SHOWN` calls the card editable and forbids "saved, noted, added, or recorded", but not "marked done". When the written proposal has a part with `mark`, the turn sends `PROPOSAL_SHOWN_STATUS` instead: the proposal is shown as cards for the user to confirm; nothing changes until they confirm, so do not say a task is marked done, done, closed, or finished, or that anything is saved; say the change is ready for them to confirm. The rest is as in `PROPOSAL_SHOWN`.

**Alternatives:**

- A status part inside `thoughts`, with `mark` and `status` on the part and only `title` required (rejected: it loosens the schema every new thought uses, which risks a model leaving out summaries; it asks the model to copy a title the server then replaces; and a part could carry `mark` together with `add_to`, which needs rules of its own).
- A third tool, `propose_status` (rejected: a turn that marks one task done and files a new one would show two proposals, against "One proposal per answer"; and every place that handles a proposal would need a second kind).
- A `status` field on an addition part (rejected: an addition always rewrites the summary and extends the raw text, which "I called the plumber" should not).
- The server marks a task done when the model's text says so (rejected: nothing changes without a confirmed card).
- Marks that can also reopen (rejected: the feature asks for marking done; the sheet's toggle reopens).

### 6. A mark that cannot apply

`write_proposal()` checks each mark. In a turn, a mark that cannot apply refuses the whole call. Nothing is stored, the call does not count as the turn's proposal, and the model gets another round. The refusals, as the exact tool result:

- `mark` is not a ref the conversation has seen: `Error: T9 is not a thought this conversation has seen. Search for it with status open, then call propose_thought with the ref the search gives.`
- the thought no longer exists, or belongs to another user: `Error: T9 no longer exists. Do not propose it; tell the user it was deleted.`
- the thought is already done: `Error: T9 is already done. Do not propose it; tell the user it is already done.`
- two marks name the same thought: `Error: marks name T3 twice. Call propose_thought again with each thought once.`

These raise `ToolRefusal`, a subclass of `ToolArgumentError` whose message `_run_tool()` passes through as it is, without the generic `. Call the tool again with valid arguments.` suffix. That suffix would push the model to propose again after "already done", when it should tell the user. Parse errors (decision 5) keep the suffix.

This differs from `thought-appending`, where a bad `add_to` falls back to a new thought: a mark has nothing to fall back to.

**In the offer before archive and `/compact`**, there is no next round, so a mark that cannot apply is dropped and logged, and the rest of the call is offered. When nothing is left, nothing is offered and the action goes ahead. `offer_proposal()` calls `write_proposal(..., offered=True)`, which drops instead of refusing; it never raises for a mark, so the archive and `/compact` routes cannot fail on one.

An addition part and a mark may name the same thought in one proposal. The status change does not move `updated_at` (decision 3), so confirming one never makes the other's confirm fail.

**Alternatives:** drop the bad mark in a turn too (rejected: the model would say the change is ready for review when no card shows it); show a card that fails on confirm (rejected: the user would review a change that cannot be made); refuse in the offer too (rejected: the offer has no round to correct it, so the action would fail).

### 7. Confirming a status part

The confirm route, after its lock and its index checks, handles a part that has `mark`:

1. A request that names more than one part, when any is a status part, gets 422 `validation_error`: `parts: a status change is confirmed on its own`. Nothing is stored.
2. A repeated confirm finds `thought_id` set. Its early return answers `Marked done.` when the part has `mark`, and `Saved.` otherwise, with the same `thought_id`.
3. `set_status()` with the part's `mark` and `done`, before the category check. Its `not_found`, for a deleted thought or another user's, becomes 404 `not_found` with the message `This thought no longer exists.`. The body is the same in both cases, and nothing changes.
4. The part's `thought_id` is set to `mark`, and the held proposal is cleared when no part is still unsettled (decision 9). One commit.
5. The answer is `{"saved": true, "thought_id": <mark>, "message": "Marked done."}`.

The body's title, summary, tags, category, and `mode` are ignored for a status part. A thought that is already done, for example after the user toggled it in the sheet, is confirmed with no change (decision 4, step 3). No embedding call is made, so a provider failure cannot affect it.

Setting `thought_id` keeps "this part is settled" in one place for the held proposal and the card. `saved_titles()` then gives the card the thought's current title, and `deleted` once the thought is gone, as for any saved part. Decision 8 keeps it out of the "filed" test.

**Alternatives:** a separate field such as `marked: true` instead of `thought_id` (rejected: the held proposal, the held note, and the card would each need a second test for "settled").

### 8. A status part does not count as filing

`discussion_start()` and `filed_titles()` read a part with a `thought_id` as a filed thought. A confirmed status part has one, but it filed nothing. Counted, it would move the start of the next proposal's raw text past the discussion before it, make the offer before `/compact` and archive find "nothing said since the last saved proposal" and skip that discussion, and list the marked task in `FILED_NOTE` as filed from this conversation. Example: a user talks through a podcast idea, then says "I called the plumber" and confirms only the status card; `/compact` would offer nothing, and the idea would be lost.

So only parts that filed or added to a thought, those with a `thought_id` and no `mark`, count as saved for `discussion_start()` and `filed_titles()`, and for any helper `thought-appending` adds in their place for the offer. The held proposal and confirm still read `thought_id` on every part (decision 7). The `thought-filing` delta states the rule as its own requirement, so the raw-text requirement in the main spec and the offer requirement that `thought-appending` modifies keep their text.

The next proposal's raw text then includes "I called the plumber". That is the user's own words in the discussion, and the cost of keeping the idea.

**Alternatives:** count it as saved, as any part (rejected: the example above); store a confirmed status part without `thought_id` (rejected: decision 7).

### 9. A status part whose thought is gone is settled

A status part whose thought was deleted can never be confirmed: confirm answers 404. If it still counted as unsaved, the held proposal would never clear, the offer would show a dead card before every `/compact` and archive, and the held note would keep telling the model to propose it again, each time refused with "no longer exists".

So a status part whose `mark` names no thought of the user is settled, like a saved part, for `unsaved_parts()`, `held_parts()`, the held note, the offer, and the held-proposal clearing in confirm. `gone_marks(session, user, parts)` in `app/chat/proposal.py` returns the `mark` ids of the unsaved status parts whose thought does not exist for this user, in one query, and returns none without a query when no part has `mark`. The callers that decide what is held pass it to `unsaved_parts()`. The card still shows the part, with "This thought no longer exists." from `target`.

**Alternatives:** on a 404, write `gone: true` on the part (rejected: it covers only a user who clicks confirm, and the 404 answer would have to commit a change while saying nothing changed); leave it held (rejected: the dead card, and a wasted round on every turn).

### 10. The status card

Each proposal part in the payload (stream event, messages answer, offered proposal) gains `mark` (thought id or null). The `target` lookup from `thought-appending` reads `mark` ids too, in the same query and with the same `Thought.user_id == user.id` filter, so a crafted `mark` with another user's id gets `target: {deleted: true}` and none of that thought's fields.

`ProposalCard` shows a part with `mark` as a small card with no fields:

- Before confirm: "Mark done: <target title>", the category as a badge, and one button, "Mark done". When `target` says deleted: "This thought no longer exists." and no button.
- After confirm: "Marked done: <saved_title>" with the Open link.
- After the thought is deleted: the "Deleted" state from `thought-editing`.
- A 404 on confirm turns the card to "This thought no longer exists."

The group hides the merge button when any part has `mark`, as it does for `add_to`.

**Alternatives:** show the full thought fields, read-only (rejected: the card asks one question, and the sheet is one click away); add `status` to `target` and show "Already done" when the sheet set it first (rejected: a turn already refuses a mark on a done thought, and confirming one is a harmless no-op that ends in "Marked done").

### 11. Four tool rounds per turn

With three model calls, the reply needs the last one, so a turn has two rounds of tool calls. These flows need three:

- A mark on an unseen ref: propose (refused), search, propose, reply.
- `/push I called the plumber`, whose first round is forced to propose: propose (refused), search, propose, reply.
- "I called the plumber, and I need to buy oat milk" with an unseen plumber task and a similar oat milk thought: search, propose (candidates), propose, reply.

`chat.yaml` `tool_rounds` goes from 3 to 4. It costs nothing on a turn that needs fewer rounds. A model that loops gets one more call before `tool_loop_limit`: at most `reply_max_tokens` more output and one more prompt on the user's key. `mcp-connectors` keeps its own `connectors.tool_rounds` (5) for conversations with a connector on.

**Alternatives:** keep 3 and let these turns end with the round-limit error (rejected: the steered path for a task the conversation has not seen would fail whenever the model first guesses a ref); a separate round budget for refused calls (rejected: a second limit in the loop for the same purpose).

### 12. Search: status and category filters, and a list with no query

`search_thoughts()` gains `status` and `category`. The filtered CTE gains:

```
AND (CAST(:status AS text) IS NULL OR status = :status)
AND (CAST(:category AS text) IS NULL OR category = :category)
```

`thought-dates` added a path with no query when a `dated_*` filter is given: a plain select of the filtered thoughts, no embedding call, no backfill, with a total count. This change takes the same path when `status` or `category` is given and there is no query. The order is date order with a `dated_*` filter, as in `thought-dates`, and otherwise `created_at DESC`. The limit is `config.limit`.

The search tool gets `status` (enum `open`, `done`) and `category` (a string; one of the user's categories). `parse_search()` refuses any other status, naming `status`, cleans the category with `clean_name()`, and refuses a call with no query and none of `dated_from`, `dated_to`, `status`, or `category`, naming `query`. A category the user does not have simply matches nothing.

`format_search_result()` adds ` · done <date>` after the filed date of a done thought, from `status_changed_at`. An open thought gets no mark, so the usual result costs no more tokens. The seen-thoughts note from `thought-appending` marks a done thought `done` the same way, and a candidate round's tool result adds: "If the user says they finished a candidate task, mark it done instead." The header of a list with no query and no date filter says "newest first". With a status or category filter, the no-match text says no filed thoughts match those filters; a date-only search keeps the `thought-dates` text.

No new index. A list with no query reads the user's rows through `ix_thoughts_user_id_created_at`; at 5,000 thoughts this is well inside the `thought-search` speed budget.

**Alternatives:** an `include_done` flag that defaults to off (rejected: the user asked that search still find done thoughts, and a default that hides them would make "did I buy the milk?" answer "nothing filed"); a status filter with no category filter (rejected: every thought is open by default, so "open" alone lists ideas and notes as well; "open tasks" needs both); a separate `list_thoughts` tool (rejected: `thought-dates` already made the query optional for a filter-only search; a third tool costs tokens on every turn).

### 13. The sheet's Done toggle

In view mode, the row with Edit and Delete gains a native checkbox labelled "Done" (no new dependency; the UI kit has no checkbox). Turning it sends `PATCH {status}` at once, with the box disabled while the request runs. The sheet takes the answer as its thought. A failure puts the box back and shows the server's message in an alert, as the sheet does for an edit. Beside a done box, the sheet shows "Done on <date>" from `status_changed_at`, formatted like the filed and changed dates.

The toggle is hidden in edit mode, so a status change never mixes with an unsaved edit. `updateThought()` dispatches `ff:thought-changed` as it does now; nothing listens for status, and the Upcoming page already reloads when the sheet closes.

**Alternatives:** status as a field in edit mode (rejected: the user asked for a toggle, and "done" is one click, not an edit); a button "Mark done" (rejected: a checkbox shows the state and the action in one control, and reads well to a screen reader).

### 14. The Upcoming page lists only open thoughts

`GET /api/thoughts/upcoming` gains `AND status = 'open'`. Nothing else on the page changes: it reloads when the sheet closes, so a thought marked done there drops out, and a thought set back to open comes back.

**Alternatives:** list done thoughts struck through (rejected: the page answers "what is coming up", and a done task is not).

### 15. Spec deltas and archive order

Most requirements in this change are ADDED. One is MODIFIED:

- `thought-search` "Filters and order" is modified by `thought-dates`, which makes the query optional with a thought-date filter and keeps the scenario "No query and no thought date", which refuses any other search with no query. An ADDED rule beside it would leave that scenario refusing a status-only search. So this change modifies the requirement: its text is `thought-dates`' text with the status and category filters added, the query optional with any of them, and newest filed first without a date filter; its last scenario becomes "No query and no filter". **If `thought-dates`' version of the requirement changes before archive, re-copy it here.**

Wording that a later archive should fold together, left as ADDED requirements because open changes already modify these blocks:

- `conversation-agent` "Tools to file and find thoughts" (modified by `thought-appending` and `mcp-connectors`) says a proposal holds parts with a title, summary, tags, and category, and the search tool takes a query. This change's added requirements add marks and the optional query.
- `conversation-agent` "The offer before an action may propose nothing" (modified by `thought-appending`) and `thought-filing` "The raw text is kept with the thought" speak of a saved proposal. `thought-filing` "A status change does not count as filing" says a status part does not make one (decision 8).
- `thought-filing` "A message with several thoughts is split" offers merge before any part is saved. "A status part is confirmed on its own" adds the exception, as `thought-appending` does for additions.

`upcoming-thoughts` exists only once `thought-dates` is archived, "Filters and order" is copied from `thought-dates`, and marks need `thought-appending`'s refs. So **archive this change after `thought-dates` and `thought-appending`**. Task group 3 and the end-to-end task 5.1 need `thought-appending` built, and tasks 2.1, 2.2, 4.4, and 5.1 need `thought-dates` built.

## Risks / Trade-offs

- [The model marks the wrong thought done] → The card names the thought by its current title, and nothing changes until the user confirms. The sheet's toggle sets it back.
- [A small model does not search before proposing, and names a ref it has not seen] → The tool result tells it to search first, and the fourth call (decision 11) leaves room to search, propose, and reply. A model that still loops ends with `tool_loop_limit`, as today. The user can still use the sheet.
- [A model says the task was marked done before the user confirms] → `PROPOSAL_SHOWN_STATUS` (decision 5) forbids it, and the status probe counts such replies against a limit.
- [A status change does not move `updated_at`, so a reader that sorts by "last changed" misses it] → `status_changed_at` is in every answer; decision 3 gives the reasons.
- [Every thought is open by default, so "open" alone lists ideas and notes] → The prompt steers the model to add the category `task` for tasks, and the status probe checks it.
- [Four calls per turn instead of three] → One more model call only for a turn that needs it or a model that loops (decision 11).
- [`thought-appending` is not built, and its refs, `target`, layer 1, or `write_proposal()` may change shape] → Re-read decisions 5 to 10 before task group 3.
- [`thought-dates` is not built, and its no-query path, the Upcoming route, or "Filters and order" may change] → Re-read decisions 12, 14, and 15 before tasks 2.1 and 4.4, and re-copy the modified requirement.
- [`background-turns` (planned) runs the turn as a background task] → A status part is a normal proposal part in a normal proposal event; a replay shows it as it shows any card. No change needed.
- [`mcp-connectors` (planned) prefixes connector tool names and has its own round limit] → The built-in `propose_thought` and `search_thoughts` keep their names, and its `connectors.tool_rounds` (5) is already above 4.

## Migration Plan

1. One Alembic revision adds `status` (`NOT NULL`, server default `'open'`, check constraint `ck_thoughts_status`) and `status_changed_at` (nullable). Every existing thought becomes `open` with no change time. Its `down_revision` is the single head when it is built: run `uv run alembic heads` in `backend/` first. On this branch that is `4d7a1c9e2b60`, but the revisions of `thought-dates` and `thought-appending` come before this one. Downgrade drops the constraint and both columns.
2. Ship the backend and frontend together. An older frontend shows a status part as an empty card, and its confirm would still mark the thought done.
3. Rollback: downgrade and deploy the previous build. Statuses set since are lost; the thoughts stay. Proposals keep status parts in their JSON, which an older build shows as empty cards.
