## Context

See `proposal.md` for why. This change sits on top of other changes, and plans against their specs and design.

Built on this branch:

- `thought-editing`: `PATCH /api/thoughts/{id}` with a closed field list (`ThoughtPatch`, `extra="forbid"`), `update_thought()` that re-indexes only what changed, `saved_title` and `deleted` on proposal parts (one query in `saved_titles()`, filtered by `Thought.user_id`), the `ff:thought-changed` window event, and Edit and Delete in `ThoughtSheet`.
- `event-category`: `event` is the sixth fixed kind. The Alembic head is `4d7a1c9e2b60` (`self-hosting-setup`).

Planned, not built here, and treated as in place:

- `thought-dates`: the `when` date columns, `dated_from`/`dated_to` on the search tool, a search with no query when a date range is given (a plain select in date order, no embedding call), and the Upcoming page with `GET /api/thoughts/upcoming`. It adds the `upcoming-thoughts` capability, and modifies `thought-search` "Filters and order".
- `thought-appending`: refs (`T1`, `T2`, …) for every thought a conversation has seen, the seen-thoughts note on every turn, `add_to` parts resolved from a ref in `write_proposal()`, `target` on proposal parts (the thought's current fields, read in the `saved_titles()` query), the similar-thought check (layers 1 to 3, also in the offer), the `based_on` and `after_updated_at` checks against `updated_at`, and `mode` on confirm. A bad `add_to` ref becomes a new thought; a tool argument error goes back to the model for another round.
- `background-turns`: no overlap with this change (Risks).
- `mcp-connectors`: moves `_run_tool()`'s search and propose code into `BuiltinTools`, which returns a `ToolOutcome`, and keeps one shared error handler in `_run_tool()`. This change edits the same propose branch and the same error handling (Risks). It also adds its own `connectors.tool_rounds` (5) for conversations with a connector on.

What exists on this branch, and matters here:

- `thoughts` has no status. `updated_at` has `onupdate=func.now()`, so any ORM update of the row moves it. The sheet shows it as the "changed" date.
- `parse_proposal()` in `app/chat/tools.py` reads each entry of `thoughts` as title, summary, tags, and category, and refuses an entry with no title or summary as a `ToolArgumentError`. The tool schema requires all four, and `thoughts` has `minItems: 1`. A call with no `thoughts` is refused, unless it has a top-level `title` (an older call shape, read as one part).
- `Turn._run_tool()` in `app/chat/turn.py` sends every `ToolArgumentError` back as `Error: <message>. Call the tool again with valid arguments.`, with the chat summary `The tool call was not valid`. After a written proposal, the tool result is `PROPOSAL_SHOWN`, which calls the card editable and lists the words the reply must avoid (saved, noted, added, recorded), and the summary is `Proposed a thought to file`. A search's summary is `Searched your thoughts for “<query>”`.
- In the propose branch, `_run_tool()` calls `drop_held_note()` and clears `self.held_parts` before `write_proposal()`. Only `parse_proposal()`, which runs before them, can refuse a call today. `drop_held_note()` finds the note by rendering `held_proposal_note()` again and comparing the text.
- `Turn.events()` makes at most `chat.yaml` `tool_rounds` (3) model calls. The reply after the last tool call needs a call of its own, so a turn has at most two rounds of tool calls before it answers; a third ends in `tool_loop_limit`.
- A part counts as saved when it has a `thought_id`. `prompt.py` (`unsaved_parts()`, the held note), `proposal.py` (`held_parts()`, `discussion_start()`, `filed_titles()`, the offer, and the replace test in `write_proposal()`), and confirm all rely on it. `write_proposal()` always makes the new proposal the held one, and marks the earlier held proposal replaced when it still has an unsaved part. The chat folds a replaced proposal's unsaved cards away, and the offer dialog (`proposal-dialog.tsx`) shows a held proposal's cards with `thought_id === null`. `discussion_start()` sets where the raw text of a later proposal starts, and whether the offer before archive and `/compact` asks the model at all.
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
- Leaving done thoughts out of the similar-thought check. A done task is still a candidate; `thought-appending` already tells the model a repeated task is usually new, and the candidate list marks a done candidate done (decision 12).
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

- `status TEXT NOT NULL DEFAULT 'open'`, with a check constraint `status IN ('open', 'done')`. The model declares it as `CheckConstraint("status IN ('open', 'done')", name="status")` in `Thought.__table_args__`; the metadata naming convention (`ck_%(table_name)s_%(constraint_name)s` in `app/db.py`) makes it `ck_thoughts_status`. The migration names it `op.f('ck_thoughts_status')`, as `setup_state` does, and adds it inside `op.batch_alter_table("thoughts")`, so SQLite (where `env.py` already turns on batch mode) rebuilds the table. Naming it `ck_thoughts_status` in the model would render as `ck_thoughts_ck_thoughts_status`.
- `status_changed_at TIMESTAMPTZ NULL`: the time of the last change of status, null while it never changed.

A status change does not move `updated_at`. Three reasons:

- The sheet's "changed" date is the date the content changed. A done date is shown on its own (decision 13).
- `thought-appending` compares `updated_at` with the part's `based_on` before an addition, and with `after_updated_at` before an undo. If marking a task done moved `updated_at`, an addition proposed before it would get a 409 for a field it does not touch, and the last addition could no longer be undone. Those two `thought-appending` requirements say a confirm or an undo is refused when "the thought changed", so the `thought-filing` delta adds "A status change does not block an addition": a status change does not count there. An undo restores the addition's `before` (title, summary, tags, category, raw text), which holds no status, so it keeps the status and `status_changed_at`; an addition's confirm writes no status either.
- Feature 7's "untouched" can read content changes from `updated_at` and status changes from `status_changed_at`, and decide which count.

The mechanism is a Core `UPDATE` that sets `updated_at` to the column itself (decision 4, step 4). When a statement gives a value for `updated_at`, SQLAlchemy does not add the column's `onupdate`, and a column expression keeps the stored value as it is. Setting the attribute to its own value on the ORM instance does not work: tested on the backend's SQLAlchemy, an unchanged value is dropped from the `SET` clause, and the statement becomes `UPDATE thoughts SET status=?, updated_at=CURRENT_TIMESTAMP`.

**Alternatives:** let `updated_at` move (rejected: the two `thought-appending` checks above); a constraint with no name (rejected: the convention needs `constraint_name`, and `alembic check` would compare an unnamed constraint); `flag_modified(thought, "updated_at")` on the ORM path (rejected: it writes back the value Python holds, so it depends on that value being loaded and round-tripping exactly, while the Core statement never leaves the database); `done_at` only, with the status read from it (rejected: decision 2's `archived` would need another column, and every filter becomes a null test); a status history table (rejected: no feature reads the history).

### 4. One store function, used by confirm and by `PATCH`

`set_status(session, user, thought_id, status)` in `app/thoughts/store.py`:

1. Loads the thought with `get_thought()`, so another user's thought and a missing one raise `not_found` with the same body.
2. Refuses any value but `open` or `done` with `validation_error` and the message `status: must be open or done`.
3. Returns the thought unchanged when the status is the same.
4. Otherwise runs `update(Thought).where(Thought.id == thought.id, Thought.user_id == user.id, Thought.status != status).values(status=status, status_changed_at=func.now(), updated_at=Thought.updated_at)` and reads the row count. With one row, it refreshes the instance, so the caller reads the new status and change time and the old `updated_at` (decision 3). With none, another request changed or deleted the thought after step 1: it reads the thought again with `get_thought()` (with `populate_existing`), so a deleted one raises the usual `not_found`, and one that already has the status is returned unchanged. It does not commit, so confirm can commit it with the part's `thought_id`, as `add_thought()` does.

The `status != status` guard keeps "the same status changes nothing" true when two requests race: a confirm from two conversations, or a confirm and a sheet `PATCH` (confirm locks the proposal row, not the thought). Both pass step 3, but only the first `UPDATE` matches, so `status_changed_at` keeps the first write's time. Without the re-read, a thought deleted between step 1 and step 4 would make the refresh raise instead of answering 404.

It touches no search entry and makes no provider call. Status is not in `search_tsv` or in any embedded piece, so nothing in search needs to change.

`ThoughtPatch` gains `status`. The route calls `set_status()` first when `status` is in the body, then `update_thought()` for the other fields when there are any. `update_thought()` commits both; with `status` alone, the route commits. A refused field after the status rolls the status back with it, since the session closes without a commit. `GET` and `PATCH` answer `status` and `status_changed_at`. The status path is a new place that answers 404, so it gets its own check that another user's thought gives the same body as an unknown id.

**Alternatives:** a separate `POST /api/thoughts/{id}/done` (rejected: `PATCH` already owns changes to a thought, its errors, and the proxy test); a `status` argument on `update_thought()` (rejected: its every path commits and moves `updated_at`, and confirm needs a write it commits itself); `SELECT … FOR UPDATE` on the thought in step 1 (rejected: SQLite ignores it, and the guarded `UPDATE` gives the same answer with no lock on either store).

### 5. Status changes as `marks` on `propose_thought`

`propose_thought` gains an optional array beside `thoughts`: `marks`, each entry `{"ref": "T3"}`, a thought the conversation has seen that the user finished. A mark always means "mark done"; there is no status field (Non-Goals). The new-thought part schema is left exactly as it is, with all four fields required. `thoughts` stays required in the schema but loses `minItems: 1`, so a call that only marks a task done sends `"thoughts": []`. Many providers do not enforce `required`, and a model marking one task done will often send only `{"marks": [{"ref": "T3"}]}`, so `parse_proposal()` reads a missing `thoughts` as `[]` when `marks` is present (the older top-level `title` shape is read as today). `parse_proposal()` reads `marks` on its own. It keeps one entry per ref: a mark carries only a ref and always means "mark done", and each thought has one ref, so a second mark with the same ref holds the same data and is dropped, not refused. It refuses:

- a call with no entry in `thoughts` and none in `marks`: `propose_thought needs at least one entry in thoughts or marks`;
- more than `MAX_PARTS` entries in both together;
- a mark with no `ref` string, naming `marks[0].ref`;
- a mark that also carries `add_to`, `new`, or `summary`: `marks[0]: a mark only names a ref; send an addition as its own entry in thoughts`. So "I called the plumber, he comes Tuesday" cannot lose the addition without a word.

One answer still shows one proposal. "I called the plumber, and I need to buy oat milk" is one call with one entry in `thoughts` and one in `marks`, written as one proposal with two parts. `write_proposal()` resolves each mark with the refs from `thought-appending` and stores it in `proposals.parts`, after the new and addition parts:

```
{"mark": "<thought id>", "title": "<the thought's title now>", "summary": "",
 "tags": [], "category": "<the thought's category now>", "thought_id": null}
```

The stored title and category come from the thought. They are for the card only: they name the thought on the card if it is later deleted (decision 10). No log line holds a thought's title, category, or summary, as no log line in `app/chat/proposal.py` holds user content today. So the one-proposal-per-answer rule, confirm, and the card group handle a status part as one more part. The held proposal, the held note, the fold of replaced cards, and the offer leave it out (decision 9). A mark needs no new ref rule: it can only name a thought the conversation has already seen.

**The similar-thought check leaves marks out.** `thought-appending`'s layers 1 to 3 run on the call's new entries in `thoughts` only. A mark is not embedded and is never given `similar`, and the thought it names is excluded from the candidates of the other parts, as `thought-appending` excludes a thought named by `add_to`. A call with only marks makes no embedding call and has no candidate round. Without this, a mark would read as a new part (no `add_to`, no `new`), its best candidate would be the marked thought itself, and the card would be withheld for a candidate round.

**Marks are checked before layer 1, and survive a candidate round.** The mark checks of decision 6 run first, before layer 1 and any embedding call, so a bad mark costs one round and no provider call. A call with a mark and a new part that has candidates writes nothing, as `thought-appending` decision 4 says for any call. Its tool result asks only about the new parts, so a model often resends only `thoughts`, and the one-proposal-per-turn rule would then block the mark for the rest of the turn. So when the call had marks, the candidate round's tool result adds the line `Send the marks again in the same call.` The second call is checked for marks again (one query, no embedding).

**The tool result after a proposal with a status part.** `PROPOSAL_SHOWN` calls the card editable and forbids "saved, noted, added, or recorded", but not "marked done". When the written proposal has a part with `mark`, the turn sends `PROPOSAL_SHOWN_STATUS` instead: the proposal is shown as cards for the user to confirm; nothing changes until they confirm, so do not say a task is marked done, done, closed, or finished, or that anything is saved; say the change is ready for them to confirm. The rest is as in `PROPOSAL_SHOWN`.

**The chat summary.** When every part of the written proposal has `mark`, the tool event's summary is `Proposed marking a thought done`, not `Proposed a thought to file`. A proposal with any new part or addition keeps `Proposed a thought to file`.

**Alternatives:**

- A status part inside `thoughts`, with `mark` and `status` on the part and only `title` required (rejected: it loosens the schema every new thought uses, which risks a model leaving out summaries; it asks the model to copy a title the server then replaces; and a part could carry `mark` together with `add_to`, which needs rules of its own).
- A third tool, `propose_status` (rejected: a turn that marks one task done and files a new one would show two proposals, against "One proposal per answer"; and every place that handles a proposal would need a second kind).
- A `status` field on an addition part (rejected: an addition always rewrites the summary and extends the raw text, which "I called the plumber" should not).
- Refuse two marks with the same ref, as `thought-appending` refuses a duplicate `add_to` (rejected: two additions carry different text, so one would be lost; two marks carry the same data, so a refusal only costs a round).
- Keep a candidate round's marks on the server for the next call (rejected: hidden state between two tool calls, which a model that changes its mind would not see; one line in the tool result does the same).
- The server marks a task done when the model's text says so (rejected: nothing changes without a confirmed card).
- Marks that can also reopen (rejected: the feature asks for marking done; the sheet's toggle reopens).

### 6. A mark that cannot apply

`write_proposal()` checks each mark, before layer 1 and any embedding call (decision 5). In a turn, a mark that cannot apply refuses the whole call. Nothing is stored, the call does not count as the turn's proposal, and the model gets another round. The refusals, as the exact tool result:

- `mark` is not a ref the conversation has seen: `Error: T9 is not a thought this conversation has seen. Search for it with status open, then call propose_thought with the ref the search gives.`
- the thought no longer exists, or belongs to another user: `Error: T9 no longer exists. Do not propose it; tell the user it was deleted.`
- the thought is already done: `Error: T9 is already done. Do not propose it; tell the user it is already done.`

These raise `ToolRefusal`, a subclass of `ToolArgumentError` whose message `_run_tool()` passes through as it is, without the generic `. Call the tool again with valid arguments.` suffix. That suffix would push the model to propose again after "already done", when it should tell the user. Parse errors (decision 5) keep the suffix. The chat summary of a `ToolRefusal` is `Could not propose that change`, not `The tool call was not valid`: an "already done" refusal answers a correct call.

**The held note is dropped only after a written proposal.** Today `_run_tool()` drops the held-proposal note and clears `self.held_parts` before `write_proposal()`, which was safe while only `parse_proposal()`, earlier, could refuse. A `ToolRefusal` is raised inside `write_proposal()`. If the note were already gone, a refused call would leave the model without it: a user with a held oat-milk proposal says "I called the plumber, and I need to book the dentist"; on the change of topic the model re-proposes the oat-milk part, the dentist part, and a guessed mark, and is refused; with no note in front of it, its corrected call holds only the dentist part and the mark, replaces the held proposal, and folds the oat-milk card away. So `_run_tool()` drops the note and clears `self.held_parts` only when `write_proposal()` wrote a proposal row. On a `ToolRefusal`, the note stays in the context and the held proposal stays held. A candidate round from `thought-appending`'s layer 2 also returns normally but writes no proposal row; it keeps the note and `self.held_parts` too, so the model's next call still sees the held parts and does not replace the held proposal without them.

`drop_held_note()` today finds the note by rendering `held_proposal_note()` again and comparing the text. The note now depends on more than the parts (refs from `thought-appending`, dates from `thought-dates`, and which parts count as unsaved, decision 9), so a second render can differ and leave the note in place. So the `Turn` keeps a reference to the note dict that `build_context()` appended (`self.held_note`, the last context entry when the turn starts with held parts), and `drop_held_note()` removes that object by identity, with no second render.

This differs from `thought-appending`, where a bad `add_to` falls back to a new thought: a mark has nothing to fall back to.

**In the offer before archive and `/compact`**, every mark is dropped, with no per-mark check (decision 9). The offer has no next round, and a mark there is not discussion that could be lost. `offer_proposal()` calls `write_proposal(..., offered=True)`, which removes parts with `mark` before anything else and logs one line with the conversation id, the proposal id when one is written, and the number of marks dropped. The line holds no title, category, or summary (decision 5). When nothing is left, nothing is offered and the action goes ahead. It never raises for a mark, so the archive and `/compact` routes cannot fail on one.

An addition part and a mark may name the same thought in one proposal. The status change does not move `updated_at` (decision 3), so confirming one never makes the other's confirm fail.

**Alternatives:** drop the bad mark in a turn too (rejected: the model would say the change is ready for review when no card shows it); show a card that fails on confirm (rejected: the user would review a change that cannot be made); refuse in the offer too (rejected: the offer has no round to correct it, so the action would fail); check marks after layer 1 (rejected: a bad mark would cost an embedding call and a candidate round before it is refused, and could push a turn past the four calls of decision 11); keep dropping the held note before `write_proposal()` (rejected: the example above, where the held proposal is replaced without its held part); drop it whenever `write_proposal()` returns (rejected: a candidate round returns with no proposal written, and the re-sent call would then replace the held proposal without its held parts, the same failure); log the dropped mark's title (rejected: logs hold no user content).

### 7. Confirming a status part

The confirm route, after its lock and its index checks, handles a part that has `mark`:

1. A request that names more than one part, when any is a status part, gets 422 `validation_error`: `parts: a status change is confirmed on its own`. Nothing is stored.
2. A repeated confirm finds `thought_id` set. Its early return answers `Marked done.` when the part has `mark`, and `Saved.` otherwise, with the same `thought_id`.
3. `set_status()` with the part's `mark` and `done`, before the category check. Its `not_found`, for a deleted thought or another user's, becomes 404 `not_found` with the message `This thought no longer exists.`. The body is the same in both cases, and nothing changes.
4. The part's `thought_id` is set to `mark`, and the held proposal is cleared when `unsaved_parts()` gives none (decision 9). One commit.
5. The answer is `{"saved": true, "thought_id": <mark>, "message": "Marked done."}`.

The body's title, summary, tags, category, and `mode` are ignored for a status part. A thought that is already done, for example after the user toggled it in the sheet, is confirmed with no change (decision 4, step 3). No embedding call is made, so a provider failure cannot affect it.

Setting `thought_id` keeps "this part is confirmed" in one place for a repeated confirm and the card. `saved_titles()` then gives the card the thought's current title, and `deleted` once the thought is gone, as for any saved part. Decision 8 keeps it out of the "filed" test.

**Alternatives:** a separate field such as `marked: true` instead of `thought_id` (rejected: the repeated confirm, the card, and the payload would each need a second test for "confirmed").

### 8. A status part does not count as filing

`discussion_start()` and `filed_titles()` read a part with a `thought_id` as a filed thought. A confirmed status part has one, but it filed nothing. Counted, it would move the start of the next proposal's raw text past the discussion before it, make the offer before `/compact` and archive find "nothing said since the last saved proposal" and skip that discussion, and list the marked task in `FILED_NOTE` as filed from this conversation. Example: a user talks through a podcast idea, then says "I called the plumber" and confirms only the status card; `/compact` would offer nothing, and the idea would be lost.

So only parts that filed or added to a thought, those with a `thought_id` and no `mark`, count as saved for `discussion_start()` and `filed_titles()`, and for any helper `thought-appending` adds in their place for the offer. Confirm and the card still read `thought_id` on every part (decision 7); the held proposal leaves status parts out (decision 9). The `thought-filing` delta states the rule as its own requirement, so the raw-text requirement in the main spec and the offer requirement that `thought-appending` modifies keep their text.

The next proposal's raw text then includes "I called the plumber". That is the user's own words in the discussion, and the cost of keeping the idea.

**Alternatives:** count it as saved, as any part (rejected: the example above); store a confirmed status part without `thought_id` (rejected: decision 7).

### 9. A status part never holds a proposal

The held proposal exists so that unfiled discussion is not lost and the same conclusion is not proposed twice. An unconfirmed mark loses nothing: the thought exists, the card stays confirmable in the chat, and the sheet's toggle is one click away. Held like any part, a mark would be offered again on every change of topic and before every archive and `/compact`, and the next proposal ("I need oat milk") would replace it and fold its card away unless the model copied the mark into it. A mark on a thought that was later deleted, or marked done in the sheet, would also stay held for good and be re-proposed and refused on every turn.

So `unsaved_parts()` in `app/chat/prompt.py` skips parts with `mark`. Everything that decides what is held reads it:

- `held_parts()`, so a proposal whose only unsaved parts are marks is not held, and the held note never lists a mark.
- `write_proposal()`: the earlier held proposal is marked replaced only when it has an unsaved part that is not a mark. A proposal whose parts are all marks is written and shown, but does not become the held proposal and does not replace one: `conversation.held_proposal_id` stays as it was. Replacing would fold away the held proposal's unfiled parts with nothing to carry them on.
- `offer_proposal()`: returns the held proposal only when it has an unsaved part that is not a mark, and drops every mark from an asked call (decision 6).
- Confirm clears the held proposal when `unsaved_parts()` gives none, so confirming the last new part clears it even when a mark is still unconfirmed.

On the client, `ProposalGroup` keeps a replaced proposal's status cards shown and confirmable; only its other unsaved cards fold away, and the folded count leaves marks out. The offer dialog (`proposal-dialog.tsx`) leaves status parts out: `heldProposalFor()` returns a proposal only when it has an unsaved part with no `mark`, and `onlyUnsaved` hides status cards. So the dialog's text, "This conversation has a thought you can file. Edit it and confirm, or carry on.", stays right: it never shows a status card.

**Alternatives:** hold a mark like any part, and settle one whose thought is deleted or no longer open with a `settled_marks()` query (rejected: more machinery, and a mark the user chose not to confirm is still offered again on every topic change, archive, and `/compact`, and folded away by the next proposal); a mark-only proposal replaces the held one (rejected: the held proposal's unfiled parts fold away with nothing carrying them on); hold it but word the offer dialog for a status change (rejected: it asks again about a change the user already saw and passed over).

### 10. The status card

Each proposal part in the payload (stream event, messages answer, offered proposal) gains `mark` (thought id or null). The `target` lookup from `thought-appending` reads `mark` ids too, in the same query and with the same `Thought.user_id == user.id` filter, so a crafted `mark` with another user's id gets `target: {deleted: true}` and none of that thought's fields.

`ProposalCard` shows a part with `mark` as a small card with no fields:

- Before confirm: "Mark done: <target title>", the category as a badge, and one button, "Mark done". When `target` says deleted: "This thought no longer exists." and no button.
- After confirm: "Marked done: <saved_title>" with the Open link.
- After the thought is deleted: the "Deleted" state from `thought-editing`, "Deleted: <title>" with the title stored in the part, and no Open link. The payload then gives `saved_title: null` and `deleted: true`, so the status card checks `deleted` before it reads `saved_title`, and never renders "Marked done:" with an empty title or a link to a missing thought. This holds live, when `ff:thought-changed` carries `deleted`, and after a reload.
- A 404 on confirm turns the card to "This thought no longer exists."

The group hides the merge button when any part has `mark`, as it does for `add_to`. When a later proposal replaces the group's proposal, its status cards stay shown and confirmable, and only its other unsaved cards fold away (decision 9). The offer dialog shows no status card (decision 9).

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

`thought-dates` added a path with no query when a `dated_*` filter is given: a plain select of the filtered thoughts, no embedding call, no backfill, with a total count. This change takes the same path when `status` or `category` is given and there is no query. The list and its total both read the `filtered` CTE, which is already scoped by `user_id`, never a new plain select of `thoughts`. A search with only `status: open` is a new kind of search that lists every open thought a user has, so a check with a second user's open tasks guards that scope (task 2.1). The order is date order with a `dated_*` filter, as in `thought-dates`, and otherwise `created_at DESC`. The limit is `config.limit`.

The search tool gets `status` (enum `open`, `done`) and `category` (a string; one of the user's categories). `parse_search()` refuses any other status, naming `status`, cleans the category with `clean_name()`, and refuses a call with no query and none of `dated_from`, `dated_to`, `status`, or `category`, naming `query`. A category the user does not have simply matches nothing.

The chat summary of a search with no query names its filters instead of an empty query: `Listed your` then `open` or `done` when a status is given, then `thoughts`, then ` in <category>` when a category is given, for example `Listed your open thoughts in task`; a search with only a date filter says `Listed your thoughts`. A search with a query keeps `Searched your thoughts for “<query>”`.

`format_search_result()` adds ` · done <date>` after the filed date of a done thought, from `status_changed_at`. An open thought gets no mark, so the usual result costs no more tokens. The model sees thoughts in two more places, and each gets the same marker: the seen-thoughts note from `thought-appending`, and the candidate list of a candidate round (`thought-appending` layer 2), which lists candidates by ref, filing date, tags, and summary in its own format. The note is built when the turn starts, so a candidate found during the turn is not in it; without a marker in the candidate list, the model could add a new "buy oat milk" to the done task `Buy oat milk`, where the to-do would stay done and never show in an open-task search or on Upcoming. With the marker, and `thought-appending`'s line that a repeated task is usually new, it files a new task. The note's query and the candidate query read `status` and `status_changed_at` in the queries they already make. The header of a list with no query and no date filter says "newest first". With a status or category filter, the no-match text says no filed thoughts match those filters; a date-only search keeps the `thought-dates` text.

No new index. A list with no query reads the user's rows through `ix_thoughts_user_id_created_at`; at 5,000 thoughts this is well inside the `thought-search` speed budget.

**Alternatives:** an `include_done` flag that defaults to off (rejected: the user asked that search still find done thoughts, and a default that hides them would make "did I buy the milk?" answer "nothing filed"); a status filter with no category filter (rejected: every thought is open by default, so "open" alone lists ideas and notes as well; "open tasks" needs both); a separate `list_thoughts` tool (rejected: `thought-dates` already made the query optional for a filter-only search; a third tool costs tokens on every turn); a candidate-round line "If the user says they finished a candidate task, mark it done instead" (rejected: steering no requirement backs and no probe measures, added to every candidate round; the steering to mark a seen thought, the open-first search, and the done markers already cover it); leave done candidates unmarked (rejected: the oat milk example above, and a mark on a candidate that is already done is refused and costs a round).

### 13. The sheet's Done toggle

In view mode, the row with Edit and Delete gains a native checkbox labelled "Done" (no new dependency; the UI kit has no checkbox). Turning it sends `PATCH {status}` at once, with the box disabled while the request runs. The sheet takes the answer as its thought. A failure puts the box back and shows the server's message in an alert, as the sheet does for an edit. Beside a done box, the sheet shows "Done on <date>" from `status_changed_at`, formatted like the filed and changed dates.

The toggle is hidden in edit mode, so a status change never mixes with an unsaved edit. `thought-editing`'s "A thought opens in a side sheet" says the thought is unchanged when the user chooses neither Edit nor Delete, so this change modifies that requirement: Done joins them, and the sheet shows the status and the done date (decision 15). `updateThought()` dispatches `ff:thought-changed` as it does now; nothing listens for status, and the Upcoming page already reloads when the sheet closes.

**Alternatives:** status as a field in edit mode (rejected: the user asked for a toggle, and "done" is one click, not an edit); a button "Mark done" (rejected: a checkbox shows the state and the action in one control, and reads well to a screen reader).

### 14. The Upcoming page lists only open thoughts

`GET /api/thoughts/upcoming` gains `AND status = 'open'`. `thought-dates`' requirement "The Upcoming page lists dated thoughts from today on" says it lists the user's dated thoughts from today on, done or not, so this change modifies it to say open dated thoughts (decision 15). Nothing else on the page changes: it reloads when the sheet closes, so a thought marked done there drops out, and a thought set back to open comes back.

**Alternatives:** list done thoughts struck through (rejected: the page answers "what is coming up", and a done task is not).

### 15. Spec deltas and archive order

The rule: this change modifies a requirement when its text or one of its scenarios would no longer hold once this change is built, and adds a requirement when the existing text stays true and only gains a case. An open change that modifies the same requirement is not a reason to leave a broken requirement as it is: this change copies that change's version and changes it, and the copy is re-made if that version changes before archive.

Five requirements are MODIFIED:

- `thought-search` "Filters and order" is modified by `thought-dates`, which makes the query optional with a thought-date filter and keeps the scenario "No query and no thought date", which refuses any other search with no query. An ADDED rule beside it would leave that scenario refusing a status-only search. So this change modifies the requirement: its text is `thought-dates`' text with the status and category filters added, the query optional with any of them, newest filed first without a date filter, and only the user's own thoughts listed and counted; its last scenario becomes "No query and no filter". **If `thought-dates`' version of the requirement changes before archive, re-copy it here.**
- `conversation-agent` "A proposal is held while the conversation carries on" says a proposal is held until every part is saved, is offered again on a change of topic, at archive, and at `/compact`, and that a later proposal folds its unsaved cards away. Decision 9 makes status parts an exception to all three. No open change modifies this requirement, so this change does: it adds that a status part does not keep a proposal held, is not offered again, is not folded away, and stays confirmable, that a proposal of only marks does not replace a held one, and that the offer holds no marks, with a scenario for each. **If another change modifies this requirement before archive, merge the two.**
- `thought-detail-view` "A thought opens in a side sheet" is modified by `thought-editing`, whose scenario "No changes from the sheet" says the thought is unchanged when the user chooses neither Edit nor Delete. The Done toggle changes it with neither. So this change copies `thought-editing`'s text and scenarios, adds that the sheet shows whether the thought is done and the date it was marked done, and makes the scenario "does not choose Edit, Delete, or Done". The added requirement "The sheet marks a thought done" keeps the toggle's own rules (decision 13). **If `thought-editing`'s version of the requirement changes before archive, re-copy it here.**
- `upcoming-thoughts` "The Upcoming page lists dated thoughts from today on" is added by `thought-dates` and lists every dated thought from today on. This change copies `thought-dates`' text and scenarios, says it lists the user's open dated thoughts and not a done one, and adds the scenarios "Done task left out", "Marked done from the page", and "Reopened" (decision 14). **If `thought-dates`' version of the requirement changes before archive, re-copy it here.**
- `thought-filing` "A message with several thoughts is split" is modified by `thought-appending`, which lets the user merge all parts before any is saved, except when a part is an addition. This change copies `thought-appending`'s text and scenarios, extends the last sentence to "... is an addition to a filed thought or marks a thought done", adds that a merge confirm naming a status part is refused, and adds the scenarios "Status part and a new thought" and "Merge request". **If `thought-appending`'s version of the requirement changes before archive, re-copy it here.**

Left as ADDED requirements, because the text they sit beside stays true:

- `conversation-agent` "Tools to file and find thoughts" (modified by `thought-appending` and `mcp-connectors`) says a proposal holds parts with a title, summary, tags, and category, and the search tool takes a query. A status part is stored with all four (decision 5), and the search tool still takes a query, which `thought-dates` already made optional with a filter without modifying this requirement. This change's added requirements add marks and the status and category filters.
- `conversation-agent` "The offer before an action may propose nothing" (modified by `thought-appending`) and `thought-filing` "The raw text is kept with the thought" speak of a saved proposal. `thought-filing` "A status change does not count as filing" says what a saved proposal is for them: a status part does not make one (decision 8).
- `thought-filing` "A proposal can add to a filed thought" and `thought-detail-view` "The last addition can be undone" (both from `thought-appending`) refuse a confirm or an undo when "the thought changed". `thought-filing` "A status change does not block an addition" says a status change does not count there, and that neither changes the status (decision 3).

`upcoming-thoughts` exists only once `thought-dates` is archived, "Filters and order" and the Upcoming requirement are copied from `thought-dates`, "A message with several thoughts is split" is copied from `thought-appending`, and marks need `thought-appending`'s refs. So **archive this change after `thought-dates` and `thought-appending`** (and after `thought-editing`, whose sheet requirement it copies). Until `thought-dates` is archived, `openspec validate thought-status --strict` passes with a note that archive would refuse the `upcoming-thoughts` delta, because that spec does not exist yet; that note is expected.

**Alternatives:** leave every requirement an open change modifies as ADDED, and let a later archive fold them together (rejected: an ADDED requirement beside one it contradicts leaves the specs saying two things, such as a sheet scenario that says nothing changes without Edit or Delete, and an Upcoming requirement that lists done thoughts; and this change already modifies "Filters and order", which `thought-dates` modifies, so the rule would not even be applied the same way twice); modify every requirement this change touches (rejected: where the text stays true, a copy only adds a requirement to re-copy when another change edits it). Task group 3 and the end-to-end task 5.1 need `thought-appending` built, and tasks 2.1, 2.2, 4.4, and 5.1 need `thought-dates` built.

## Risks / Trade-offs

- [The model marks the wrong thought done] → The card names the thought by its current title, and nothing changes until the user confirms. The sheet's toggle sets it back.
- [A small model does not search before proposing, and names a ref it has not seen] → The tool result tells it to search first, and the fourth call (decision 11) leaves room to search, propose, and reply. A model that still loops ends with `tool_loop_limit`, as today. The user can still use the sheet.
- [A model says the task was marked done before the user confirms] → `PROPOSAL_SHOWN_STATUS` (decision 5) forbids it, and the status probe counts such replies against a limit.
- [A status change does not move `updated_at`, so a reader that sorts by "last changed" misses it] → `status_changed_at` is in every answer; decision 3 gives the reasons.
- [Every thought is open by default, so "open" alone lists ideas and notes] → The prompt steers the model to add the category `task` for tasks, and the status probe checks it.
- [Four calls per turn instead of three] → One more model call only for a turn that needs it or a model that loops (decision 11).
- [`thought-appending` is not built, and its refs, `target`, layer 1, or `write_proposal()` may change shape] → Re-read decisions 5 to 10 before task group 3.
- [`thought-dates` is not built, and its no-query path, the Upcoming route, "Filters and order", or the Upcoming list requirement may change] → Re-read decisions 12, 14, and 15 before tasks 2.1 and 4.4, and re-copy both modified requirements.
- [`thought-appending` changes "A message with several thoughts is split", or `thought-editing` changes "A thought opens in a side sheet", before this change is archived] → Re-copy the requirement into this change's delta and re-apply this change's edit (decision 15).
- [`background-turns` (planned) runs the turn as a background task] → A status part is a normal proposal part in a normal proposal event; a replay shows it as it shows any card. No change needed.
- [`mcp-connectors` (planned) prefixes connector tool names and has its own round limit] → The built-in `propose_thought` and `search_thoughts` keep their names, and its `connectors.tool_rounds` (5) is already above 4.
- [`mcp-connectors` (planned) moves the search and propose code into `BuiltinTools`, which returns a `ToolOutcome`, and keeps one shared error handler in `_run_tool()`, where connector errors keep their own wording] → This change edits the same places: the `ToolRefusal` pass-through in the except clause, the held note dropped only after a proposal row is written (decision 6), and the choice of `PROPOSAL_SHOWN_STATUS` and of the chat summaries in the propose and search branches (decisions 5, 6, and 12). Whichever change is built second moves the `ToolRefusal` pass-through into the shared handler, before the connector error case, and the result text and summaries into `BuiltinTools`' `ToolOutcome`. Task 3.2's check that a refusal has no suffix, and task 3.4's summary checks, guard the move.

## Migration Plan

1. One Alembic revision adds `status` (`NOT NULL`, server default `'open'`, check constraint `op.f('ck_thoughts_status')`, added in `op.batch_alter_table("thoughts")` so SQLite rebuilds the table; decision 3) and `status_changed_at` (nullable). Every existing thought becomes `open` with no change time. Its `down_revision` is the single head when it is built: run `uv run alembic heads` in `backend/` first. On this branch that is `4d7a1c9e2b60`, but the revisions of `thought-dates` and `thought-appending` come before this one. Downgrade drops the constraint and both columns.
2. Ship the backend and frontend together. An older frontend shows a status part as an empty card, and its confirm would still mark the thought done.
3. Rollback: downgrade and deploy the previous build. Statuses set since are lost; the thoughts stay. Proposals keep status parts in their JSON, which an older build shows as empty cards.
