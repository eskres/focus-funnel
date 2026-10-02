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
