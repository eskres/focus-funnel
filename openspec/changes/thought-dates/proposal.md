## Why

A thought can be about a set date or time: "call the plumber on Monday" is a `task` on Monday, "dinner with Sam Friday at 7" is an `event` on Friday. Today the date lives only in the text, so nothing can list or find thoughts by when they happen. A thought keeps one category; the date is a separate field. (Decided 2026-10-01, instead of several categories per thought.)

## What Changes

- A thought can have a date: a start, and an optional end. Each is a date with an optional time. Any category can have a date. A thought with no date has none.
  - "call the plumber on Monday": start Monday, no time, no end.
  - "dinner Friday at 7": start Friday 19:00, no end.
  - "trip to Oslo 3-6 Nov": start 3 Nov, end 6 Nov.
  - "meeting 10-11 on Tuesday": start Tuesday 10:00, end Tuesday 11:00.
- A date is stored as the user's local date and time (wall time), with the time zone it was set in. It is not turned into UTC.
- `propose_thought` takes an optional date per part. The proposal card shows it, and the user can change or clear it before confirming. Confirm stores it.
- When the day is ambiguous, the model does not guess. A weekday named on that same weekday ("Friday", said on a Friday) and "next <weekday>" each give two date choices. The card shows both as buttons, with "No date", and the user picks one before confirming. This works the same in `/push` and in explore mode.
- Weeks start on Monday, so "this week" runs Monday to Sunday.
- The thought detail sheet shows the date. With the `thought-editing` change, the sheet's Edit also changes or clears the date.
- `search_thoughts` takes a date range that filters by the thought's date, for "what's on this week". It is separate from `since`, which still filters by the day the thought was filed. With a date range, the query is optional: a search with only a range lists the dated thoughts in it, in date order.
- The browser sends its time zone with each chat turn and with each request for an offered proposal (before archive and `/compact`). The model gets the user's local date and weekday instead of the UTC date. `since` and the new range are read as the user's local days.
- A new Upcoming page lists the user's dated thoughts from today on, in date order, grouped by day. A thought that started before today and ends today or later is listed. Past thoughts are not listed. Each item opens the thought.

## Capabilities

### New Capabilities

- `upcoming-thoughts`: the Upcoming page and its endpoint: which dated thoughts it lists, in what order, and how an item opens.

### Modified Capabilities

- `thought-store`: a thought has an optional date; the date fields are checked.
- `thought-filing`: new requirement: a proposal part can carry a date, which the card shows and the user can change or clear before confirming.
- `thought-search`: "Filters and order" gains the date range on the thought's date, date order, and an optional query when a range is given.
- `conversation-agent`: new requirements: the model gets the user's local date, and the two tools carry dates (the date on a proposal part, the date range on a search).
- `thought-detail-view`: new requirement: the sheet shows the date, and its Edit changes or clears it.
- `chat-interface`: "A proposal can be reviewed in the chat" names the date among the card's fields. The delta is built on `thought-editing`'s version of this requirement, so `thought-editing` must be archived first.

## Impact

- Backend: `app/models/thought.py` and one Alembic migration (date columns and an index); `app/thoughts/store.py` (check and write the date); `app/chat/prompt.py` (local date in the system prompt, tool schemas, held-proposal note); `app/chat/tools.py` (parse the date and range, date in the search result); `app/thoughts/search.py` (range filter, date order, search with no query); `app/routers/chat.py` and `app/routers/conversations.py` (time zone on the turn and the offer, date on confirm); `app/routers/thoughts.py` (date in `GET` and `PATCH`, new `GET /api/thoughts/upcoming`). A new `tzdata` dependency, so the slim image knows every IANA zone.
- Frontend: `lib/chat.ts` and `lib/conversations.ts` (send the time zone), `lib/sse.ts` and `lib/thoughts.ts` (the date type), `components/chat/proposal-card.tsx` (date fields), `components/chat/thought-sheet.tsx` (show and edit the date), a new `app/app/upcoming/page.tsx` and a sidebar link.
- API: a `when` object (`start`, `end`, `time_zone`) on proposal parts, confirm, `GET` and `PATCH /api/thoughts/{id}`; `time_zone` on `POST /api/chat` and `POST .../proposal`; new `GET /api/thoughts/upcoming`.
- Cost: none on the user's key. A date-only change makes no embedding call, and a search with only a date range makes none.
- Depends on `thought-editing` (planned, not built) for editing the date in the sheet, and must be archived after it (design decision 9). Shares the Alembic chain with `event-category` (branch `event-category-planning`, not merged): whoever merges second rebases `down_revision` and keeps the single-head test passing.
