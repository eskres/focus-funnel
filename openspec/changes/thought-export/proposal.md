## Why

A user's thoughts live only in this app. There is no way to take them out: to keep a copy, read them elsewhere, or move to another tool. Settings can delete everything, but cannot hand it over first. A user should be able to download all their thoughts, with everything the app knows about each one, as JSON and as Markdown.

## What Changes

- New endpoint `GET /api/me/export?format=json` or `?format=markdown`. It answers one file with every thought the user owns: title, summary, raw text, tags, category, status and when it last changed (`thought-status`), date (`when`, from `thought-dates`), filed and changed times, origin (the conversation and proposal it came from, from the archived `explore` change; the proposal id is the app's reference to the message the thought came from), and additions (where each came from and whether it was undone, from `thought-appending`).
- The JSON file holds each thought in the same shape as `GET /api/thoughts/{id}`, plus a format name, a version, the export time, and a count at the end. The Markdown file is one readable file: one section per thought, with the raw text in a code block. Text from the thoughts is escaped, so it shows exactly and never renders as HTML, an image, or a link made from Markdown syntax; a viewer may still make a bare web address clickable, which loads nothing until clicked. Both end with a line that shows the file is complete.
- The file is named `focus-funnel-thoughts-<YYYY-MM-DD>.json` or `.md` and is sent as an attachment (`Content-Disposition`) with `Cache-Control: no-store`, so browsers do not keep the whole store in their cache.
- The export is streamed. The server reads thoughts in batches of 200 by filing time, writes each batch to the response, and holds no more than one batch in memory. It writes no file on the server. It works for a large store.
- The export makes no embedding or model call, needs no provider key, and contains no vectors or search data.
- Only the user's own thoughts are exported. An origin or addition names only the user's own conversations.
- Conversations and messages are not exported. A thought names its conversation by id and title, and its source message by the proposal's id.
- One export per format runs at a time per user, so JSON and Markdown can download together. A second export in the same format while the first is running gets `409` with the new code `export_running`, and so does a fifth export while four of the user's exports are still connected. Demo mode's request limits still apply.
- A failure after the file has started ends the download as failed, without the end line, so a cut-off file is never taken for a whole one.
- Deleting all content or the account, or ending the demo, while an export runs ends that export as failed in the same way, so a file cut short by the delete never looks complete. So does the demo session reaching its expiry time while the export runs.
- Settings gets an "Export" section right above "Your data", with "Download JSON" and "Download Markdown". The browser downloads the file itself, so the page never holds it. A refused export shows its message in the section; a logged-out user is sent to log in, and an expired demo session shows the demo's "session ended" view, as elsewhere. The section is offered in demo mode too, since demo data is deleted when the session ends.
- The Next.js proxy already streams response bodies and passes `Content-Disposition`. It gets two small rules: it keeps an upstream `Cache-Control: no-store` instead of replacing it with `no-cache`, and it refuses an export started by another site (`Sec-Fetch-Site` not `same-origin` or `none`) with `403 validation_error`, the shape the app already uses for a sign-in started from another site, without calling the backend. The login's `safeReturnTo()` resolves the return address as the browser does (dot segments, `%2e`, and dropped tabs and line breaks included), no longer returns to a path under `/api/` or `/auth/` or to another site, and returns the resolved path, so a login link from another site cannot make the app's own page start an export.
- The backend's own `app.*` loggers write INFO lines to the server log, so the export's end line, and the demo cleanup's existing line, are no longer dropped.
- Errors use `{"error":{"code","message"}}`.

## Capabilities

### New Capabilities

- `thought-export`: downloading all of a user's thoughts as one JSON or Markdown file: what each thought carries, the two formats, the file name, streaming, one export per format at a time, the Settings section, and the proxy's part.

### Modified Capabilities

None. The "Deleting in settings" requirement of `account-data-deletion` stays as it is (design decision 9). The deletes call the export's new `stop_exports()` first, which changes nothing they delete or answer (design decision 15).

## Impact

- Backend: a new `app/thoughts/export.py` (batched read, JSON and Markdown writers, the one-per-format guard, `stop_exports()`, the end log line); a new `GET /api/me/export` in `app/routers/me.py`; `export_running` in `app/errors.py`; a `stop_exports()` call in `delete_user_content()` and `delete_user_data()` in `app/user_data.py`, imported inside each function so `app.demo`, `app.user_data`, and the export form no import cycle, after `stop-and-spend-cap`'s `stop_turns()` and its claim and count check, right before the first delete statement; the `app` logger set to INFO with a stderr handler in `app/main.py`; an autouse fixture in `tests/conftest.py` that clears the export's registry. It reuses `ThoughtOut`, `OriginOut`, and the addition model where `thought-appending` leaves them in `app/routers/thoughts.py`, with the `when`, `status`, and `additions` fields the planned changes add, and adds `thought_view()` and `addition_view()` beside them, taken out of the `GET`'s body, for the `GET` and the export to share. Nothing moves, so `thought-library`, planned in parallel and also changing that file, meets only that small change.
- Frontend: a new `components/export-settings.tsx` and its test; `app/settings/page.tsx` (the section above "Your data"); `export_running` and `ExportRunningError` in `lib/api.ts`, with a test in `lib/api.test.ts`; the two rules in `app/api/[...path]/route.ts`, with new tests in `app/api/[...path]/route.test.ts` and `app/api/[...path]/demo.test.ts`; `safeReturnTo()` in `lib/login.ts`, with a new `lib/login.test.ts`.
- API: new `GET /api/me/export`. No other endpoint changes.
- No migration. No new dependency.
- Cost: none on the user's key. One indexed query per 200 thoughts.
- Depends on `thought-dates`, `thought-status`, and `thought-appending` (planned) for the `when`, `status`, and `additions` fields, and on `stop-and-spend-cap` (planned, and through it `background-turns`' registry of running turns) for `stop_turns()` and the claim and count check that the deletes run before `stop_exports()`. This change is built after all four. It does not depend on `thought-library`.
