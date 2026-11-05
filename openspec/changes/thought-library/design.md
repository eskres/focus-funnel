## Context

See `proposal.md` for why. This change sits on top of other changes, and plans against their specs and design.

Built on this branch:

- `thought-editing`: `PATCH` and `DELETE /api/thoughts/{id}`, Edit and Delete in `ThoughtSheet`, and the `ff:thought-changed` window event, which carries `{id, title}` or `{id, deleted: true}` and nothing else.
- `event-category`: `event` is the sixth fixed kind. `FIXED_CATEGORIES` in `lib/thoughts.ts` has six names.

Planned, not built here, and treated as in place:

- `thought-status` (feature 1, planned on this branch): `thoughts.status` (`open` or `done`, `NOT NULL DEFAULT 'open'`, check constraint `ck_thoughts_status`) and `status_changed_at`; a status change never moves `updated_at` or `created_at`; `status` and `status_changed_at` on `GET /api/thoughts/{id}`; the sheet's Done toggle. Its decision 2 says `archived` will be a third value of the same column, added by a later change, and that every list of open thoughts asks for `open` by name. Its decision 12 keeps `search_thoughts(status=...)` generic "so a later page such as the library can list done thoughts".
- `thought-dates`: the five `when` columns and the `when` wire shape (`start`, `end`, `time_zone`); the request zone read once per request into a `ZoneInfo`, with `UTC` for a missing or unknown name (its decision 3); `_as_start()` and `_as_end()` in `search.py` taking that zone; `lib/dates.ts`, which formats `when` without `new Date()` on a date string; and the Upcoming page (`app/app/upcoming/page.tsx`), which mounts its own `ThoughtSheet`, reloads its list when the sheet closes and on the `ff:thought-changed` event, and has a sidebar link "Upcoming" under the sidebar's top button. That design calls the button "New chat"; in `components/chat/sidebar.tsx` it reads "New conversation". `GET /api/thoughts/upcoming` is declared before `/{thought_id}`.
- `thought-appending`: an addition rewrites the summary, tags, category, and raw text of a filed thought, never `created_at`.
- `background-turns`, `mcp-connectors`, `self-hosting-setup`: no overlap (Risks).

What exists on this branch, and matters here:

- `thoughts.created_at` is `server_default=func.now()` and no code path writes it again. `updated_at` moves on every ORM update (`onupdate=func.now()`).
- `ix_thoughts_user_id_created_at` on `(user_id, created_at)` and the GIN index `ix_thoughts_tags` (Postgres only). Thought tests are marked `postgres`.
- `get_thought()` in `store.py` reads one thought with `Thought.user_id == user.id`, so another user's thought is `not_found`. `check_category()` and `clean_name()` in `categories.py`; `clean_tags()` in `store.py` collapses inner spaces, lowercases, drops a leading `#`, trims, and drops empty and repeated tags, then refuses more than `MAX_TAGS` tags or a tag over `MAX_TAG` (50) characters, naming `tags`.
- `owned_by(model, user)` in `app/ownership.py` is the owner filter for list queries (`select(Model).where(owned_by(Model, user))`), tested in `tests/test_ownership.py`.
- Query parameters are typed in the routers that take them: `app/routers/usage.py` has `days: int = Query(default=30, ge=1, le=366)` and `app/routers/settings_models.py` has `model: str = Query(min_length=1)`. A value that fails is answered by `_handle_validation_error` in `app/errors.py`, which names the field by its `loc` with only `body` left out: `query.days: Input should be ...`. `invalid(field, message)` in `store.py` answers `field: ...`. Both are 422 `validation_error` naming the field.
- The backend runs `uvicorn` with its default access log (`backend/Dockerfile` `CMD`), which writes each request's path with its query string. `app/log_masking.py` wraps the log record factory, so a change to a record there reaches every handler. No route so far takes the user's own content in a query string.
- `router = APIRouter(prefix="/api/thoughts")` has `GET`, `PATCH`, and `DELETE` on `/{thought_id}`. No route lists thoughts.
- The search path (`search_thoughts()`) returns a `SearchResult` of hits, capped by `chat.yaml`'s `search.limit` and a size budget, built as text for the model. `thought-dates` and `thought-status` add a no-query path to it that lists filtered thoughts in date or filed order, with a total count and no cursor.
- `lib/thought-link.ts`: `openThought(id)` and `closeThought()` set and clear `?thought=` on the current path with `history.pushState`, and `useOpenThought()` reads it only once the address belongs to the page being rendered. `ThoughtSheet` works on any page that mounts it.
- The Next.js catch-all proxy (`app/api/[...path]/route.ts`) sends every method through one `forward()`, which keeps `new URL(request.url).search` as it arrived. `route.test.ts` checks a query only on a `PUT` (`?x=1&y=two`), never on a `GET` and never percent-encoded; task 2.1 adds that check.
- `ThoughtSheet` is `<Sheet modal={false}>` with `showOverlay={false}`, and its Close button is never disabled, so the page behind it stays visible and usable, and the sheet can close while a `PATCH` is still running. `updateThought()` dispatches `ff:thought-changed` once the `PATCH` answers, even after the sheet has closed. On a 404 the sheet says "This thought no longer exists."
- In demo mode (`AUTH_MODE=demo`), `proxy.ts` `demoRequest()` counts every request, page loads, prefetches, and `/api/*` alike, against `DEMO_RATE_LIMIT` (60 a minute by default, `docs/login.md`), and answers `/api/*` past it with 429 `rate_limited` and the message "Too many requests. Try again in N seconds.", which `apiFetch()` raises as `RateLimitedError`. Without `TRUSTED_PROXY=true`, the documented default, every visitor shares that one limit. `demoPage()` starts a session on the first page request and sends `/` on to `/app`; no page shows a "Log in" button.
- `scripts/search_bench.py` seeds a scratch database with 5,000 thoughts and times the search SQL; it is the check for `thought-search` "Search is fast".
- The app layout (`app/app/layout.tsx`) holds the sidebar and a `main` area; `app/app/[id]/page.tsx` is a conversation. A static segment such as `library` wins over `[id]`.

## Goals / Non-Goals

**Goals:**

- One request per page of the list, owner-scoped, with no provider call.
- "Show more" never repeats or skips a thought, whatever was filed, changed, or deleted in between.
- `archived`, when a later change adds it, joins the status filter with no change to the endpoint's shape or the page's code beyond one list each.
- Reuse the sheet and the Upcoming page's way of opening it and reloading after it closes and after a change is saved.

**Non-Goals:**

- A search box on the page (decision 8).
- Bulk actions: select several, mark done, delete, or change category at once.
- A count of all thoughts or of those that match the filters.
- Sort choices. The list is newest filed first, only.
- A filter on the thought's own date (`when`) (decision 6).
- A "no category" filter, several categories or tags at once, and a filter on a category the user has removed from their settings (decision 6).
- A summary or excerpt in the row. The sheet shows the thought in full.
- Filters in the page address (decision 10).
- Live updates while the sheet is closed: a thought filed in another tab shows when the list is loaded again.
- The `archived` status itself, and whether "Any status" should leave archived thoughts out. That belongs to the change that adds archiving (decision 7).

## Decisions

### 1. A page of its own, opened like the Upcoming page

The Library is `app/app/library/page.tsx`, inside the app layout, so the sidebar stays. A sidebar link "Library" sits under the "New conversation" button, beside "Upcoming". The page mounts its own `ThoughtSheet`, as the Upcoming page does. A row is a button that calls `openThought(id)`, which sets `?thought=<id>` on `/app/library`, so the address names the thought, it can be copied, and Back closes the sheet, with no change to `lib/thought-link.ts`'s address rules.

The list is `<ul aria-label="Thoughts">`; each row's button is named by the thought's title. A row shows the title, the category as a badge, the tags, "Filed <day>", the thought's own date from `lib/dates.ts` when it has `when`, and a "Done" badge when the status is `done`. The filed day is formatted from `created_at` in the browser's zone, as the sheet formats it; it is an instant, not a wall date.

**Alternatives:** a panel inside the chat (rejected: the chat already has the sidebar, the sheet, and the context meter; `thought-dates` decision 8 rejected the same for Upcoming); a tab on the Upcoming page (rejected: two lists with two orders and two filter sets on one page); open a row on a page of its own, `/app/thoughts/<id>` (rejected: the sheet already shows, edits, deletes, and marks done; a second view would drift).

### 2. Newest filed first, with the id as tie-breaker

The order is `created_at DESC, id DESC`. `created_at` never changes: an edit, a status change (`thought-status` decision 3), and an addition (`thought-appending`) leave it alone. So a thought keeps its place whatever happens to it, and a page boundary never moves under the user. The id breaks ties, so two thoughts filed in the same microsecond have one fixed order.

**Alternatives:** last changed first, by `updated_at` (rejected: every edit moves a thought to the top, so a thought edited from the sheet between two pages would be listed twice or not at all, and "Show more" could not be stable); the thought's own date (rejected: most thoughts have none, and Upcoming already lists dated thoughts in date order); title order (rejected: no feature asks for it, and the user thinks of a brain dump in time).

### 3. Keyset paging with an opaque cursor

A page asks for `limit` rows after a cursor. The cursor is the `(created_at, id)` of the last row shown, written as `base64url("<created_at in UTC, isoformat(timespec='microseconds')>|<id>")`, with no padding. The next page is:

```
WHERE user_id = :user_id
  AND <filters>
  AND created_at <= :c
  AND (created_at < :c OR id < :i)
ORDER BY created_at DESC, id DESC
LIMIT :limit + 1
```

The `user_id` term is built with `owned_by(Thought, user)` from `app/ownership.py`, as other list queries build theirs (decision 5). The plain `created_at <= :c` is redundant, and is there so the planner gets a range on `ix_thoughts_user_id_created_at` rather than an `OR` it may not use. The extra row tells whether more exist: when `limit + 1` rows come back, the answer drops the last one and gives the cursor of the `limit`-th as `next_cursor`; otherwise `next_cursor` is null.

Why this is stable:

- A thought filed later has a newer `created_at` than every row shown, so it is never after the cursor. It shows when the list is loaded again from the newest.
- An edit or a status change does not change `created_at` or `id` (decision 2), so the thought stays on its page.
- A delete removes one row and moves nothing. The cursor holds values, not a reference, so it works even when the thought it came from is gone.

A cursor names only a place in the list. It holds no user id and no filter, and it is never looked up as a thought: the query always adds `owned_by(Thought, user)`, so a cursor from another user's list, or a forged one, lists only the requester's own thoughts and tells nothing about anyone else's. The client sends the same filters with each cursor; when a filter changes, it starts again with no cursor (decision 10). `decode_cursor()` refuses a cursor with 422 `validation_error`, message `cursor: not a valid cursor`, when:

- it has a character outside the base64url alphabet (`A-Z`, `a-z`, `0-9`, `-`, `_`), so a cursor with `=` padding is refused;
- it does not decode (`binascii.Error`), or its bytes are not UTF-8 (`UnicodeDecodeError`);
- it is not exactly two parts split on `|` (`<time>` alone, `a|b|c`);
- its time does not parse (`ValueError` from `datetime.fromisoformat()`, also for an empty part), or has no offset;
- its time cannot be converted to UTC (`OverflowError`, for example `0001-01-01T00:00:00+05:00`). The decoder converts it with `astimezone(timezone.utc)` itself, because asyncpg would do the same when it binds the value, and would fail there with a 500;
- its id is not a UUID (`ValueError`).

Every one of these is caught in `decode_cursor()`, so no forged cursor reaches the query.

Postgres keeps `timestamptz` to the microsecond. `isoformat()` leaves out the fraction when the microsecond is 0, so the encoder writes `isoformat(timespec="microseconds")`, and the cursor's time is always written the same way. `fromisoformat()` reads either form, so the cursor's time is the stored time exactly. UUIDs compare the same way in Postgres and in Python.

**Alternatives:** `OFFSET` (rejected: a thought filed or deleted between two pages shifts every later row, so "Show more" repeats one or skips one); a cursor that is the last thought's id, looked up for its `created_at` (rejected: one more query per page, and once that thought is deleted the cursor leads nowhere: answering 404 would break the list, and answering the first page would repeat it); a server-side snapshot of the ids at the first page (rejected: state on the server for every open page, for a list a reload can rebuild); a row comparison `(created_at, id) < (:c, :i)` (rejected: the same rows, but the index ends at `created_at`, and the plain range is the form the planner is sure to use on it; the bench measures that form); a cursor that also holds the filters and refuses a mismatch (rejected: the client already restarts on a filter change, and a mismatch would only give a list that is still owner-scoped and still stable).

### 4. `GET /api/thoughts`

```
GET /api/thoughts?limit=50&cursor=<c>&category=task&tag=home&status=open
                 &filed_from=2026-11-01&filed_to=2026-11-30&time_zone=Europe/Oslo
```

Every parameter is optional. `limit` is 1 to 100, default 50. An empty value of any parameter (`limit=`, `cursor=`, `status=`, `category=`, `tag=`, `filed_from=`, `filed_to=`, `time_zone=`) is read as if it were absent, so `status=&filed_from=` lists every thought and `limit=` gives a page of 50. The answer:

```
{"items": [{"id", "title", "category", "tags", "status", "created_at", "when"}],
 "next_cursor": "<c>" | null}
```

`when` is the `thought-dates` shape or null. An item holds only what a row shows (decision 1). It has no `status_changed_at`, summary, raw text, or origin; the sheet reads those with `GET /api/thoughts/{id}`. The route is `@router.get("")` on the existing router, so it does not meet `/{thought_id}` or `/upcoming`. It uses `get_current_user` and `get_session` only: no settings, no provider client.

In the browser, `listThoughts()` builds the query with `URLSearchParams`, as the rest of `lib/` encodes with `encodeURIComponent`, never by joining strings. The Tag field takes free text: written into the query by hand, a `#home` would start the URL fragment, so the browser would send no tag and every thought would be listed, and a tag such as `home&status=done` would add parameters the user did not choose. Encoded, each is one `tag` value, which the server cleans (decision 6).

The parameters are typed, as `app/routers/usage.py` types `days`, and each is wrapped in one `BeforeValidator` that turns `""` into `None`, the empty-as-absent rule above:

```python
def _empty_as_none(value):
    return None if value == "" else value

Limit = Annotated[Annotated[int, Field(ge=1, le=100)] | None, BeforeValidator(_empty_as_none)]
FiledDay = Annotated[
    Annotated[date, Field(ge=date(1900, 1, 1), le=date(9998, 12, 31))] | None,
    BeforeValidator(_empty_as_none),
]
Text = Annotated[str | None, BeforeValidator(_empty_as_none)]
```

`limit: Annotated[Limit, Query()] = None` (the route uses 50 for `None`), `filed_from` and `filed_to` are `FiledDay`, and `cursor`, `status`, `category`, `tag`, and `time_zone` are `Text`. The bounds sit inside the optional type: `Query(50, ge=1, le=100)` on an optional `int` would hand `None` to the `ge` check, a `TypeError` and a 500, and a plain `int = Query(50, ...)` refuses `limit=` with 422, against the rule above. Both were tried on the backend's FastAPI 0.141 and Pydantic 2.13, as was the form above. Each check is a 422 `validation_error` naming the field:

- `limit` not a whole number from 1 to 100: Pydantic's message, `query.limit: Input should be ...`. Pydantic refuses `abc`, `1.5`, and non-ASCII digits such as `²` and `٥٠` here, never with a 500.
- `filed_from` or `filed_to` not a date, or before 1900-01-01 or after 9998-12-31: `query.filed_from: Input should be ...`. Without the bounds, `filed_to=9999-12-31` overflows in `_as_end()`, which adds a day, and `filed_from=0001-01-01` with `time_zone=Asia/Tokyo` overflows when the local start is turned into UTC; both would be a 500. A native date field lets a user type such a day; the page does not send it (decision 10), and the server still refuses it from a forged request or another client. Within that range no zone's offset can overflow. Pydantic also reads a few other forms as a day, such as `2026-11-01T00:00`; each names one whole day, so it is let through, and the page sends only `YYYY-MM-DD`.
- `status` not in `THOUGHT_STATUSES`: the message of `check_status()` (decision 7), today `status: must be open or done`, raised as `ApiError` with `invalid()`.
- `cursor`: `cursor: not a valid cursor` (decision 3), raised the same way.

The tests check the code and that the message starts with `query.limit: `, `query.filed_from: `, or `query.filed_to: `, not Pydantic's wording after it, which can change with a Pydantic upgrade. `status` and `cursor` messages are the project's own and are checked in full.

A `filed_to` before `filed_from` is not refused; it lists nothing.

The list is owner-scoped by its `WHERE`, so there is no record to answer 404 for: another user's thoughts are simply never in it.

**Filter values and the access log.** This is the first route that puts the user's own words, a tag or a category, in a query string, and uvicorn's default access log writes the query: `GET /api/thoughts?tag=therapy`. Those lines would stay in the operator's logs after "Delete content" or "Delete account". `self-hosting-setup` rejected a token in the URL because "query strings land in access logs". So the request stays a `GET`, and `app/log_masking.py`'s record factory drops the query string from the path of every `uvicorn.access` record, for every route, before any handler sees it: the line reads `GET /api/thoughts HTTP/1.1" 200`. uvicorn's `AccessFormatter` unpacks `record.args` into exactly five values (client address, method, full path, HTTP version, status code), so the factory replaces only `args[2]` with its text before the first `?` and keeps `args` a 5-tuple; it never rewrites the record as `msg, args = text, None`, as `_mask_record()` does for secrets, which would break every access line under uvicorn's formatter. The query is dropped before, and apart from, the secret masking, so it runs whether or not a secret is registered in the context. No route needs its query in the access log. The browser's request to the Next.js proxy carries the same query; the Next.js server writes no access log, and the project ships no reverse proxy. An operator who puts one in front logs what it is set to log, as for every other path.

**Alternatives:** take `limit`, `filed_from`, and `filed_to` as plain strings, match each with an ASCII pattern, parse it, and refuse it with `invalid()` (rejected: a hand-written parser beside the typed `Query` the backend already uses, with its own tests for every digit and date form, where Pydantic already refuses `²`, `1.5`, and `abc` with a 422; the cost is a `query.` prefix on three fields, which still names the field); check `limit` with `str.isdigit()` and `int()` (rejected: `'²'.isdigit()` is true and `int('²')` raises `ValueError`, a 500); a range check for the filed days in the route with `invalid()` (rejected: the type carries its bounds, as `limit` carries 1 to 100, so there is one place for each rule); refuse an empty parameter (rejected: `time_zone=` is already read as absent, a form that clears a field sends `name=`, and two answers for one empty value would be a trap); a plain `int = Query(50, ge=1, le=100)` (rejected: it refuses `limit=`); drop the query in the access record by rewriting `msg` and clearing `args` (rejected: uvicorn's formatter needs the five arguments); dropping `query` from `loc` in the shared handler (rejected: it changes the messages of other routes); a `POST /api/thoughts/search` with a JSON body (rejected: a read with a handful of flat filters is a `GET`, the proxy already forwards query strings, and the access log is handled above); accept the query in the access log (rejected: a tag is the user's content, and it would outlive a delete); `--no-access-log` (rejected: the operator loses every request line, not only the query); a total count in the answer (rejected: a `count(*)` per filter change on a large store, for a number no requirement asks for; "Show more" is offered while `next_cursor` is set); a fixed page size with no `limit` (rejected: the page reload of decision 9 asks for up to 100 at a time and for exactly the rows still missing in its last request, and tests are cheaper with small pages).

### 5. A plain select in `app/thoughts/library.py`, on the existing index

`list_thoughts(session, user, *, limit, cursor, category, tag, status, filed_from, filed_to, zone)` builds one ORM `select(Thought).where(owned_by(Thought, user))`, the owner filter every list query uses (`app/ownership.py`), with only the columns a row needs (`load_only`: `id`, `title`, `category`, `tags`, `status`, `created_at`, and the five `when` columns), the filters of decision 6, the cursor of decision 3, and the order of decision 2. A column left out of `load_only` and read for the answer would lazy-load on the async session and raise `MissingGreenlet`, a 500 that shows only for a dated, timed, or done thought, so task 1.3 checks each item's values against `GET /api/thoughts/{id}`, not only its keys. It reads `search_tsv` and the embeddings never, makes no provider call, and needs no search index row, so it works for a user with no key and for one whose index needs a rebuild.

It uses `ix_thoughts_user_id_created_at`: the planner scans the user's rows backwards from the cursor and stops after `limit + 1` that pass the filters. Ties on `created_at` are sorted on `id` in memory, which is cheap because ties are rare. A tag filter is `tags @> ARRAY[:tag]`, which can use `ix_thoughts_tags`. No new index, so no migration.

The worst case is a filter that few thoughts pass, such as a rare tag on a user whose matching thoughts are all old: the scan reads many rows to fill one page. At 5,000 thoughts per user that is one scan of 5,000 index entries. `scripts/library_bench.py`, built on `search_bench.py`'s scratch database and seeding, holds the list to `thought-search`'s budget: 50 ms at the 95th percentile for the database part, for the first page, the last page, and each filter (task 1.5). It seeds that worst case on purpose rather than leaving it to random seeding: a rare tag on only the 5 oldest thoughts, and a `status=done` run where only the oldest 1% are done. It prints each case's row count, so the reader sees the scan went to the end.

**Alternatives:** reuse `search_thoughts()`'s no-query path (rejected: it is capped by `search.limit` and a size budget for the model's context, counts every match, has no cursor, and its date-filter order is by the thought's date, not filed time); a new index on `(user_id, created_at, id)` (rejected for now: it replaces one that already serves the order, needs a migration, and the bench decides whether it is needed; Risks); a partial index per status (rejected: `thought-status` adds none for its open lists either, and the bench covers it).

### 6. Filters: one category, one tag, and filed days

All filters are `AND`ed, and each is skipped when absent. An empty parameter is absent (decision 4).

- `category`: cleaned with `clean_name()`, matched exactly. A category that is empty after cleaning is skipped. It is not checked against the user's categories: a category the user removed from settings stays on its thoughts (`thought-filing` "The user can add categories"), and a request for it lists them. The page offers "Any category" and the user's categories from `useCategories()`, which reads the `CategoriesProvider` the app layout (`app/app/layout.tsx`) already wraps every page in; outside a provider it falls back to `FIXED_CATEGORIES`, so task 2.3 checks the options inside one, with an added category. A removed category is not offered, as on a proposal card.
- `tag`: cleaned by a new `clean_tag()` in `store.py`, matched with `tags @> ARRAY[:tag]`. One tag. `clean_tag()` is the per-tag part of `clean_tags()`, moved out: inner spaces collapsed, lowercased, a leading `#` dropped, trimmed. It has no length check, and `clean_tags()` calls it and keeps its own count and length checks for stored tags. A filter tag goes through `clean_tag()` only, so a tag over 50 characters, which no thought can carry, lists nothing rather than being refused naming `tags`. A tag that is empty after cleaning, such as `   ` or `#`, is skipped like an absent one. The page has a text field "Tag", applied on Enter or when the field loses focus, and only when its text, trimmed, differs from the tag already applied. Otherwise nothing is requested and the rows stay, so tabbing through the filter bar or clicking from the field to a row keeps the user's place. The page compares trimmed text, not cleaned text, so the cleaning rules stay in `clean_tag()` alone; ` #Home` after `home` asks once more and gets the same list.
- A tag or category that still holds `\x00` after cleaning matches nothing: Postgres `text` cannot hold U+0000, so no stored thought carries it, and sent as a bound parameter it makes asyncpg raise `invalid byte sequence for encoding "UTF8": 0x00`. That would answer 500 `internal_error` and log the SQL error with its parameters, the user's filter value among them. So `list_thoughts()` returns `{items: [], next_cursor: null}` without running the query. `str.split()` does not split on `\x00`, so neither `clean_tag()` nor `clean_name()` removes it.
- `filed_from`, `filed_to`: local days. `filed_from` is `created_at >= _as_start(filed_from, zone)`; `filed_to` is `created_at < _as_end(filed_to, zone)`, both from `thought-dates`, with the request zone (`time_zone`). A name is looked up with `ZoneInfo` only when it is in `zoneinfo.available_timezones()`, read once into a frozenset at import; every other name is read as `UTC` without calling `ZoneInfo`. `ZoneInfo` fails on a forged name in more ways than one exception type covers: on the backend's Python 3.14 with `tzdata`, `Mars/Base` raises `ZoneInfoNotFoundError`, an empty name, an absolute path such as `/etc/localtime`, a name with `..`, or one with `\x00` raise `ValueError`, 256 `a` characters raise `OSError` (file name too long, from the `tzdata` lookup), and `"a/"*300 + "x"` raises `RecursionError`. `thought-dates` decision 3 says `UTC` for a missing or unknown name; if its helper is not built this way, task 1.3 changes it to the set lookup, so a forged `time_zone` is never a 500. The page sends `time_zone` from `lib/time-zone.ts` and has two native date fields, "Filed from" and "Filed to" (decision 10).
- `status`: decision 7.

**The date filter is on the filed date, not the thought's own date.** The list is in filed order, and every thought has a filed date; a filed-day range cuts the list into a slice of the same order. Most thoughts have no `when`, so a `when` filter would hide nearly everything, and a dated thought already has the Upcoming page (from today on) and the chat's `dated_from`/`dated_to` search (any days). A later change can add `dated_from`/`dated_to` here with `thought-dates`' overlap test; a filter does not change the order or the cursor, so paging needs nothing new.

**Alternatives:** filter by `when` (rejected: above); catch the exceptions `ZoneInfo` raises, one type at a time (rejected: `OSError` and `RecursionError` were found only by trying, and the next Python or `tzdata` may raise another; a set lookup never reaches the file system with a forged name); catch every `Exception` around `ZoneInfo` (rejected: `RecursionError` still costs a deep recursion per request, and a broad catch hides real faults); both date ranges (rejected: two pairs of date fields on a small filter bar, for a case search already answers); several tags or categories at once (rejected: a multi-select for each, with "any" or "all" to decide; one of each covers "my open tasks" and "everything tagged home"); refuse a category the user does not have (rejected: a removed category could no longer be listed, and an unknown name simply matches nothing, as in `thought-status` decision 12); a tag picker fed by the user's tags (rejected: a new endpoint for a list `known_tags()` caps for the model); clean the filter tag with `clean_tags([tag])` (rejected: it refuses a tag over 50 characters naming `tags`, a field the request does not have, where the spec says an unknown tag lists nothing); click a tag in a row to filter by it (rejected: the row is one button that opens the sheet, and a button inside it is not allowed); refuse a tag or category with `\x00` (rejected: the spec says an unknown value lists nothing and is not refused); strip `\x00` and search for the rest (rejected: `a\x00b` would then match `ab`, a tag the user did not ask for); apply the tag on every Enter and blur (rejected: each blur would start the list again and lose the user's place); compare the cleaned tag in the browser (rejected: the cleaning rules would be written twice).

### 7. The status filter, and `archived` later

`app/models/thought.py` gets `THOUGHT_STATUSES = ("open", "done")` beside the check constraint `thought-status` adds. The constraint stays as `thought-status` writes it, `CheckConstraint("status IN ('open', 'done')", name="status")`; a test checks that the tuple equals the constraint's values (task 1.1), which keeps the two in step. Building the constraint's text from the tuple would save nothing, since the archiving change widens the constraint in its own migration anyway, and it would reach into another change's model and risk an `alembic check` difference.

`store.py` gets `check_status(value)`, which returns the value when it is in `THOUGHT_STATUSES` and otherwise raises `invalid("status", ...)` with one message built from the tuple: the values joined with commas and a last `or`, so today `status: must be open or done`, the message `thought-status` decision 4 already gives. `set_status()` calls it in place of its own check, and `ThoughtPatch.status` stays a plain string that `set_status()` checks; if `thought-status` was built with a `Literal`, task 1.1 replaces it. The list's `status` is checked with the same function. So there is one list of statuses and one message in the backend. With no `status`, the list holds every status.

`lib/thoughts.ts` gets `THOUGHT_STATUSES = ["open", "done"] as const`, `type ThoughtStatus = (typeof THOUGHT_STATUSES)[number]`, used for `Thought.status` and the row's `status`, and `STATUS_LABELS: Record<ThoughtStatus, string>` (`Open`, `Done`), so a status added to the list without a label fails `tsc`. The page's status select is "Any status" and then one option per entry, built from that list, never written out by hand.

So the change that adds `archived` adds it to the two tuples, the constraint (its own migration, `thought-status` decision 2), and the labels, and the filter takes it with no other change: the endpoint's `status` stays one value, the select gets one option, and the row shows "Archived" from the same label map. Whether "Any status" should then leave archived thoughts out, as most lists do with archived things, is that change's decision; it is a default of the page, not a shape of the endpoint, and nothing here assumes either answer.

A row shows a "Done" badge for `done`. An open thought shows no badge, so a page of ideas and notes, which are all open, carries no noise. Any status other than `open` shows its label, keyed on "not open", as `thought-status` decision 2 keys its marker, so an archived thought will show "Archived" and not look open.

**Alternatives:** default to "Open" (rejected: the page is "my thoughts", and a done task should be listed without a filter; nearly every thought is open anyway); a boolean `done` filter (rejected: the third value would need a new parameter); a list of statuses, `status=open&status=done` (rejected: no requirement asks to combine two, and one value is a select, not a set of checkboxes); read the statuses from the server (rejected: a new endpoint for two names that change once); a second message for the list, `status: must be one of open, done` (rejected: two messages for one rule, from two lists); build the constraint's text from the tuple (rejected: above).

### 8. No search box

The page has filters and no text search. A real search box would be the chat's search: meaning and words, which costs an embedding call, ranks by relevance, and has no stable order to page by. A words-only filter on `search_tsv`, ordered newest first, would be a few lines of SQL, but it would answer differently from the chat's search for the same words (no meaning, no weak-match cut-off), so the user would get two answers to one question. It is not trivial in what it promises, so it is left out. "Find the thought about X" stays a chat question, and the chat's sources open the same sheet.

**Alternatives:** a words-only filter (rejected: above); call `search_thoughts()` from the page (rejected: the feature forbids embedding calls here, and relevance order cannot page with a keyset).

### 9. When the sheet closes, the shown rows are loaded again

The Upcoming page reloads its list when the sheet closes. The Library does the same, extended to paging: it loads again from the newest, with the same filters, up to as many rows as it showed before, and then replaces the rows and the cursor in one state update.

The target is `max(rows shown, 50)`, so a close before the first page arrived (a sheet opened from a copied address) loads one page of 50. Each request asks for `limit = min(100, target - loaded)`, with the previous answer's `next_cursor`, and the loop stops when it has `target` rows or `next_cursor` is null. So 50 shown asks once with `limit: 50`; 100 shown asks once with `limit: 100`; 120 shown asks `limit: 100` and then `limit: 20`. The last answer ends at the right row, and its `next_cursor` is the right cursor for "Show more". The client cannot load more and cut the list back, because the cursor is opaque and only the server can make one for a row in the middle.

The reload follows the page state of decision 10:

- It takes a new generation number, as a filter change does. An answer for an older generation is dropped, so a reload answer that comes back after the filter changed is dropped, and so is a "Show more" answer that comes back after the reload started.
- "Show more" is disabled while a reload runs, as while any request runs.
- If any request of the reload fails, the old rows and cursor stay, and the alert shows the server's message with "Try again", which runs the whole reload again from the newest. The user keeps their place: an edited thought shows its change in the same spot, a deleted one is gone, one that no longer passes the filters (marked done under "Open", given another category) is gone, and the rows after it move up by one. A thought filed elsewhere meanwhile shows at the top. The rows keep their React keys (ids), so the browser keeps the scroll position.

The Library page has its own close effect, as the Upcoming page has: a small effect in `components/library/thought-library.tsx` that keeps the last value of `useOpenThought()` in a ref and starts the reload when it goes from an id to null, not on open, not on the first render, and not when the user clicks a second row while the sheet is open (the id goes from one thought to another, never to null). The Upcoming page and its tests are not changed, and `lib/thought-link.ts` gets nothing new.

The reload runs on every close, also after a close with no change, as on the Upcoming page. It also runs, with a new generation, on `ff:thought-changed`, as the Upcoming page does. The sheet is not modal (Context), so the list is in view beside it, and the user can close the sheet while an edit's Save or the Done toggle is still sending its `PATCH`. The close reload's `GET` can then reach the backend before the `PATCH` commits: the row keeps its old title, or a task just marked done stays under "Open", and without the event nothing would load the list again until the next close. `updateThought()` dispatches the event once the `PATCH` has answered, also after the sheet has closed, so the reload it starts sees the change. The event carries only the title or `deleted`, not the status, category, or tags the filters need, so the page does not patch the row from it; it reloads. A delete from the sheet dispatches the event and then closes the sheet, so two reloads start one after the other; the first is an older generation and its answers are dropped.

A row can outlive its thought: deleted in another tab, from the chat, or by the end of a demo session's data. Clicking it opens the sheet, which says "This thought no longer exists." on the 404 and dispatches nothing. The close reload then lists without it. The Library page shows no alert for it: the sheet already said what happened, and the page's own requests did not fail.

**Alternatives:** load only the first page again (rejected: a user 300 rows down loses their place on every close); patch the one row from `GET /api/thoughts/{id}` and test the filters in the browser (rejected: the filter rules, including local filed days, would be written twice, once in SQL and once in TypeScript); patch the row from `ff:thought-changed` (rejected: above); reload only on close, not on the event (rejected: a close while a `PATCH` runs leaves the list stale, above); reload only on the event, not on close (rejected: a thought deleted elsewhere, or changed in another tab, dispatches nothing here); disable Close while a save runs (rejected: it changes the shared sheet, and Back and Escape close it too); re-fetch only the page the row was on with its starting cursor (rejected: when a row leaves that page, the first row of the next page moves into it, and the two loaded pages then overlap); a shared hook, `useSheetClosed(callback)` in `lib/thought-link.ts`, used by this page and the Upcoming page (rejected for now: the feature asks to reuse the Upcoming page's pattern, not to rework that page; `thought-dates` is planned and not built on this branch, so the change would edit a page it cannot see and re-test its `ff:thought-changed` listener; a later clean-up can move both effects into one hook once both pages exist); load 100 at a time until at least as many rows as before (rejected: 50 shown becomes 100 after a close, against "as many as were shown before", and the extra rows cannot be cut off, since their cursor is not the client's to make); keep the rows that loaded before a failure (rejected: a part list with a cursor from its middle is a state no other path makes).

### 10. Page state

The filters, the rows, and the cursor live in the page's React state, not in the address. Changing a filter clears the rows and the cursor and loads the first page. Each request carries a generation number; a filter change and a reload after the sheet closes (decision 9) each take a new one, and an answer for an older generation, such as a "Show more" that returns after the filter changed, is dropped. "Show more" is a button under the list, disabled while a request runs; it is not infinite scroll, which is harder to reach by keyboard and to test. "Show more" sends the filters in force with the cursor, never the cursor alone. A failed request shows the server's message in an alert with a "Try again" button that repeats it; an `UnauthenticatedError` redirects to login, as the sheet does.

The generation rule covers failures as well as answers: a failure for an older generation is dropped like a success, so it shows no alert. The alert is cleared when a newer request is sent, so a stale message never sits over a good list.

The date fields carry `min="1900-01-01"` and `max="9998-12-31"`, the range of decision 4. A native date field reports a value while the user types the year one key at a time (`0002-11-01`, `0020-11-01`, `0202-11-01`, then `2026-11-01`), and `min` and `max` do not stop it. So a value outside that range is not applied: the previous filter stays and no request is sent. Only `2026-11-01` asks for a list. An emptied field clears that end of the range and lists again from the newest, with no `filed_from` (or `filed_to`) and no cursor. Emptying a field that was already empty asks nothing, as the Tag field does with its applied text.

**Alternatives:** filters in the address (rejected for now: `lib/thought-link.ts` rewrites the address on every open and close, and would have to carry the filters through; a refresh losing the filters is a small cost); infinite scroll (rejected: above); apply a date on blur only (rejected: picking a day from the calendar should apply it at once, and the range check already drops partial years); send every value and let the server refuse it (rejected: three requests bound to fail, and three alerts, while a year is typed); debounce the date fields (rejected: a pause in typing still sends a partial year).

### 11. Spec deltas and archive order

This change adds one capability, `thought-library`, and modifies none. The rule `thought-status` decision 15 states: modify a requirement when its text or a scenario would no longer hold once this change is built. None would:

- `thought-detail-view` "A thought opens in a side sheet" speaks of a sheet over the chat, and "An open thought has its own address" of a conversation. Both stay true for the chat. The Upcoming page (`thought-dates`) opens the same sheet over another page and states that in its own capability ("An upcoming item opens the thought", "as in a conversation"), without modifying `thought-detail-view`. The Library does the same in "A library row opens the thought", so there is one way of doing it, and this change does not copy `thought-status`' version of the sheet requirement only to add a page name.
- `thought-search` is untouched: the list is not a search.
- `conversations` "The sidebar lists conversations" stays true with one more link above the list, as it did for "Upcoming".

The `thought-library` spec relies on `thought-status`' status values and Done toggle, and `thought-dates`' `when` and local days. So **archive this change after `thought-dates` and `thought-status`** (and so after `thought-editing`, which both follow). Nothing in another change's specs needs to be re-copied here.

**Alternatives:** modify "A thought opens in a side sheet" to name the Library and Upcoming pages (rejected: it would copy `thought-status`' modified version, to be re-copied whenever that one changes, for a sentence that is not wrong; and `upcoming-thoughts` did not); put the list endpoint under `thought-store` (rejected: the page and its endpoint are one behaviour, as `upcoming-thoughts` is).

## Risks / Trade-offs

- [`thought-status` is not built, or its column or the `archived` plan changes] → Task 1.1 waits for it. Re-read decision 7 before starting; if `thought-status` already defines a tuple of statuses or a status check, use them and do not add a second. Task 1.1 moves `set_status()`'s check onto `check_status()` with the same message, so `thought-status`' own tests pass unchanged.
- [`thought-dates` is not built: no `when`, no zone helper, no `lib/dates.ts`, no Upcoming page] → Task 1.1's filed-day filter needs the zone-aware `_as_start()`/`_as_end()`; the row's date needs `when`. Re-read decision 6 before task 1.1. The Library's close effect does not depend on the Upcoming page (decision 9).
- [A filter few thoughts pass makes the scan read many rows] → The bench (task 1.5) measures each filter at 5,000 thoughts. If one misses the budget, the fix is a `(user_id, created_at, id)` index in its own revision, with no change to the endpoint or the specs.
- [Tags and category names in the query string reach the access log, and outlive a delete] → The record factory drops the query from every `uvicorn.access` line (decision 4), checked by task 1.3. A reverse proxy the operator adds logs what it is set to log.
- [A forged cursor or an extreme filed day overflows when turned into UTC] → Caught in `decode_cursor()` and refused by the day range of decision 4, both as 422; task 1.2 and 1.3 check each.
- [A forged query value reaches a parser or the database in a form it fails on: a day that overflows when turned into UTC, a `time_zone` `ZoneInfo` fails on (`ZoneInfoNotFoundError`, `ValueError`, `OSError` for a very long name, `RecursionError` for a deeply nested one), or `\x00` in a tag or category] → Each is a 500 that logs the request's values. The typed parameters and day bounds of decision 4, the zone lookup of decision 6 (only a name in `zoneinfo.available_timezones()` reaches `ZoneInfo`; every other name is `UTC`, whatever `ZoneInfo` would have raised), and the empty answer for `\x00` of decision 6 turn each into a 422 or a 200; task 1.3 checks each with no `internal_error` logged.
- [Loading the shown rows again on each close and each `ff:thought-changed` costs one request per 100 rows] → 1,000 rows shown is ten indexed requests, only when the sheet closes or a change is saved. A user who never opens a row pays nothing.
- [Demo mode counts every request against `DEMO_RATE_LIMIT`, and the reload multiplies them] → Each list request, including each step of a reload (`ceil(rows shown / 100)` requests, twice for a delete from the sheet), counts against the limit (60 a minute by default), which every visitor shares without `TRUSTED_PROXY=true`. When the Next.js proxy answers 429 `rate_limited`, the reload keeps the old rows and cursor and shows the server's message, "Too many requests. Try again in N seconds."; it does not redirect to login. "Try again" runs the whole reload again, so it is no cheaper. Accepted: a demo user has few thoughts, so a reload is one request; task 2.4 checks the 429 path, and task 3.1 raises the limit for its walkthrough.
- [A thought filed in another tab shows at the top after the next close, and the rows below move down by one] → Accepted: the list is what a fresh load would show. Paging between two "Show more" clicks is still stable.
- [A category the user removed cannot be picked in the filter] → Accepted (Non-Goals); its thoughts are still listed with no filter and with every other filter.
- [`created_at` ties on SQLite, which keeps whole seconds] → The id tie-break keeps the order fixed; the thought tests run on Postgres (`pytest -m postgres`), as all thought tests do.
- [`background-turns` (planned) lets a turn run on when the user leaves the chat] → Going to the Library is leaving the chat; that change already covers it. A thought confirmed meanwhile shows at the top on the next load.
- [`mcp-connectors`, `thought-appending`, `self-hosting-setup`] → No shared code. An addition from `thought-appending` changes a row's fields, not its place (decision 2).

## Migration Plan

1. No migration: the list reads existing columns and the existing index. `THOUGHT_STATUSES` is a Python tuple beside `thought-status`' check constraint, which is not changed, so `alembic check` stays clean.
2. Backend and frontend can ship apart: an old frontend never calls `GET /api/thoughts`, and a new frontend on an old backend gets an error answer on that path, which the page shows in its alert.
3. Rollback: deploy the previous build. Nothing is stored by this change.
