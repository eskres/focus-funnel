## Context

See `proposal.md` for why. What exists on `main` (2d091e1) and shapes the approach:

- `thoughts` has one `category` column and no date. `created_at` is the filing time. Alembic head is `8a4d6f2b9c13`.
- `system_prompt(today)` in `app/chat/prompt.py` adds "Today is <weekday> <date>" from `datetime.now(UTC).date()`. `build_context()` calls it from three places: the turn (`routers/chat.py`), the offer before archive and `/compact` (`chat/proposal.py`, reached through `POST /api/conversations/{id}/proposal`), and the context meter (`routers/conversations.py`). No request carries a time zone.
- `search_thoughts()` turns `since` and `until` into UTC midnights (`_as_start`, `_as_end`). The query is required, and every hit must pass a similarity or word-share cut-off, so a search cannot list "everything this week".
- `parse_proposal()` reads parts into `ProposalPart(title, summary, tags, category)`, stored as JSON in `proposals.parts`. Confirm (`ConfirmIn`) takes the card's fields and calls `store_thought()`.
- `ThoughtSheet` is mounted in `components/chat/chat.tsx` and opens from `?thought=<id>` (`lib/thought-link.ts`). The app layout has a sidebar and a Settings link.
- `thought-editing` (planned, not built) adds `PATCH /api/thoughts/{id}` with a closed field list, and Edit mode in `ThoughtSheet`. It also modifies the `thought-detail-view` side-sheet requirement and the `chat-interface` card requirement.
- `mcp-connectors` and `thought-appending` both modify the `conversation-agent` requirement "Tools to file and find thoughts".
- `event-category` (branch `event-category-planning`, not merged) adds a data-only Alembic revision on `8a4d6f2b9c13`.

## Goals / Non-Goals

**Goals:**

- One date shape, `when`, used the same way by the tool, the proposal part, confirm, `GET`, `PATCH`, and the Upcoming list.
- A date change never costs an embedding call.
- No date arithmetic in the browser's own zone on a stored date: a stored date shows as written.

**Non-Goals:**

- Repeating dates ("every Monday").
- Reminders, notifications, or calendar export. The stored zone keeps them possible later.
- A calendar or week view. The Upcoming page is a list.
- Past dated thoughts on the Upcoming page. Search finds them ("what did I have last week").
- Showing the date in the sources list under an answer. It stays the record of what the answer read.
- Converting a date when the user's zone changes. A date set in Oslo still shows 19:00 in Tokyo.

## Decisions

### 1. Store wall time plus the zone, not UTC

Five nullable columns on `thoughts`: `starts_on DATE`, `starts_at TIME`, `ends_on DATE`, `ends_at TIME`, `time_zone TEXT`. A null `starts_at` means a day with no time. All are null for a thought with no date. One Postgres index, `(user_id, starts_on) WHERE starts_on IS NOT NULL`, serves both the range filter and the Upcoming list.

"Call the plumber on Monday" is a calendar day, not an instant. In UTC it would need a fake midnight, and a user west of UTC would see Sunday. Wall time keeps the user's words. Range filters compare days directly, with no zone sums in SQL. The zone is kept so a later reminder or export can turn a timed date into an instant.

**Alternatives:** a `timestamptz` start and end plus an "all day" flag (rejected: all-day dates shift by zone, and every read needs the zone to show the day); one JSON column (rejected: no index on the date, and the Upcoming query and the range filter both need one).

### 2. One wire shape: `when`

```
"when": {"start": "2026-10-02T19:00", "end": null, "time_zone": "Europe/Oslo"}
```

`start` and `end` are `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`, no seconds, no offset. `when` is `null` for no date. One parser in `app/thoughts/dates.py` turns `when` into the five column values and back, and applies the checks in the `thought-store` spec (start needed, both or neither have a time, end not before start). `store_thought()` and `update_thought()` call it and refuse with `validation_error` naming `when`. An unknown or missing zone is stored as `UTC` (checked with `zoneinfo.ZoneInfo`).

Where each piece comes from:

| Place | `start`/`end` from | `time_zone` from |
|---|---|---|
| `propose_thought` part | the model | the turn's zone (decision 3), added by the server |
| `proposals.parts[*].when` | the parsed part | as above |
| Confirm body | the card | the browser, at confirm |
| `PATCH` body (with `thought-editing`) | the sheet | the browser, at save |
| `GET` answer, Upcoming items | stored | stored |

The tool schema has `when` with `start` and `end` only; the model never names a zone. `parse_proposal()` drops a part's `when` that fails the check and keeps the rest (spec: "Not valid from the model"), as it already drops an unknown category.

**Two choices for an ambiguous day.** A part can give `when_choices` instead of `when`: a list of exactly two `{start, end}` objects. It is stored on the part and sent to the card the same way, each choice stamped with the zone. `parse_proposal()` applies these rules in order:

1. When the part has both, `when_choices` wins and `when` is dropped. The model flagged the day as unclear, and a single date would hide that.
2. A choice that fails the check is dropped.
3. One valid choice left becomes `when`. None left means no date.
4. More than two choices: the first two are kept.

Confirm needs to know whether the user picked. In `ConfirmIn`, a missing `when` key is different from `"when": null`: null means "No date", and a missing key means no pick. Confirm reads this with `model_fields_set`. For a part with `when_choices`, a missing `when` gives 422 `validation_error` naming `when` ("pick a date"), and nothing is stored. For a part without choices, a missing `when` stores no date, as now. The server does not check that the picked date is one of the two choices. The user can also type another date in the fields.

Merge keeps the first part's `when` or `when_choices`, as it keeps the first part's title and category.

**Alternatives:** separate `start_date`, `start_time`, … fields on the wire (rejected: four fields on every shape, and the model mixes them up more than one ISO string); an offset in the string (rejected: a day with no time has no offset).

### 3. The browser sends its zone; the server reads it per request

`lib/time-zone.ts` returns `Intl.DateTimeFormat().resolvedOptions().timeZone`. It is sent as `time_zone` on:

- `POST /api/chat` (`ChatRequest.time_zone`),
- `POST /api/conversations/{id}/proposal` (a new optional body `{time_zone}`),
- confirm and `PATCH` (inside `when`, decision 2).

The server turns it into a `ZoneInfo` once per request, with `UTC` for a missing or unknown name and no refusal. The turn passes it to `build_context()` (`system_prompt(today)` gets `datetime.now(zone).date()`), to `parse_proposal()` (to stamp `when.time_zone`), and to `search_tool_result()` (decision 4). The context meter keeps UTC: its estimate does not change with the date.

`_as_start` and `_as_end` take the zone, so `since` means the user's local midnight. This fixes "what did I file today" for users far from UTC (spec scenario "Filed since today, in local days").

Add `tzdata` to the backend dependencies. `zoneinfo` falls back to it when the slim image has no system zone files.

**Alternatives:** store the zone on the user (rejected for now: the brief decided per turn; a stored zone goes stale when the user travels, and the browser always knows the current one); refuse an unknown zone (rejected: a chat message must not fail over a date line).

### 4. Search: a thought-date range, and no query needed with it

The search tool gets two optional fields, `dated_from` and `dated_to` (`YYYY-MM-DD`), described as "the days the thought happens on, not the day it was filed". `since` keeps its meaning and name. `query` becomes optional in the schema; `parse_search()` refuses a call with neither a query nor a `dated_*` field, naming `query`.

In `search.py`, the filtered CTE gains:

```
AND (:dated_from IS NULL OR coalesce(ends_on, starts_on) >= :dated_from)
AND (:dated_to   IS NULL OR starts_on <= :dated_to)
```

This is the overlap test; a thought with no date fails both, so it never passes a `dated_*` filter.

With a `dated_*` field and no query, `search_thoughts()` skips the embedding call and the ranking SQL and runs one plain select: the user's thoughts that pass the filters, ordered `starts_on, starts_at NULLS FIRST, created_at`, limited to `config.limit`, with a total count. It does not backfill missing embeddings, since it makes no provider call. With a query, ranking works as now, inside the filter.

`format_search_result()` adds the date to each dated entry, after the filed date: `1. Dinner with Sam · filed 2026-09-28 · on Fri 2026-10-02 19:00`, or `on 2026-11-03 to 2026-11-06`. The header for a date-only search says "date order". The "no match" note for a date-only search says no filed thoughts are dated in those days.

**Alternatives:** reuse `since`/`until` with a "by thought date" flag (rejected: the brief keeps them apart, and a flag is easy for the model to forget); a separate `list_dated_thoughts` tool (rejected: a third tool for one filter; "dinners this month" needs the query and the range together anyway).

### 5. The prompt teaches dates once

`system_prompt()` keeps "Today is <weekday> <date>." in the local zone, and adds "Weeks start on Monday." The `when` description on the part says:

- Give a date only when the thought is about a set date or time.
- Work out weekdays and "tomorrow" from today.
- A weekday means the soonest such day after today.
- Give a time or an end only when the user names one.

The `when_choices` description says: do not guess an unclear day; give two choices instead, and no `when`. It names the two cases from the `conversation-agent` spec, with one example each:

- A weekday that is today's weekday: today, and one week later.
- "Next" with a weekday: the soonest such day after today, and one week after that.

The search tool's description adds: when the user asks what is on, coming up, or planned for a time, pass `dated_from`/`dated_to`, with no query unless they name a subject. `held_proposal_note()` adds a `Date:` line per part, or `Date: <a> or <b> (not picked yet)` for two choices.

The chat never asks about the day before proposing. Under `/push` the proposal tool is forced, so the model cannot ask first. The card is the one place that asks, in `/push` and in explore mode alike.

**Alternatives:** the model asks in the chat and proposes after the answer (rejected: impossible under `/push`, and two behaviours for one rule); the card shows no date and the reply asks (rejected by the user: the card should offer the choices).

### 6. Card and sheet date fields

A small `components/chat/date-fields.tsx` holds the date fields, used by `ProposalCard` and the `ThoughtSheet` edit mode (which `thought-editing` adds). It uses native `<input type="date">` and `<input type="time">`, so no new dependency:

- No date: an "Add date" button.
- A start date, an optional start time, a "Clear" button, and "Add end".
- An end: an end date, and an end time shown only when the start has a time. The end time starts as the start time, so "both or neither" holds without the user thinking about it.

A part with `when_choices` shows the two choices as buttons ("Fri 2 Oct, 19:00", "Fri 9 Oct, 19:00") and a "No date" button, in place of the date fields. A pick fills the fields with that choice, or clears them for "No date". After a pick, the fields work as above, so the user can still adjust the date. Confirm stays disabled until a pick is made or the fields are set, and the card always sends `when` (an object or null) once a pick is made.

The browser does not reject a bad range itself; the server's `validation_error` naming `when` shows as the card's and sheet's existing alert. `lib/dates.ts` formats `when` for display by splitting the string, never through `new Date("2026-10-02")`, which parses as UTC midnight and shows the previous day west of UTC.

The sheet shows the date as its own line ("When: Fri 2 Oct 2026, 19:00"), above the filed and changed dates.

### 7. Editing the date rides on `thought-editing`

`thought-editing`'s `PATCH` body gets an optional `when` (object, or `null` to clear), passed to `update_thought()`. `update_thought()` treats the date like the category: no embedding call, no change to the search entries. Edit mode in the sheet adds the date fields from decision 6.

If `thought-dates` is built before `thought-editing`, tasks 4.x wait; the rest of the change does not depend on it.

**Alternatives:** build a date-only `PATCH` here (rejected: `thought-editing` already designs the endpoint, its errors, and the sheet's edit mode; two edit paths would drift).

### 8. The Upcoming page

`GET /api/thoughts/upcoming?from=YYYY-MM-DD` answers `{items: [{id, title, category, when}], more: bool}`. `from` is the browser's local today; the server does not guess it. The filter is `coalesce(ends_on, starts_on) >= :from`, the order is decision 4's date order, and the limit is 200 (`more` is true when a 201st row exists). The route is declared before `/{thought_id}` so `upcoming` is not parsed as an id. Owner-scoped like every thoughts route.

`app/app/upcoming/page.tsx` sits in the app layout, so the sidebar stays. A sidebar link "Upcoming" sits under "New chat". The page groups items by day (`Today`, `Tomorrow`, then `Monday 5 October`); an item that started before today goes under `Today`. The page mounts its own `ThoughtSheet`; `openThought()` already works on any path, because it only sets `?thought=`. The page reloads the list when the sheet closes, and on the `thought-changed` event from `thought-editing` when it exists.

**Alternatives:** a panel inside the chat (rejected: the chat already has the sidebar, the sheet, and the context meter; a page is one more link and no layout work); show past items under a toggle (rejected for now: past dates are a search question, and it doubles the page's states).

### 9. Spec deltas and other changes' requirements

`mcp-connectors` and `thought-appending` both modify "Tools to file and find thoughts", and `thought-editing` modifies the sheet requirement. This change adds new requirements there instead ("The tools carry dates", "The sheet shows and edits a thought's date", "A proposal can carry a date"), so no two changes rewrite the same block. One wording overlap remains: the base requirement says the search tool "SHALL take a query"; the added requirement makes it optional with a date range. Whichever change archives last should fold the two into one sentence.

The `chat-interface` requirement "A proposal can be reviewed in the chat" lists the card's fields, so it must name the date. A new requirement cannot fix a list in another one, so this change modifies it. `thought-editing` modifies the same requirement. This change's delta is `thought-editing`'s version with "and date" added to the field list and one dated-card scenario. So **`thought-editing` must be archived before `thought-dates`**; archiving in the other order would drop `thought-editing`'s saved-title and deleted-card rules. Task group 4 already depends on `thought-editing`, so the order costs nothing. If `thought-editing`'s delta changes before it is archived, copy the new version into this delta again.

### 10. The date index is Postgres only; "today" comes from one clock

The partial index `ix_thoughts_user_id_starts_on` is declared like the GIN indexes: `info=POSTGRES_ONLY` with `ddl_if(dialect="postgresql")`, and the revision creates it only on Postgres. SQLite runs only the rest of the app's tests, where the date queries are small. `alembic check` still passes on both, because `alembic/env.py` leaves Postgres-only indexes out of the SQLite comparison.

`app/thoughts/dates.py` reads the time from one function, `utc_now()`, and `today_in(zone)` turns it into the local date. Tests replace `utc_now()` to fix "today"; no time-freezing dependency is added. A `when` that is not an object or null is refused naming `when`, like a bad start.

**Alternatives:** a partial index on both databases with `sqlite_where`, as `uq_search_indexes_one_active` does (rejected: the design asks for one Postgres index, and nothing on SQLite needs it); `freezegun` (rejected: a new dev dependency for one clock).

### 11. Details of the model's dates, settled while building them

- The system prompt ends "Today is <Weekday> <YYYY-MM-DD>. Weeks start on Monday." The date is the user's local date for the turn and the offer; the context meter and a caller with no zone use the UTC date.
- Every stored part has the keys `when` and `when_choices`, null when unused, so the stream event, the conversation, and the offer answer show one shape. Older stored parts without the keys read as null.
- `parse_proposal()` counts only a non-empty `when_choices` list as choices; null or `[]` leaves `when` to stand. Two choices that are the same date count as one, which then becomes `when`. Any `time_zone` the model writes is ignored; the turn's zone is stamped.
- The held-proposal note gives each part a `Date:` line after `Category:`: `Date: 2026-10-02T19:00`, `Date: 2026-11-03 to 2026-11-06`, `Date: 2026-10-02 or 2026-10-09 (not picked yet)`, or `Date: none`, as `Category: none` does.
- `POST /api/conversations/{id}/proposal` takes an optional body, so an older frontend's empty POST still works (UTC).
- Confirm checks the pick after the already-saved check, so a repeated confirm of a saved part still answers its thought, and before anything is stored: a card whose first part has `when_choices` and whose body has no `when` key gets 422 "when: pick a date, or no date". With a merge, only the first part's choices count, as merge keeps the first part's date.
- The `dates` probe reads the search call's `dated_from`, `dated_to`, and `query` from the raw arguments, so it scores the model's call whether or not `parse_search()` accepts it yet.

**Alternatives:** leave the date keys out of a part with no date (rejected: the conversation's answer model adds them as null anyway, so the event and the conversation would differ); refuse a confirm that picks a date outside the two choices (rejected in decision 2: the fields are the source of truth).

### 12. Details of searching by the thought's date, settled while building them

- Every search result entry now says `filed` before its filing day, so the two dates cannot be confused: `1. Oat milk · filed 2026-09-20 · #groceries`. A dated entry adds `on` and its date after it, before the tags. Both sides of a range carry their weekday, as a single date does (`on Tue 2026-11-03 to Fri 2026-11-06`), so the model can answer "what is on Friday" from either end; an end later the same day gives only its time (`on Mon 2026-10-05 09:30 to 11:00`). Undated entries have no `on` part. The sources under an answer stay as they were.
- A date-only search answers "N of your thoughts are dated in those days (date order):", and "M more are dated in those days. Narrow the days or add tags to see them." when the limit cuts it. With nothing found it answers "No filed thoughts are dated in those days. Say so plainly, and do not answer as if the user had filed something." A search with a query and a date range keeps the usual header and note.
- `parse_search()` refuses neither a query nor a `dated_*` field as "query must be a non-empty string, unless dated_from or dated_to is given". `dated_from` and `dated_to` must be written `YYYY-MM-DD` (checked by pattern first, as `when` is), and `dated_to` before `dated_from` is refused, so the model gets another round instead of an empty result.
- `search_thoughts()` takes `query=None`; an empty or blank query counts as none. Without a query and without a `dated_*` day it raises `validation_error` "query: …", for callers other than the tool. The date-only listing keeps the tag, `since`, and `until` filters, ties on the same start break by filing time, and the hits carry no similarity, rank, or excerpt.
- The chat's tool line for a date-only search reads "Looked up your thoughts dated 2026-09-28 to 2026-10-04" ("from …", "up to …", or "on …" for one side or one day).

**Alternatives:** keep undated headings as they were and add only the `on` part (rejected: an unlabelled filing day next to an `on` date reads as two event dates); a weekday on the single date only, as decision 4's example shows (rejected: a range is just as often asked about by weekday).

### 13. Details of editing the date, settled while building them

- `PATCH /api/thoughts/{id}` takes `when` as `ThoughtPatch` takes the other fields: a missing key keeps the date, `null` clears it, and an object is checked by the same parser as confirm, so a refusal is 422 `validation_error` "when: …" with the thought unchanged. `GET` and `PATCH` answer `when` (`{start, end, time_zone}` or null). A date-only change commits without touching `search_tsv` or the embeddings.
- The sheet sends `when` only when the start or end changed, as it sends only the changed fields; the zone alone never counts as a change. A changed date carries the browser's zone at save, so a date set in Oslo and moved in Tokyo is stored with `Asia/Tokyo`.
- `date-fields.tsx` holds the fields as text (`start`, `startTime`, `end`, `endTime`, `""` for empty) and turns them into `when` only at save. "Add date" starts the start day at the browser's local today, so the fields never hold a date with no start. Setting a start time while an end exists gives the end the same time when it has none; clearing the start time clears the end time, so both or neither have a time. "Add end" starts the end as the start; "Remove end" and "Clear date" undo each.
- The sheet's date line ("When: Fri 2 Oct 2026, 19:00", "When: Tue 3 Nov 2026 – Fri 6 Nov 2026", or "Mon 5 Oct 2026, 09:30 – 11:00" for an end later the same day) sits in the header between the title and the filed and changed dates, and shows the stored date in edit mode too, so a refused save still shows what is stored. `lib/dates.ts` formats it from the string with fixed English weekday and month names; `lib/time-zone.ts` reads the browser's zone. Both were added with task 4.2, ahead of group 5, which uses them.

**Alternatives:** send `when` on every save (rejected: an unchanged field is never sent, so a stale browser zone would overwrite the stored one on any title edit); leave "Add date" with an empty start (rejected: a save would then be refused for a missing start the user never saw as a field to fill).

## Risks / Trade-offs

- [The model gives two choices for a clear day, or one date for an unclear day] → Task 2.5 measures both on the preferred model. A wrong single date still shows on the card, where the user checks it before confirming.
- [The user picks a choice and then types another date] → Accepted: the fields are the source of truth once a pick is made.
- [Small models give bad ISO strings] → The part keeps everything but the date, so the user can still save and add the date on the card. Task 2.5 measures it on the preferred model.
- [`new Date()` on a date string shows the wrong day] → One formatter in `lib/dates.ts`, with a test run under a `TZ` west of UTC.
- [A user who moves zones sees old times as written] → Accepted (non-goal); the stored zone allows a later fix.
- [`thought-editing` lands later or changes its `PATCH`] → Task group 4 is the only part that depends on it; re-read decision 7 before starting it.
- [`background-turns` (planned) runs the turn as a task that outlives the request] → The zone is read once per request and handed to the turn when it is built (decision 3), so the task keeps it. Nothing reads the zone from the request during the turn. A reattach builds no context, and a restart does not resume a turn, so neither needs the zone. `background-turns` needs no change.

## Migration Plan

1. One Alembic revision adds the five nullable columns and the partial index. No backfill: existing thoughts have no date. On top of `8a4d6f2b9c13`; if `event-category` merges first, set `down_revision` to its revision and keep the single-head test passing.
2. Backend and frontend can ship apart. An old frontend sends no zone (UTC, as today) and no `when` (no date stored). A new frontend on an old backend gets no `when` back and shows no date.
3. Rollback: downgrade drops the columns and the index. Dates set since are lost; nothing else is.
