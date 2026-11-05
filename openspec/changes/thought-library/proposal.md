## Why

A filed thought can be reached only through the chat: a search, a source link, or a saved card. There is no place to see what is filed, to browse it, or to find a done task without asking the model. The user needs a page that lists their thoughts.

## What Changes

- A new Library page, reached from a sidebar link "Library" beside "Upcoming", under "New conversation". It lists the user's thoughts, newest filed first, 50 at a time, with a "Show more" button for the next 50.
- Each row shows the title, the category, the tags, the filed date, the thought's own date when it has one (`when`, from `thought-dates`), and "Done" for a done thought (from `thought-status`).
- Filters: one category, one tag, a status (any, open, or done), and a range of filed days. They work together. Changing a filter starts the list again from the newest. The status choices come from one list in the backend and one in the page, so `archived`, a later third status, joins the filter by being added to each (with the check constraint and the page's labels; design decision 7).
- The date filter is on the filed date, not on the thought's own date (design decision 6). The list is in filed order, and every thought has a filed date; most have no `when`. Dated thoughts already have the Upcoming page and the chat's date search.
- A row opens the thought in the existing side sheet, over the Library page, with the address naming it, as the Upcoming page does. When the sheet closes, and when a change made in it is saved, the rows already shown are loaded again, so an edit, a delete, a status change, or an undone addition (`thought-appending`) shows at once, also when the sheet closed before the change was saved, and the user keeps their place.
- A new endpoint, `GET /api/thoughts`, owner-scoped, pages with a keyset cursor on the filed time and the id. Paging stays stable while thoughts are filed, changed, or deleted: "Show more" never repeats or skips a thought. The endpoint makes no embedding call and no model call, and uses the existing `(user_id, created_at)` index. A tag or category in the query string is kept out of the backend's access log (design decision 4).
- No search box on the page. Search stays in the chat (design decision 8). No bulk actions, no counts, and no sort choices.

## Capabilities

### New Capabilities

- `thought-library`: the Library page and its endpoint: which thoughts it lists, in what order, how it pages, its filters, how a row opens the thought, and that it lists only the owner's thoughts with no provider call.

### Modified Capabilities

None. The sheet is reused as it is, as the Upcoming page reuses it (design decision 11).

## Impact

- Backend: a new `app/thoughts/library.py` (`list_thoughts()`, the cursor); `app/routers/thoughts.py` (`GET /api/thoughts`, with typed query parameters as `app/routers/usage.py` has, and an empty parameter read as absent); `app/models/thought.py` (`THOUGHT_STATUSES`, one tuple beside the status check constraint, which is not changed); `app/thoughts/store.py` (`clean_tag()`, moved out of `clean_tags()`, and `check_status()`, which `set_status()` then uses); `app/log_masking.py` (the query string dropped from access log lines); `thought-dates`' request-zone helper, if it does not already, looks a name up only when it is in `zoneinfo.available_timezones()` and reads every other name as `UTC`, so no forged `time_zone` reaches `ZoneInfo`; a new `scripts/library_bench.py`.
- Frontend: `lib/thoughts.ts` (`listThoughts()`, the row type, `THOUGHT_STATUSES` and the `ThoughtStatus` type derived from it, and `ff:thought-changed` from `thought-appending`'s undo client once its `POST` answers); a new `app/app/library/page.tsx` and `components/library/` (the list, the filters, a row, and the page's own reload when the sheet closes and on `ff:thought-changed`, as the Upcoming page has; that page is not changed); `app/api/[...path]/route.test.ts` (an encoded `GET` query through the proxy); `components/chat/sidebar.tsx` (the "Library" link).
- API: new `GET /api/thoughts?limit&cursor&category&tag&status&filed_from&filed_to&time_zone`, answering `{items, next_cursor}`. The Next.js catch-all proxy sends every method through one `forward()`, which keeps the query string as it arrived; task 2.1 adds a check that an encoded `GET` query reaches the backend unchanged.
- No migration. No new dependency.
- Cost: none on the user's key. A page of the list is one indexed query. In demo mode each list request, reloads included, counts against `DEMO_RATE_LIMIT` (design Risks).
- Depends on `thought-status` (planned on this branch: the `status` column), `thought-dates` (planned: `when`, the request zone, `lib/dates.ts`, the Upcoming page and its reloads when the sheet closes and on `ff:thought-changed`), `thought-appending` (planned: the undo in the sheet, its endpoint, and its client in `lib/thoughts.ts`), and `thought-editing` (built: Edit and Delete in the sheet). Archive after `thought-dates`, `thought-status`, and `thought-appending` (design decision 11).
