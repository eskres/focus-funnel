## Context

See `proposal.md` for why. What exists on this branch and in the planned changes below this one, and shapes the approach:

- `thoughts` has an index on `(user_id, created_at)` (`ix_thoughts_user_id_created_at`); `id` is not in it. `search_tsv` is a deferred column. Embeddings live in `thought_embeddings`, a separate table; nothing here needs to read it.
- A session runs in Postgres's default isolation, READ COMMITTED, where each statement sees the data committed when that statement starts. Two statements in one transaction can see different states.
- `get_current_user` depends on `get_session`, a dependency with `yield`. In the pinned FastAPI 0.141, `request_response()` closes such dependencies only after `await response(...)`, so for a streamed answer only after the stream ends. `get_or_create_user()` commits and then runs a `SELECT`, which starts a new transaction on the request's session.
- `delete_user_content()` and `delete_user_data()` in `app/user_data.py` do the deleting for `DELETE /api/me/content`, `DELETE /api/me`, `DELETE /api/demo/session` ("End demo"), and the demo cleanup loop (`delete_expired_demo_users`). `stop-and-spend-cap` (planned, built on `background-turns`' registry of running turns) makes those callers call `stop_turns()` first, then claim every conversation of the user in the delete's own transaction and count the ones still claimed; when that count is not 0 the delete rolls back and answers 409, and the demo cleanup loop skips the visitor until its next pass. This change is built after `stop-and-spend-cap`, so decision 15 can place its call after that claim check.
- `GET /api/thoughts/{id}` (`app/routers/thoughts.py`) answers `ThoughtOut`: id, title, summary, tags, category, raw text, created and updated times, and `origin` (`{conversation_id, conversation_title, archived, proposal_id, proposed_at}` or null). `get_thought_with_origin()` in `store.py` reads a thought and its origin in one query, joining only the owner's conversation.
- The planned changes add to that answer: `when` (`{start, end, time_zone}` or null, from `thought-dates`, five columns turned into `when` by one parser in `app/thoughts/dates.py`), `status` and `status_changed_at` (`thought-status`), and `additions` (`thought-appending`: newest first, each `{id, added_at, undone, conversation_id, conversation_title, proposal_id}`, from the `thought_additions` table, whose rows cascade away with their proposal; the raw text keeps what was added). A `thought_additions` row also holds `before`, the thought's fields before the addition, raw text included.
- `check_fields()` in `store.py` runs every text field, `raw_text` included, through `_text()`, which calls `.strip()`. `store_thought()`, `update_thought()`, and `thought-appending`'s appends all go through it, so a stored raw text never starts or ends with whitespace, a blank line or a final line break included. It can still hold `\r\n`, a lone `\r`, and blank lines inside.
- `clean_tags()` in `store.py` trims, lowercases, and drops a leading `#`, but keeps spaces and other characters inside a tag, so `weekend plans` and `a,b` are possible tags.
- The `account-data-deletion` routes live under `/api/me` in `app/routers/me.py` (`DELETE /api/me`, `/api/me/content`, `/api/me/usage`). Each refuses demo mode with 404.
- The chat already streams: `POST /api/chat` returns a `StreamingResponse` and opens its own sessions through `get_session_factory()`, because "the stream outlives the request's dependencies".
- The backend runs as one `uvicorn` process with no `--workers` (`backend/Dockerfile`). `background-turns` keeps its running turns in an in-process registry for the same reason. The pinned `uvicorn` 0.53 sets `scope["asgi"]["spec_version"]` to `"2.3"`. With that, Starlette 1.6's `StreamingResponse` runs `listen_for_disconnect(receive)` beside the body and cancels the body task when `http.disconnect` arrives. Only from spec version 2.4 does it rely on `send` raising `OSError` instead. Under 2.3, the cancel happens inside `StreamingResponse.__call__`'s own task group, which then returns normally: no `CancelledError` or other exception reaches a caller of `__call__`.
- An exception that leaves the app after the response started goes through Starlette's `ServerErrorMiddleware`, which calls the app's `Exception` handler, `_handle_unexpected_error` in `app/errors.py` (`logger.exception("Unhandled error")`), and re-raises; `uvicorn` then logs "Exception in ASGI application" with the traceback and closes the connection. An app that returns after the response started but before its last body message makes `uvicorn` log one ERROR line, "ASGI callable returned without completing response.", with no traceback, and close the connection the same way.
- The demo session's end is checked only when a request starts: `get_current_user` refuses a demo user whose `expires_at` has passed (`demo.now()`). After that, a demo user's rows go only when `delete_expired_demo_users()` runs, every 300 seconds, and with `stop-and-spend-cap` it can skip a busy visitor until its next pass.
- In firebase mode, `/login?returnTo=…` is a public page. `safeReturnTo()` in `lib/login.ts` accepts any string that starts with one `/` and not `/\`, and returns it unchanged. The value is then used through the WHATWG URL parser: after sign-in `FirebaseLogin` calls `router.replace(destination)`, which fetches that URL from the app's own page, and `/auth/callback` and demo mode's `/auth/login` redirect to `new URL(returnTo, base)`. That parser resolves `.` and `..` segments, `%2e` and `%2e%2e` included, and drops tabs and line breaks: `/settings/../api/me/export` and `/a<tab>pi/me/export` resolve to `/api/me/export`, and `/<tab>/evil.example` to `https://evil.example/`.
- The Next.js proxy (`app/api/[...path]/route.ts`) is a catch-all. Next.js hands it the `path` segments already percent-decoded, and `backendTarget()` encodes them again, so `/api/m%65/export` reaches the backend as `/api/me/export`. It adds the credential on the server, passes `request.signal` to the backend call, returns `upstream.body` without buffering, and forwards `content-disposition` and `content-type`. It sets `Cache-Control: no-cache` on every answer, and `no-store` in demo mode. In demo mode, `prepareDemoCall().finish()` also passes `upstream.body` through, except for key saves and 401 answers; on a 401 `demo_session_expired` it clears the demo cookies. `proxy.ts` limits demo requests per client address.
- The session cookie is `HttpOnly; Secure; SameSite=Lax` (`lib/session.ts`), so the browser sends it on a top-level `GET` navigation started by another site.
- On the client, `createApiError()` in `lib/api.ts` builds the error class for a code from `errorClasses`, typed `Record<ApiErrorCode, typeof ApiError>`, so every code in `ApiErrorCode` needs a class there. For `demo_session_expired` it dispatches `DEMO_EXPIRED_EVENT` (`ff:demo-session-expired`), which `components/demo/demo-context.tsx` turns into the "demo session ended" view. The other settings sections call `redirectToLogin("/settings")` on `UnauthenticatedError`.
- Settings (`app/settings/page.tsx`) shows `DeleteDataSection` ("Your data") last. That section renders nothing in demo mode.
- Postgres tests carry the `postgres` marker; `tests/thought_helpers.py` has `counted_queries()`.
- `app/demo.py` imports `delete_user_data` from `app.user_data` at the top (line 23), before it defines `now()`. `app/main.py` imports `app.demo` (for `cleanup_loop`) before the routers. `app/routers/demo.py` writes `from app.demo import now`. `app/auth.py` already imports `app.demo` inside a function, with the comment "Imported here: app.demo builds on this module."
- The backend sets up no logging of its own: there is no `basicConfig` or `dictConfig` in `app/`, and the Dockerfile runs plain `uvicorn app.main:app` with no `--log-config`. `uvicorn`'s default `LOGGING_CONFIG`, which `uvicorn.Config()` applies in its constructor, configures only the `uvicorn`, `uvicorn.error`, and `uvicorn.access` loggers, and sets `uvicorn` and `uvicorn.access` to `propagate: False`. So an `app.*` logger keeps the root level, WARNING, and its INFO records are dropped (the demo cleanup's `Deleted %d expired demo sessions` line included). And `uvicorn.error`'s records stop at the `uvicorn` logger and never reach the root logger, where pytest's `caplog` listens; once applied, that setting stays for the rest of a test session.
- `Proposal` (`app/models/conversation.py`) has no payload column. What the model wrote is in `parts` (JSON) and `raw_text`. A proposal records the tool message's `position` and the user messages it was filed from (`from_position`, `to_position`), and `thought-origin` opens an origin by conversation and proposal.
- SQLite, which the default test run uses, hands back naive datetimes. `DemoAuthenticator.current_user()` therefore compares `as_utc(user.expires_at)` with the aware `demo.now()`.

## Goals / Non-Goals

**Goals:**

- One request gives one file with all the user's thoughts, in a shape that matches the thought API.
- Memory on the server stays flat as the store grows: one batch at a time, no temp file.
- No new table, migration, or dependency. The proxy gets two small rules and no new route, and the login's `safeReturnTo()` a stricter check (decisions 11 and 14).
- A delete of all the user's content during an export never leaves a file that looks complete (decision 15).

**Non-Goals:**

- Exporting conversations, messages, or proposals. A thought names its conversations by id and title only.
- An addition's `before` snapshot (the undo state). The export holds each thought as it is now.
- Categories as a list, settings, provider keys, model loadout, usage records.
- Importing an export.
- A filtered or partial export (by category, status, or date). `thought-library` may add filters to its list; a filtered export can build on this later.
- A zip, CSV, or one file per thought.
- Times in the user's own zone in the Markdown file. Times are UTC and say so.
- A snapshot of the store at one instant (decision 2).
- Scheduled or emailed exports.

## Decisions

### 1. One route, `GET /api/me/export?format=json|markdown`

The route sits in `app/routers/me.py` beside the account-data routes that the same Settings area calls. `format` is a required query value, `json` or `markdown`. A missing or other value is refused by FastAPI's validation with 422 `validation_error`, whose message names `query.format`. The route uses `get_current_user`, so the owner comes from the credential and no id is taken from the request.

The route checks everything that can fail before the first byte: the login, the format, and the one-export guard (decision 7). After that it answers 200 and streams. The proxy refuses a start from another site before the backend is called (decision 14).

The route also takes `session: AsyncSession = Depends(get_session)`. FastAPI caches a dependency within a request, so this is the same session `get_current_user` used. The route then works in this order: it reads `user.id` and, for a demo user, `demo.as_utc(user.expires_at)` (decision 12); calls `await session.close()`; reads `utcnow()` (decision 6); and only then calls `take_lease()` and builds the generator and `ExportResponse` with that lease, inside `try: … except BaseException: release(lease); raise`. So taking the lease is the last step that can refuse or fail, and no failure can leave a lease that no `ExportResponse` will release. The session is closed because, left open, it would keep one pooled connection idle in a transaction until the stream ends (Context), which is the cost decision 2 avoids. The stream reads only through its own sessions.

**Alternatives:** two routes, `/api/me/export.json` and `/api/me/export.md` (rejected: two handlers for one flow, and the format is a value, not a resource); an `Accept` header (rejected: a link the browser follows cannot set it); `/api/thoughts/export` (rejected: `/api/thoughts/{thought_id}` would parse `export` as an id unless the route is declared first, as `thought-dates` must do for `upcoming`; and `thought-library` may shape `/api/thoughts` for its list); `POST` (rejected: it reads and changes nothing, and a frame cannot post without a form; decision 14 covers what `POST` would have guarded against). For the request's session: leave it to FastAPI (rejected: it closes only after the stream, above); make `get_session` a function-scoped dependency (rejected: `get_current_user` and every other route share it, and this change should not change when their sessions close). For the order: taking the lease before closing the session (rejected: if `close()` or a later step raised, the route would answer 500 and the lease would stay in `LIVE`, where no heartbeat clears it; four such failures would refuse the user's exports until the process restarts).

### 2. Read in keyset batches of 200, each in its own short session

`export_thoughts(session_factory, user_id, lease)` in a new `app/thoughts/export.py` is an async generator of batches. Each batch opens a session, starts its transaction at REPEATABLE READ (`await session.connection(execution_options={"isolation_level": "REPEATABLE READ"})` on Postgres), runs two queries, and closes it:

1. The thoughts with their origin, as `get_thought_with_origin()` joins it, for many rows: `WHERE thoughts.user_id = :user AND (created_at, id) > (:last_created_at, :last_id) ORDER BY created_at, id LIMIT 200`. The `(user_id, created_at)` index serves it. `id` is not in that index, so Postgres reads the row comparison as the looser `created_at >= :last_created_at`, then filters on `id` and sorts the rows that share a `created_at`. Thoughts filed at the same instant (several parts confirmed in one transaction, where `now()` is fixed) are few, so this is a short filter; only a store where thousands of thoughts share one `created_at` would reread that group on every batch.
2. The additions of those thought ids, with their conversation title, joining only the owner's conversations, newest first. It selects the listed columns only, never `before`, which can hold 20,000 characters of old raw text per row.

The batch size is a module constant, `EXPORT_BATCH = 200`, so tests can lower it.

The generator never yields an empty batch. When the thoughts query returns no rows, it stops without yielding and without running the additions query. When it returns fewer rows than `EXPORT_BATCH`, it yields them and runs no other query; when the writer asks for the next batch, it checks its lease once more (below) and then stops. So a store of exactly k × 200 thoughts yields k full batches and then runs one more thoughts query that finds nothing.

Both queries of a batch run in one REPEATABLE READ transaction, so they read one snapshot: a thought's `raw_text`, `summary`, and `updated_at` and its `additions` (and their `undone`) always come from the same moment. Under the default READ COMMITTED, an addition confirmed or undone between the two statements could be listed while the thought's fields still came from before it. The transaction is short and read-only and ends before the batch is yielded, so the stricter level costs nothing; a read-only transaction never gets a serialization failure. Postgres is the only store; the SQLite database of the default test run has no such level, so the option is set only when the dialect is `postgresql`.

Before and after each batch's thoughts query, and once more after its last batch before it stops, the generator calls `lease.check()`, which raises `ExportAborted` when the lease's `aborted` flag is set or, for a demo user, when `demo.now()` has reached the session's `expires_at` (decisions 12 and 15). It reads the clock through the module, imported inside the method (decision 16). The writers ask for the next batch only after the previous batch's chunk was sent, so the last check runs after the last thoughts were sent and before the closing chunk.

The connection goes back to the pool between batches, and the request's own session is closed before the stream starts (decision 1). A slow download, where the browser reads slowly and the server waits to send, then holds no connection and no open transaction. Oldest first matches the index and makes a thought filed during the export come last, where it is either included or not.

**Alternatives:**

- One transaction with a server-side cursor (`session.stream()` with `yield_per`): one snapshot, but it holds a connection and a transaction open for the whole download, as long as the slowest browser takes. Rejected: a few slow exports would hold the pool.
- `OFFSET` paging: rejected, it re-reads every earlier row on each page, so a large store costs quadratic work.
- Adding `id` to the index as `(user_id, created_at, id)`: rejected, it needs a migration for the rare case of a large group of thoughts filed at one instant; the goal is no migration. Task 2.7 and 5.2 seed distinct filing times, as real stores have, and task 2.1 keeps a small tie case.
- No final check after the last batch: rejected, most stores are one batch, so a delete that lands while that batch is being sent would still end the file with its count or end line.
- Load everything, then write: rejected by the goal.
- One query that also builds the additions as JSON in Postgres: rejected, it is Postgres-only SQL for no gain at one more indexed query per batch.
- Yielding the empty last batch and leaving it to the writers: rejected, every writer would then have to guard its separators against it. The writers still skip an empty batch (decisions 4 and 5), so the two rules back each other up.
- The two queries of a batch at the default READ COMMITTED: rejected, a thought could then be half old and half new, as above.
- One statement per batch that joins the additions to the thoughts: rejected, it repeats each thought's raw text on every addition row, and the stricter isolation gives the same consistency for free.

The price is that the export is not a snapshot of the whole store: a thought edited while the export runs shows its new version if its batch is read later, and a thought deleted while the export runs is left out if its batch is read later. Each thought is read whole in one batch, from one snapshot, so a thought is never half old and half new. Deleting all the user's content or account during an export is not left to this rule; decision 15 ends that export as failed. See Risks.

### 3. Each thought is the `GET` answer's shape, from one mapping

`ThoughtOut`, `OriginOut`, and (from `thought-appending`) the addition model stay in `app/routers/thoughts.py`, where `thought-appending` leaves them. Two functions join them in that file, taken out of the `GET`'s body: `thought_view(thought, origin, additions) -> ThoughtOut` and `addition_view(row)`, which turns an addition row into the addition model. `GET /api/thoughts/{id}` calls both for one thought; the export calls them for every thought of a batch. `when` comes from `thought-dates`' parser, `status` and `status_changed_at` from the row. The export's batched `additions_for(session, user_id, thought_ids)` lives in `app/thoughts/export.py`, which imports the models and the two functions from the router module. That import goes one way: the router module never imports the export (decision 16).

The GET keeps the read `thought-appending` plans for it (its decision 9: one join, like `origin`), so its thought and additions still come from one statement and this change adds no READ COMMITTED gap there. Only the export runs the batched additions query of decision 2, on its REPEATABLE READ session. The request's session cannot take that level: `get_current_user` has already started its transaction (Context).

So the export and the single-thought API cannot drift. A field that a later change adds to `ThoughtOut` joins the export too. A test pins the exported key set, so such an addition is a deliberate change to that test, and a reviewer sees it.

`ThoughtOut` has no vector or search field, and the queries never touch `thought_embeddings` or `search_indexes`. A test checks the SQL the export runs for both. Nothing from a message is read, and of a proposal only `id`, `created_at`, `conversation_id`, and `user_id`, for the origin and the additions; never `parts` or `raw_text`, which hold what the model wrote (Context). So text the assistant wrote in the conversation cannot reach the file.

**Alternatives:** a separate export schema (rejected: two shapes to keep in step, for the same thought); `select *` style rows turned to dicts (rejected: it would pick up `search_tsv` and any later column without review); the GET reading its additions with the export's batched query and one id (rejected: two statements on the request's READ COMMITTED session could mix a thought and its additions from different moments; the shared `addition_view()` and the equality test of task 2.4 already keep the two from drifting); moving the models and the two functions into a new `app/thoughts/views.py`, so the export imports no router (rejected for now: `thought-library`, planned at the same time, also changes `app/routers/thoughts.py` and its models, and a move here would force a merge on that branch; the move can come in a later change once `thought-library` has landed); `thought_view()` in a new `app/thoughts/views.py` or in `export.py` that imports the models from the router (rejected: the `GET` would import it back, a cycle between the router and that module).

### 4. The JSON file: one document, one thought per line, the count last

```
{"format":"focus-funnel-thoughts","version":1,"exported_at":"2026-11-05T14:03:00Z","thoughts":[
{...thought...},
{...thought...}
],"count":2}
```

The generator yields the opening line before the first query, then one chunk per batch, then the closing line with the count. Each thought is `model_dump_json()`. Inside a batch, thoughts are joined by `,\n`. A batch after the first non-empty one starts with `,\n`, and an empty batch writes nothing and does not count as the first. So the file is valid JSON whatever batches arrive. The count comes last because it is only known at the end. It doubles as the sign that the file is complete: it is written only when the last batch was read and no delete of the user's content or account stopped the export (decision 15). One thought per line keeps the file easy to read with `grep` and line tools while staying one JSON document.

`exported_at` is the export's start, in UTC, to the second, with `Z` (decision 6).

**Alternatives:** JSON Lines (rejected: the story asks for JSON, and most tools that open "a JSON file" expect one document); a count at the start (rejected: it needs a `count(*)` first, and the number can change before the end, decision 2); pretty-printed JSON (rejected: each thought spread over many lines, for a file people mostly feed to tools).

### 5. The Markdown file: one file, a section per thought, data shown as plain text

One file streams as simply as the JSON. A zip would need a streaming zip writer and gives the user a folder to unpack, for no gain in reading. The layout:

````
# Focus Funnel thoughts

Exported 2026-11-05 14:03 UTC.

---

## Call the plumber

- Status: done, marked done 2026-11-04 10:15 UTC
- Category: task
- Tags: #home, #weekend plans
- Date: 2026-11-09 (Europe/Oslo)
- Filed: 2026-10-01 09:12 UTC
- Changed: 2026-10-12 09:00 UTC
- From: Weekend plans (archived), proposed 2026-10-01 09:10 UTC, conversation 1b2c4e6a-3f0d-4c1e-9a57-2d8b6e0f4a13, proposal 3c4d5e6f-7a8b-4c9d-8e0f-1a2b3c4d5e6f
- ID: 9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a

### Summary

> Call the plumber about the leaking kitchen tap.

### Raw text

```text
the kitchen tap leaks again, call the plumber on monday
```

### Additions

- 2026-10-12 09:00 UTC from Plumber chat, conversation 5e6f7a8b-9c0d-4e1f-a2b3-c4d5e6f7a8b9, proposal 7a8b9c0d-1e2f-4a3b-8c4d-5e6f7a8b9c0d

---

End of export: 1 thought.
````

Rules:

- A line or section with nothing to show is left out: no `Category`, `Tags`, `Date`, `From`, `Raw text`, or `Additions` when the thought has none. `Status` is always shown.
- The status line carries the time of the last status change whenever there is one, since `thought-status` sets `status_changed_at` on every change, reopening included: `- Status: done, marked done <time> UTC` for `done`; `- Status: open, reopened <time> UTC` for `open` with `status_changed_at` set (a done thought opened again); plain `- Status: open` when `status_changed_at` is null (it never changed). A status that a later change adds gets `- Status: <status>, since <time> UTC`.
- **Line breaks.** In every data field outside the raw text, the writer treats every break that `str.splitlines()` knows as a line break: `\r\n`, `\r`, `\n`, and also `\v`, `\f`, `\x1c` to `\x1e`, `\x85`, U+2028, and U+2029. CommonMark ends a line at a lone `\r` as well as at `\n`, and line tools follow `splitlines()`. So it splits with `splitlines()`, never on `\n` alone. A single-line field (title, tag, category, conversation title) turns each break into a space, so the heading and every `- Name:` line stay one line. The summary quotes each resulting line (below). Escaping a `-`, `+`, `=`, or number at the start of a line then sees every line a viewer sees. The titles and summaries can hold a lone `\r`: `_text()` in `store.py` only strips them, and a model's tool call or `mcp-connectors` text can carry one.
- Tags are written each with `#`, separated by `, `. A comma inside a tag is written `\,`. So `#home, #weekend plans` reads back as two tags, the second with a space.
- A date shows as stored, `T` replaced by a space: `2026-10-02 19:00`, or `2026-11-03 to 2026-11-06`, then the zone in brackets. Other times are UTC, to the minute, with `UTC`.
- An undone addition ends with `(undone)`. Additions are newest first, as in the sheet.
- Ids are written in full. The `ID:` line carries the thought's UUID, the `From:` line the origin conversation's and the proposal's, and each addition line its conversation's and proposal's, so the file keeps the references decision 13 promises.
- **Data is shown, never rendered.** Titles, summaries, tags, categories, and conversation titles are written by a model or a user, and with `mcp-connectors` they can carry text from outside sources such as a calendar invite. Many Markdown viewers load remote images and raw HTML when a file is opened. So in every field outside the raw-text code block, the writer puts a backslash before each `` \ ` * _ [ ] < > ! # & ~ | `` character. It also escapes the start of each line, where the start is the first character that is not a space or a tab, since CommonMark allows up to three spaces before a list marker, a rule, or a setext underline: a `-`, `+`, or `=` there gets a backslash, and so does the `.` or `)` after a number there (`1\.`, `  2\)`). Inside the summary's quote this is what stops `> - item`, `>   1. step`, `> ---`, and `> x` followed by `> ===` from rendering as a list, a rule, or a heading. Other fields sit after the writer's own `## ` or `- Name: `, so for them it changes nothing a viewer shows. That covers conversation titles in the `From:` line and in each addition line too: a conversation title starts as the user's first message and the user can rename it. The text then shows exactly as stored and renders as plain text: no HTML, image, heading, list, rule, or end line ever comes from data, and no link from Markdown link syntax or `<…>` autolinks. Only the writer's own lines (headings, the `- Name:` lines, rules, the end line) are Markdown.
- Bare web addresses are the one thing escaping does not stop. GFM viewers (GitHub, VS Code, Obsidian) turn a bare `https://…`, `www.…`, or email address in plain text into a link. Such a link loads nothing when the file is opened; only a click follows it, and the address shows exactly as stored. The writer does not break the addresses up: escaping the `:` after a scheme or the `.` after `www` works in some renderers and not others, and it changes what a plain-text reader sees.
- The summary is a block quote: each of its lines, after splitting as above, starts with `> ` (a blank line is `>`), after escaping. So no summary line can stand on its own as a heading, a rule, or the end line.
- **Indented summary lines.** Inside `> `, a line whose leading spaces and tabs reach four columns is an indented code block in CommonMark (when it opens the quote or follows a blank line), and a code block shows the escape backslashes as typed: `    <b>x</b>` would show as `\<b\>x\</b\>`. So when a summary line's leading whitespace holds a tab or at least four spaces, the writer writes that whitespace's first character as a character reference: a space as `&#32;`, a tab as `&#9;`. A reference is not indentation, so the line stays a paragraph, and its text is the stored line, leading whitespace included. `&` is escaped everywhere in data, so a reference never comes from data. The line-start escaping above still applies after the reference. A line with a shorter indent is written as it is.
- The raw text sits in a fenced block whose fence is one backtick longer than the longest run of backticks in the text, and at least three. The writer puts the opening fence line, the raw text exactly as given (`\r\n`, a lone `\r`, and blank lines included), then always exactly one `\n`, then the closing fence. A stored raw text is stripped (Context), so it never starts with a blank line or ends with a line break; the writer still keeps a leading blank line or a final newline it is given, which task 2.3 checks on in-memory data. So the raw text is what lies between the opening fence line's `\n` and the closing fence, minus that one `\n`, and a raw text with its own fences cannot end the block early.
- The last line is `End of export: N thoughts.` (`1 thought.` for one). With no thoughts, the body is `No thoughts.` and the last line says `0 thoughts`. Because every data line outside a code block is split on every line break, escaped, and, in the summary, quoted, this is the only line outside a code block that starts with `End of export:`. It is written only when the export was not stopped (decision 15).
- Like the JSON writer, an empty batch writes nothing.

Each section is built from the `ThoughtOut` of decision 3, so both formats show the same data.

**Alternatives:** a zip with one `.md` per thought (rejected above); the raw text as a block quote (rejected: Markdown in it would render and change what the user sees); the summary in a code block too (rejected: it makes the file hard to read, which is the point of the format); data written as it is (rejected: a summary could load a remote image when the file is opened, and could fake a section or the end line); stripping HTML and links (rejected: it changes the text, and the export keeps what is stored); tags separated by spaces (rejected: a tag can hold a space); tags each in backticks (rejected: a tag can hold a backtick, and the line reads less easily); adding the closing `\n` only when the raw text lacks one (rejected: then `a` and `a\n` give the same file, and the round trip is lost); splitting data on `\n` only (rejected: a summary `x\r---` would give a rule outside the quote, and `x\rEnd of export: 9 thoughts.` a fake end line); escaping only a marker in a line's very first character (rejected: `   - item` and `   ---` would still render as a list and a rule); shortened ids, as a reader might prefer (rejected: a cut id names nothing, and the JSON file would then hold references the Markdown file lacks); escaping bare addresses (rejected above); leaving the time out of an open status line (rejected: the time of a reopen is data the thought has, and the JSON carries it); leaving a summary line indented by four columns to render as code (rejected: the code block shows the escape backslashes, so the text no longer shows as stored); `&nbsp;` for the first space (rejected: it is a different character, so a copy from the viewer would not give back the stored line); a reference on every indented line, however short (rejected: one to three spaces never make code, and the plain form reads better in a text editor).

### 6. File name, headers, and the clock

- JSON: `Content-Type: application/json; charset=utf-8`, `Content-Disposition: attachment; filename="focus-funnel-thoughts-2026-11-05.json"`.
- Markdown: `Content-Type: text/markdown; charset=utf-8`, `Content-Disposition: attachment; filename="focus-funnel-thoughts-2026-11-05.md"`.
- Both: `Cache-Control: no-store`, so no browser or cache keeps the whole store on disk after the user deletes the file or their content (decision 11).

The route reads the time once, from `app.thoughts.export.utcnow()`, a module function tests replace. The date in the name is that instant's UTC day, the same instant as `exported_at` and the Markdown `Exported` line. The name is plain ASCII, so it needs no `filename*`. A refused export is an ordinary error answer with no `Content-Disposition`.

**Alternatives:** the user's local day (rejected: the browser would have to send its zone for a file name; see Non-Goals); a time in the name (rejected: a second export on the same day gets the browser's own `(1)` suffix, which is enough); a clock passed as a dependency (rejected: one module function is the seam `conversations.now()` and `demo.now()` already use).

### 7. One export per user and format at a time, with a one-minute heartbeat

`app/thoughts/export.py` keeps one registry in the process, `LIVE: dict[user_id, set[Lease]]`. It holds every lease that has not been released, stale ones included, so `stop_exports()` can reach every export that is still connected (decision 15). A lease has its format, the monotonic time of its last write, an `aborted` flag, and, for a demo user, the session's `expires_at` (decision 12). Leases are plain objects compared by identity; they carry no token. A lease is *running* when it is not `aborted` and was written within the last 60 seconds. So a user can download JSON and then Markdown at once, as the story asks, but cannot start a second JSON export while one runs.

- The route takes the lease with `take_lease(user_id, format, expires_at)`, a synchronous function: it checks the user's set and adds the new lease in one step, with no `await` between them. In one event loop, two requests that arrive together therefore cannot both pass the check: one gets 200, the other 409.
- It refuses with 409 `export_running` ("An export in this format is already running. Try again when it has finished.") when the user's set holds a running lease of that format. It also refuses with 409 `export_running` ("Too many of your exports are still open. Try again when one has finished.") when the set already holds `EXPORT_LIVE_LIMIT = 4` leases. Otherwise it adds a new lease; a stale lease of that format stays in the set until its export ends.
- The generator refreshes the lease's write time after each chunk it yields.
- The lease is released by `ExportResponse`, a small `StreamingResponse` subclass whose `__call__` ends with `finally: await self.body_iterator.aclose(); release(lease); log the end` (decision 8). So an export that ends, fails, or loses its client frees that format at once, whether or not the generator ever started. `release()` removes that lease, and only that one, from the user's set, and drops the user's key once the set is empty. An old export's release therefore never drops a newer one's lease.
- A lease not written for 60 seconds is stale. This heartbeat has one job: a connection that stays open but stops reading, such as a paused browser download or a proxy that hangs, sends no disconnect, so without it the user would be blocked until the connection dies. With it they are blocked for one minute at most. A stale export that starts writing again counts as running again, which is what it is.

`LIVE` is module state. `backend/tests/` is flat, with one `tests/conftest.py`, so an autouse fixture there clears it before and after every test. That also covers the delete tests in `test_delete_my_data.py` and `test_demo.py` that reach `stop_exports()`. A test that fails while it holds a lease, or a lease left fresh by another test's clock patch, then cannot make a later test answer 409.

This is all the abuse control the export needs. It is a read of the user's own rows, one indexed query per 200 thoughts, with no provider cost. At most one export per format is running, and at most four are connected per user, so a client that stops reading and starts again every 61 seconds holds at most four batch-sized chunks in `uvicorn`'s write buffer. In demo mode, `proxy.ts` already limits requests per client address, and the export is one request. Another user's export never waits on this user's.

**Alternatives:** no limit (rejected: a script could start many full reads of a large store at once); one export per user across formats (rejected: it refuses "Download JSON" then "Download Markdown", the natural way to get both); a cap of two running exports per user (rejected: two JSON exports would be allowed and a Markdown one refused, which is harder to explain than one per format); no heartbeat, relying on disconnect alone (rejected: a paused download would hold the format until the browser drops the connection, which can be hours); a per-user rate limit, such as one export per minute (rejected: it refuses a user whose download failed and who tries again at once, which the lease does not); a Postgres advisory lock (rejected: it holds a connection for the whole download, which decision 2 avoids, and does not exist on SQLite); a row in a jobs table (rejected: a migration for state that only matters while one process runs); 429 `rate_limited` (rejected: nothing is too frequent; the user's own export is in the way, as `conversation_busy` says for a running answer); a second registry, `RUNNING`, holding the newest lease per user and format beside `LIVE`, with a token so that a release drops only its own entry (rejected: two structures to keep in step, and a token rule to test, for what one set and the running test above give; the one difference, a stale export that writes again counting as running, is the more accurate answer); forgetting a stale lease once a new one is taken (rejected: `stop_exports()` could then not reach that export, which would go on after a delete and end with its count, and stalled exports would have no bound); aborting a stale lease when a new one is taken (rejected: a slow but live download would fail because the user pressed the button again, and it still would not bound stalled exports, which see the flag only when they resume); checking and storing the lease across an `await` (rejected: two presses at once could both pass the check).

### 8. A failure after the first byte ends the download as failed; every export logs one end line

Once the 200 and the first chunk are sent, the status cannot change. When a batch query fails, the generator re-raises. Starlette's error middleware cannot send a 500 after the response started, so it re-raises, and `uvicorn` closes the connection without the final empty chunk. The browser sees an incomplete transfer and marks the download failed. The proxy passes the broken stream on as broken (decision 11). The part received never has the closing count (JSON) or the end line (Markdown), so a file saved some other way is visibly cut off.

When the client goes away, the pinned `uvicorn` (spec version 2.3) sends `http.disconnect`, Starlette cancels the body task inside its own task group, and `super().__call__` returns normally (Context). `ExportResponse`'s `finally` then closes the generator, so no further batch is read. Under a server at spec version 2.4 or later, Starlette instead sees `send` raise `OSError` and raises `ClientDisconnect`; the same `finally` runs. Tests cover both.

An export stopped by a delete or by the demo session's end (decision 15) is a user's action, not a server error, so it does not go up to Starlette. `ExportResponse` catches `ExportAborted` from `super().__call__` and returns without sending the last body message. `uvicorn` closes the connection without the final empty chunk, as for a failure, and logs one ERROR line, "ASGI callable returned without completing response.", with no traceback and no thought content. The app's "Unhandled error" handler never sees it.

`ExportResponse`'s `finally` writes one INFO line on logger `app.thoughts.export` for every export that started. It reaches the server's log because `app/main.py` sets up the `app` logger (decision 17):

```
export ended user=<id> format=<json|markdown> thoughts=<n> outcome=<complete|failed|client_gone>
```

`ExportResponse`'s body iterator wraps the writer and sets a `finished` flag when the writer is exhausted. That happens only after the writer's last `yield` resumes, that is, once Starlette has sent the closing chunk and asked for more. The outcome is:

- `complete` when `finished` is set;
- `failed error=ExportAborted` when `super().__call__` raised `ExportAborted` (caught, above);
- `failed error=<exception class>` when it raised anything else except `ClientDisconnect` (re-raised);
- `client_gone` when it raised `ClientDisconnect` (spec 2.4 and later), or returned normally while `finished` is not set (spec 2.3, where the body task was cancelled).

`thoughts` is the number written so far. A failure is logged at INFO too, since the line is the record; any exception other than `ExportAborted` goes up to Starlette as above. No log line holds thought content: no title, summary, tag, or raw text.

**Alternatives:** write an error object into the file and end it normally (rejected: the download would look complete, and the JSON would no longer have one shape); `client_gone` only on a `CancelledError` or `ClientDisconnect` that reaches `ExportResponse` (rejected: under the pinned spec 2.3 neither reaches it, so every cancelled download would log as `failed`); re-raising `ExportAborted` like any failure (rejected: every export followed by a delete would log an "Unhandled error" traceback twice, from the app's handler and from `uvicorn`, for a normal user action); ending a stopped export with the last body message (rejected: the browser would mark the download complete); collect everything first so an error can still be a 500 (rejected by the streaming goal); log only failures (rejected: an operator, and task 5.2, cannot then tell a cancelled export from one still running).

### 9. The Settings section sits above "Your data", and `account-data-deletion` is not changed

A new `ExportSection` (`components/export-settings.tsx`) is its own card, "Export", placed in `app/settings/page.tsx` directly before `DeleteDataSection`. Its text: "Download all your thoughts with their dates, status, tags, category, summary, raw text, where they came from, and their additions." It has two buttons, "Download JSON" and "Download Markdown", and no confirmation, since nothing is changed.

It is a separate card because "Your data" renders nothing in demo mode, and the export is offered there (decision 12). The "Deleting in settings" requirement of `account-data-deletion` stays as it is, so it does not collide with `stop-and-spend-cap`, which modifies the same requirement. The export's own requirement says where the section sits. The deletes gain a call to `stop_exports()` (decision 15), which changes nothing they delete or answer; what it does to a running export is the export's own requirement.

**Alternatives:** a fourth row in "Your data" (rejected: that card hides in demo mode, and its rows are destructive buttons with confirmations); modifying "Deleting in settings" (rejected: the delete rules do not change, and a second change rewriting that block would have to be merged with `stop-and-spend-cap`'s).

### 10. The browser downloads through a hidden frame, and reads only a refusal

Each press appends a new hidden same-origin `<iframe>` whose `src` is `/api/me/export?format=…`. No press removes or reloads an earlier frame. Removing a frame, or changing its `src`, before its navigation has become a download cancels that request; the backend holds the lease until the abort reaches it. So with one frame per button replaced on each press, a quick double-click would cancel the first request and could get 409 on the second, leaving the user with no file and an "already running" message. With a frame per press, the first request goes on, and the second is refused with 409 `export_running` while the first runs, which the card shows (below). Pressing the other button never touches a running download. The frames stay until the section unmounts; a page of settings sees a handful of presses.

`lib/api.ts` gets `export_running` in `ApiErrorCode`, `ExportRunningError`, and the `export_running: ExportRunningError` entry in `errorClasses`, which its `Record<ApiErrorCode, …>` type requires.

- On success the answer is an attachment. The browser's own download manager saves it to disk as it arrives and shows its progress. The page holds none of it and stays as it is.
- On a refusal (401, 403, 409, 422, 429, 500, 502) the answer is JSON with no attachment, so it loads into the frame. The frame's `load` handler reads the error text from the frame's document: first the text of its first `pre` element, then the body's text. Chrome and Safari show a JSON answer as a `pre`; a JSON viewer may wrap it in its own interface.
  - When the text parses as `{"error":{"code","message"}}`, the handler builds the error with `createApiError(code, message, 0)` (the frame cannot read the status; nothing here uses it). So `demo_session_expired` dispatches `ff:demo-session-expired` and the demo "session ended" view shows, as for every other call. On `UnauthenticatedError` it calls `redirectToLogin("/settings")`, as the other settings sections do, and shows no alert. Any other error shows its message in the card's alert.
  - When the document has text that does not parse, such as a JSON viewer's interface, the card shows "The export could not start. Try again." So a refusal is never silent.
  - An empty or unreadable document, which is what a frame that fires `load` for a download has, is ignored, so a download is never shown as an error.

The section does not show a busy state: the page cannot tell when a download ends, and the browser shows that itself.

**Alternatives:**

- One frame per button, remounted with a new `key` on each press (rejected: the remount removes the earlier frame and can cancel its request, above).
- Ignoring a press while that button's last frame has not fired `load` (rejected: browsers differ in whether a frame fires `load` for a download, so the button could stay dead).
- `fetch()` and save a `Blob` (rejected: the browser would hold the whole file in memory and show no progress until the end, which undoes the streaming).
- An `<a download>` link (rejected: a refused export would be saved as a file holding the error JSON in some browsers, with nothing shown on the page).
- A plain link or `window.location` (rejected: a refusal would replace the settings page with raw JSON).
- The File System Access API (rejected: not in every browser).
- Showing every parsed error's message, without `createApiError()` (rejected: a demo visitor whose session expired would see only a line in the card while the page went on as if the session were live, and a logged-out user would not be sent to log in).
- Refusals sent as `text/plain` for this route (rejected: the 401 comes from a shared dependency and the 429 and 502 from the proxy, so every one of them would need a special case).

### 11. The proxy keeps `no-store` from the backend

The catch-all already streams `upstream.body`, forwards `content-disposition` and `content-type`, adds the credential on the server, and passes `request.signal` to the backend call, so a cancelled download aborts the backend request and `ExportResponse` releases the lease. In demo mode, `finish()` passes `upstream.body` through for every route but key saves and 401s. When the backend's connection breaks mid-body, the proxy's body stream errors, and the browser's download fails.

One change: the proxy sets `Cache-Control: no-cache` on every answer outside demo mode, which lets a browser store the answer on disk and only check it again before reuse. For the export that would leave the whole store in the browser's cache after the user deleted the file, or their content. So when the upstream answer's `cache-control` holds `no-store`, the proxy keeps `no-store`. The backend sends it on the export (decision 6). Demo mode already sets `no-store`.

New tests pin all of this (task group 4), so a later proxy change that buffered, dropped the header, or weakened the cache rule would fail them.

**Alternatives:** a dedicated `app/api/me/export/route.ts` (rejected: it would repeat the credential and demo handling the catch-all has); `no-store` on every proxied answer (rejected: a wider change than this feature needs, though nothing here stands against it later); `no-store` whenever the answer is an attachment (rejected: it ties the cache rule to a header that means something else; the backend saying `no-store` is the direct signal).

### 12. Demo mode offers the export

A demo visitor is a user like any other on the backend, and their thoughts are deleted when the session ends. Taking them out first is the most useful thing the export does for them. The route does not refuse demo mode, unlike the delete routes, and the section shows in demo mode. The demo request limit covers abuse (decision 7).

An export started just before the session expires must not go on reading and sending the visitor's data after it. `get_current_user` checks the expiry only when the request starts, and the cleanup loop may come minutes later or skip a busy visitor (Context). So the route stores the demo user's expiry on the lease as `demo.as_utc(user.expires_at)`: SQLite, in the default test run, hands back a naive time (Context), and comparing it with the aware `demo.now()` would raise `TypeError`, which `DemoAuthenticator.current_user()` avoids the same way. `lease.check()` (decision 2) raises `ExportAborted` once `demo.now()`, read through the module (decision 16), reaches it. The export then ends as failed, as for a delete (decision 15), at the latest at the next batch boundary.

**Alternatives:** hide it in demo mode, as the delete choices are (rejected: the delete choices are hidden because "End demo" already deletes; nothing else exports); leave the end to the cleanup loop's `stop_exports()` (rejected: the spec refuses the session once it expires, and the loop can be minutes late); read the user row in each batch (rejected: a query per batch for a time already known when the export starts); storing `user.expires_at` as the database hands it back (rejected: naive on SQLite, above).

### 13. Scope: thoughts and origin references only

The file holds thoughts. A thought's origin and additions name their conversation by id and title, the proposal by id, and when it was proposed or added. Messages and proposals are left out: exporting them is a second, larger format (roles, tool calls, compacted summaries, proposal parts) that the story does not need, and the ids keep the link for a later conversation export. The raw text is in the file, and it is the user's own words from those conversations.

The origin's `proposal_id`, and each addition's, stands for the message the thought came from. A proposal records the tool message's position and the user messages it was filed from (`position`, `from_position`, `to_position`), and `thought-origin` opens an origin by conversation and proposal (Context). So the conversation id plus the proposal id is the app's own reference to the source message, which the story asks for, and no separate message id is exported.

### 14. Only a same-origin page can start an export

Because the session cookie is `SameSite=Lax`, another site could open `/api/me/export?format=json` as a top-level navigation or with `window.open`. The browser would send the cookie and save the user's whole store to their downloads folder without them asking, which matters on a shared machine, and the site could hold the user's lease so their own export gets 409.

The real button always loads the export in a same-origin frame, which the browser sends with `Sec-Fetch-Site: same-origin`. So the proxy refuses `GET /api/me/export` with 403 `validation_error` ("Start the export from Settings.") when `Sec-Fetch-Site` is present and is neither `same-origin` nor `none`, before it calls the backend. That is the shape the app already uses for a request started from another site: `app/auth/firebase/session/route.ts` answers 403 `validation_error` ("Sign in from this site's login page."). The app's other 403 code, `not_allowed`, means an allow-list refusal and maps to `NotAllowedError`, so it does not fit.

The check matches the decoded route segments the proxy already hands to `backendTarget()`: `path.length === 2 && path[0] === "me" && path[1] === "export"`. It never matches `request.url` or `request.nextUrl.pathname`. Next.js decodes the segments and `backendTarget()` encodes them again, so `/api/m%65/export` and `/api/me/%65xport` reach the backend's export; a check on the raw path would let those through with the cookie. The check runs right after `path` is read, before `getCredential()` and before demo mode's `prepareDemoCall()`. `none` is a navigation the user started (the address bar or a bookmark), which is their own choice. A request without the header (an older browser, or `curl` with the cookie) passes, since no other site can make a current browser omit it. `validation_error` is already in `ApiErrorCode`, so the client needs no new code for it.

This check trusts that only the app's own code makes a `same-origin` request to the export. One app path could be steered from outside: the login's return address. In firebase mode, another site can link to `/login?returnTo=/api/me/export?format=json`; after the user signs in, `FirebaseLogin` calls `router.replace()` with that path, and the Next router fetches it from the app's page, with `Sec-Fetch-Site: same-origin` (Context). A test on the raw string is not enough, since every place that uses the value resolves it with the WHATWG URL parser first: `/settings/../api/me/export`, `/settings/%2e%2e/api/me/export`, `/./api/me/export`, and `/a<tab>pi/me/export` all resolve to `/api/me/export`, and `/<tab>/evil.example` and `/<newline>/evil.example` resolve to another site (Context). So `safeReturnTo()` in `lib/login.ts` resolves the value the same way and checks what it resolves to:

- An empty value, or one that does not start with `/`, falls back to `DEFAULT_RETURN_TO`, as now.
- It parses the value with `new URL(value, "http://placeholder.invalid")` and falls back unless the parsed origin is still `http://placeholder.invalid`.
- It falls back when the first segment of the parsed `pathname`, percent-decoded, is `api` or `auth`: `/api`, `/api/…`, `/auth`, and `/auth/…`, since a login only ever returns to a page. Decoding the segment means an encoded letter, as in `/%61pi/me/export`, cannot hide it; a segment that does not decode falls back too.
- Otherwise it returns the parsed `pathname + search + hash`, not the raw value. So the router and the redirects get the path that was checked, already normalized.

That covers every login mode, as all of them go through `safeReturnTo()`. It also closes the redirect to another site through a tab or a line break, which the old check let through.

**Alternatives:** a new code `forbidden` (rejected: the app would then have two names for one refusal, and `forbidden` would need a place in `ErrorCode`, `ApiErrorCode`, and `errorClasses` for nothing the client does differently); a CSRF token in the URL (rejected: the frame's URL would need a token from a prior call, for the same protection the header gives); `SameSite=Strict` (rejected: it changes login for the whole app); checking `Referer` (rejected: it can be stripped by policy, and an empty one would have to pass); checking in the backend route, with the proxy forwarding the header (rejected: the backend is private and sees only the proxy, so the check belongs where the browser's request arrives, and the refused call then never reaches the backend); `POST` with a form (rejected: decision 1); matching the URL's pathname (rejected: percent-encoding gets past it, above); refusing only `/api/me/export` in `safeReturnTo()` (rejected: no API or auth route is a page to land on after login, and a list of one would miss the next such route); testing the raw `returnTo` string for `/api/` and `/auth/` (rejected: dot segments, `%2e`, and a dropped tab reach `/api/me/export` once the parser resolves them, above); returning the raw value after checking the parsed one (rejected: the check and the use would then read two different paths).

### 15. Deleting during an export ends it as failed

The Export card sits right above "Your data", and decision 12 offers the export as the step before "End demo". So a likely flow is: press "Download JSON", then delete while the download still runs. Left alone, the delete commits, the next batch finds no rows, and the writer ends the file with its count or end line and logs `outcome=complete`. The user would get a file that carries the export's own "complete" mark but lacks most of their thoughts, and the data would be gone.

New `stop_exports(user_id)` in `app/thoughts/export.py` sets `aborted` on every lease in the user's `LIVE` set, in both formats and stale ones included (decision 7). It is synchronous and waits for nothing. An aborted lease no longer counts as running, so a new export can start right after the delete. `delete_user_content()` and `delete_user_data()` in `app/user_data.py` call it right before their first delete statement, importing it inside the function (decision 16). That covers every caller: `DELETE /api/me/content`, `DELETE /api/me`, `DELETE /api/demo/session` ("End demo"), and the demo cleanup loop. The order in each delete is `stop-and-spend-cap`'s: `stop_turns()`, then the claim of the user's conversations and the count of those still claimed in the delete's transaction, and only then `stop_exports()` and the delete statements. So a delete refused with 409, or a visitor the cleanup loop skips, stops no export. This is why the change is built after `stop-and-spend-cap`.

The generator calls `lease.check()` before and after each batch's thoughts query and once more after its last batch (decision 2), and raises `ExportAborted` when the flag is set. The flag is set before the delete commits, so any query that could see the delete starts after the flag is set, and the check after that query raises at the latest. A delete that lands while the last batch is being sent is caught by the last check, before the closing chunk. The download then ends as failed, as in decision 8: no count, no end line, and `outcome=failed error=ExportAborted`, with no "Unhandled error" traceback. The stopped export's later `release()` removes only its own lease, so a new export started after the delete keeps its lease. A batch that was read before the delete may still be sent; it holds thoughts as they were, and the file stays visibly cut off.

**Alternatives:**

- Refuse the deletes with 409 `export_running` while a fresh lease exists (rejected: it changes `account-data-deletion`'s delete requirements, which `stop-and-spend-cap` already modifies, so the two changes would have to be merged; a user who deletes means to delete; and the demo cleanup loop cannot ask anyone to wait).
- Leave it to the count (rejected: the count is right for what was written, so the file looks whole while most of it is missing).
- Wait in the delete until the export ends (rejected: a slow download could hold a delete for minutes).
- A Postgres check in each batch, such as reading the user row (rejected: content deletes keep the user row, and it adds a query per batch for what an in-process flag does; the deployment is one process, decision 7).

### 16. No import cycle between the demo, the deletes, and the export

`app.demo` imports `app.user_data` at the top, and `app/main.py` imports `app.demo` first (Context). This change makes `app.user_data` call `stop_exports()` from `app.thoughts.export` (decision 15), and makes `Lease.check()` read `demo.now()` (decision 12). With top-level imports on both new edges, that closes the loop `app.demo → app.user_data → app.thoughts.export → app.demo`. Then `from app.demo import now` at the top of `export.py`, as `app/routers/demo.py` writes it, fails when `app.main` starts, because `app.demo` defines `now` only after its line that imports `app.user_data`. And when `export.py` is loaded first, as a test or the autouse fixture of task 2.5 can do, `app.user_data` meets a half-loaded `export` with no `stop_exports` yet. Either way it is an `ImportError`.

The rule:

- `app/user_data.py` imports `stop_exports` inside `delete_user_content()` and `delete_user_data()`, with a comment in the style of `app/auth.py`'s: "Imported here: app.demo imports this module, and the export reads app.demo's clock."
- `export.py` never imports `app.demo` at the top. `Lease.check()` does `from app import demo` inside the method and calls `demo.now()`. Reading it through the module also means a test that patches `app.demo.now` is seen.
- `export.py` imports `app.routers.thoughts` at the top (decision 3). That module imports neither `app.demo`, `app.user_data`, nor the export.

Task 2.1 checks that `import app.thoughts.export`, `import app.user_data`, and `import app.main` each succeed in a fresh interpreter, and tasks 2.9 and 2.10 run that check again.

**Alternatives:** a lazy import on one edge only (rejected: either one alone breaks today's loop, but `export.py` imports the router module, whose imports can grow, and a lazy import on each new edge keeps the loop from coming back through a later import); `stop_exports()` and the registry in `app/user_data.py` (rejected: the deletes module would then hold the export's state); the export registering a callback with `app.user_data` when it is imported (rejected: whether a delete stops exports would then depend on import order).

### 17. The backend's `app` loggers write INFO to the server log

`ExportResponse`'s end line is the operator's record of an export (decision 8), and task 5.2 reads it in the backend log. With no logging setup (Context), an INFO line from `app.thoughts.export` is dropped. So `app/main.py`, at import and beside `install_log_masking()`, calls a new `configure_app_logging()` that sets the `app` logger to INFO and gives it one `StreamHandler` on stderr with the format `%(levelname)s %(name)s: %(message)s`. It adds the handler only when the `app` logger has none, so a second call adds no second handler. `propagate` stays on, so pytest's `caplog` still sees `app.*` records; the root logger has no handler under `uvicorn`'s default config, so nothing is written twice. Root and library loggers are left as they are. This also makes the existing `Deleted %d expired demo sessions` line visible. `install_log_masking()` sets the record factory, so its masking applies to these records as to all others.

Tests that read the end line still call `caplog.set_level(logging.INFO, logger="app.thoughts.export")`, so they do not depend on whether `app.main` was imported first.

**Alternatives:** the end line at WARNING (rejected: a complete export is no warning, and the cleanup line would stay hidden); `--log-config` in the Dockerfile (rejected: the compose files, `uv run uvicorn` in development, and the tests start the app in different ways, and the code is the one place they share); `logging.basicConfig(level=logging.INFO)` (rejected: it turns on INFO for every library, such as `httpx`, which logs each request's URL, provider calls included).

### 18. The `GET` keeps its two reads; `thought_view()` takes the additions already built

Decision 3 says the `GET` keeps the read `thought-appending` planned for it, "one join, like `origin`". As built, `thought-appending` reads them in two statements on the request's session: `get_thought_with_origin()` (the thought, its proposal's time, and its conversation, in one outer join) and then `list_additions()`. This change keeps exactly that read, so the `GET` runs the same statements as before (four, with the user's upsert and lookup; a test pins that number and one statement each on `thoughts` and `thought_additions`), and it adds no new READ COMMITTED gap: the gap between the two reads was already there. Folding them into one statement is not this change's job, and would change `thought-appending`'s code and its query-count test.

`thought_view(thought, origin, additions)` takes `origin` as the store's `ThoughtOrigin` (or None) and `additions` as a list of the router's addition model, already built by `addition_view(row)`. `addition_view()` reads `id`, `added_at`, `undone`, `conversation_id`, `conversation_title`, and `proposal_id` by attribute, so it takes `thought-appending`'s `AdditionOut` dataclass and a labelled `Row` from the export's batched query alike. The task 1.1 tests sit at the end of `tests/test_thought_additions.py`, which has the fixtures for a thought with an origin and an addition; a small unit test of the two functions is in `tests/test_thought_view.py`.

**Alternatives:** one statement for thought, origin, and additions in the `GET` (rejected here: it changes `thought-appending`'s read and test for no gain to the export); `thought_view()` taking raw addition rows and calling `addition_view()` itself (rejected: the export builds the additions per thought from one batched query, and the `GET` from its own list; passing built models keeps one mapping for each).

### 19. The fresh-interpreter import check puts the backend folder on `sys.path`

Tasks 2.1, 2.9, and 2.10 run `uv run python -I -c 'import app.thoughts.export'` (and `app.user_data`, `app.main`) in `backend/`. That command fails before and after this change with `ModuleNotFoundError: No module named 'app'`: `app` is not an installed package, and `-I` leaves the working folder off `sys.path`. So the check runs `uv run python -I -c "import sys; sys.path.insert(0, '.'); import app.thoughts.export"` in `backend/`, which keeps the fresh, isolated interpreter and imports only the module named. `tests/test_export_lease.py` runs the three as a pytest check, and `tests/test_app_logging.py` imports `app.main` the same way.

**Alternatives:** plain `uv run python -c …` (rejected: it also works, but drops `-I`, so a stray module in the working folder or an environment variable could hide a cycle); installing the backend as a package (rejected: a packaging change for one check).

### 20. `stop_exports()` sits in `delete_user_by_id()` and `delete_user_content()`

Decision 15 names `delete_user_content()` and `delete_user_data()`. As built, `delete_user_data()` only calls `delete_user_by_id()`, and the demo cleanup loop (`delete_expired_demo_users()`) calls `delete_user_by_id()` directly. So the call goes in `delete_user_by_id()` and `delete_user_content()`, each importing `stop_exports` inside the function with decision 16's comment. That covers `DELETE /api/me`, `DELETE /api/demo/session`, and the cleanup loop through `delete_user_by_id()`, and `DELETE /api/me/content` through `delete_user_content()`. Every caller runs `stop_and_claim()` first, so the order of decision 15 holds: a delete refused with 409, or a visitor the loop skips, stops no export. A test removes the call from `delete_user_by_id()` and sees the account, "End demo", and cleanup cases fail.

**Alternatives:** the call in `delete_user_data()` only (rejected: the cleanup loop would miss it, and an export of an expired visitor would end with its count once the expiry check of decision 12 was the only guard); the call in each route and in the loop (rejected: four call sites for one rule).

### 21. The lease's clock, its owner, and the order of the two refusals

The design names one seam, `utcnow()`. The lease's monotonic clock is a second module function, `monotonic()`, wrapping `time.monotonic` and read through the module, so a test moves it by 61 seconds with `monkeypatch`. A `Lease` also carries its `user_id`, since `release(lease)` takes only the lease. It is a `@dataclass(eq=False)`, so it is compared and hashed by identity. `take_lease()` checks the four-lease limit before the running lease of that format, so with four open exports a fifth of either format gets "Too many of your exports are still open.", as task 2.5 expects, whether or not the newest of the four is still running. The route reads the expiry as `as_utc(user.expires_at)` whenever the user has one, rather than by auth mode: only demo users have an expiry.

**Alternatives:** patching `time.monotonic` itself (rejected: it would move every clock in the process, the event loop's included); checking the format first (rejected: the fifth JSON export would then get the "already running" message while four are open).

### 22. The empty JSON and Markdown files

The JSON writer's opening chunk ends with `"thoughts":[`; the first non-empty batch starts with `\n`, each later one with `,\n`; the closing chunk is `\n],"count":N}` when there were thoughts, else `],"count":0}`, and both end with one `\n`. So an empty store gives the literal `"thoughts":[]`, and every thought still sits on its own line. The Markdown file with no thoughts has the header, `Exported …`, and its rule as usual, then `No thoughts.`, one rule, and `End of export: 0 thoughts.`, treating "No thoughts." like a section. A summary line of only spaces and tabs follows the indent rule as it stands (four spaces become `&#32;` and three spaces), which no test needs.

**Alternatives:** an opening line ending in `[\n` (rejected: the empty file would hold `[\n\n]`, not `[]`).

### 23. The export's additions query labels `undone`

`additions_for()` selects `ThoughtAddition.id`, `thought_id`, `added_at`, `proposal_id`, `undone_at IS NOT NULL` labelled `undone`, and the conversation's `id` and `title` labelled `conversation_id` and `conversation_title`, so each row is a labelled `Row` that `addition_view()` takes as it takes the store's dataclass (decision 18). It orders by `added_at` and `to_position`, both descending, as `list_additions()` does, and groups by thought in Python. `export_thoughts()` drops each batch's rows before it yields, so only one batch is held at a time; task 2.7 measured a traced peak of about 3.8 MB for a 23 MB JSON file of 10,000 thoughts with 2,000-character raw texts.

### 24. A tab-led summary line keeps its reference, though markdown-it would not make it code

Task 2.3's by-hand check renders the two indented summary lines with `markdown-it` 14.1.0 in CommonMark mode. With the reference, both lines give a `<p>` whose text, entities decoded, is the stored line, leading space or tab included, and no `<code>`, as the first line of the quote and after a blank quote line. Written without the reference, the four-space line gives `<pre><code>` as decision 5 says, but the tab line does not: after `> `, the tab reaches only column 4, so it is two columns of indentation, and `markdown-it` gives `<p><b>x</b></p>` with the tab dropped. So for a tab the reference keeps the stored text rather than preventing a code block. The writer keeps the reference: the line then shows exactly as stored, and other renderers that expand the tab differently cannot turn it into code. The task's command `npx --yes -p markdown-it@14.1.0 node -e 'require("markdown-it")…'` cannot `require` the package (`npx` puts its bin folder on `PATH` but sets no `NODE_PATH`), so the same `node -e` script ran after `npm install --no-save markdown-it@14.1.0` in an empty scratch folder.

**Alternatives:** dropping the reference for a tab (rejected: the tab would vanish from the rendered text, and the text would no longer show as stored).

### 25. The running-server log check runs on port 8300 with its settings in the environment

Task 2.10 starts `uvicorn` on port 8765 with the settings in `backend/.env`. In this workspace the app runs on port 8300 and its databases are named `ff_f4_*`, and there is no `backend/.env`. So the check ran `uv run uvicorn app.main:app --port 8300 2> <log>` in `backend/`, with `DATABASE_URL` at a fresh `ff_f4_logcheck` database migrated to the current head (`460c92991076`), `AUTH_MODE=demo`, `SETUP_WIZARD=false`, and a generated `KEY_ENCRYPTION_KEY` in the environment, and no `--log-config`.

### 26. The section's heading, its reading of the refusal, and the extended page test

The card's title wraps an `<h2>Export</h2>` in `CardTitle`, as the Connectors card does, since `CardTitle` is a `div` and task 3.2 finds "Export" as a heading. The frame's `load` handler reads the shared error format with `readErrorBody()`, now exported from `lib/api.ts`, instead of a second copy of it. A `demo_session_expired` refusal also shows its message in the card's alert, as any error but `UnauthenticatedError` does (decision 10); the demo "session ended" view replaces the page at once, so the alert is not seen there. Frames are keyed by their place in the list, which never shrinks while the section is mounted.

Task 3.2 says a new `app/settings/page.test.tsx`. That file already exists, with the Connectors tests and a top-level mock of `@/lib/demo-settings` that answers `null`. So the task's tests are added to it, and the mock answers a `vi.hoisted` value that the demo-mode test sets and `afterEach` resets. The demo-mode render also needs `GET /api/me` answered for `DemoProvider`, and `next/navigation` mocked for the header's `DemoBar`.

**Alternatives:** a second page test file (rejected: two files would each mock `@/lib/demo-settings` for the same page); a local error parser in the section (rejected: it would repeat `readErrorBody()`).

### 27. The proxy's export check, its `no-store` test, and the login page test

The proxy refuses the export by its decoded segments whatever the method, not only for `GET`: the backend has no other method on that path, so a refusal there costs nothing and the check stays a single line. It keeps `no-store` when one comma-separated directive of the upstream `cache-control` is `no-store`, ignoring case, rather than when the string merely contains it. Task 4.1 asks that the session read is not called for a refused export; `route.test.ts` mocks `@/lib/session` with the real module and `readSession` wrapped in `vi.fn`, so every other test there runs as before. Task 4.3's page check is a new `app/login/page.test.tsx` that mocks `getAuthConfig()` to answer firebase mode and `FirebaseLogin` to record its props, and renders what the server component returns. `safeReturnTo()` also falls back when the URL parser throws, which a value starting with `/` does not do today.

**Alternatives:** a `GET`-only check (rejected: no gain, and a later `HEAD` or `POST` on the path would pass it); a substring test on `cache-control` (rejected: `no-store` inside another token would match); stubbing firebase environment variables for the page test (rejected: the page needs only the parsed config, and the mock keeps the test off the env parsing).

## Risks / Trade-offs

- [Not a snapshot: edits and deletes while the export runs show up in later batches] → Each thought is whole and current as of its batch. `exported_at` says when the export started. A user who wants a fixed copy exports while not editing. Deleting all content or the account, or ending the demo, during an export ends that export as failed (decision 15).
- [An export started in the instant between `stop_exports` and the delete's commit] → Its first batch can read the old rows and its later ones none, so it could end with a count. Accepted: it needs a press of "Download" within the few milliseconds of the delete's own transaction, and the user who just deleted knows their data is gone. `stop-and-spend-cap` accepts the same kind of gap for a new conversation.
- [Every export stopped by a delete or a demo session's end logs one ERROR line from `uvicorn`, "ASGI callable returned without completing response."] → Accepted: it has no traceback and no thought content, and the export's own INFO line says `outcome=failed error=ExportAborted`. The only way to end the download as failed is to close the connection without the last chunk, which is what `uvicorn` reports. The app's "Unhandled error" traceback is not logged (decision 8).
- [A large group of thoughts filed at one instant is reread on every batch] → `id` is not in the index (decision 2). Real stores file at distinct times, a multi-part confirm gives a handful of ties, and the scale checks (tasks 2.7 and 5.2) seed distinct times. A store where thousands share one `created_at` would still export correctly, only more slowly.
- [A bare web address in a summary becomes clickable in GFM viewers] → It loads nothing when the file is opened and shows exactly as stored; only a click follows it (decision 5).
- [The export is built on four planned changes (`thought-dates`, `thought-status`, `thought-appending` for the fields; `stop-and-spend-cap`, on `background-turns`' registry, for the claim the deletes check before `stop_exports()`)] → It is built after them. If their `GET` fields change before then, decision 3 makes the export follow; re-read decision 5 for the Markdown lines. If the deletes' claim check moves, decision 15's order follows it: `stop_exports()` stays after the last step that can refuse the delete.
- [The in-process lease does not hold across several backend processes] → The deployment is one process, as `background-turns` relies on. With more processes a user could run one export per format per process, which is harmless.
- [A slow but live client with very large batches may go a minute between chunks] → The lease is then seen as stale and a second export of that format may start. Both run to the end; that is the cost of a heartbeat, and it is harmless. Both stay in `LIVE`, so a delete stops both (decision 15), and no more than four exports of a user are ever connected (decision 7).
- [Browsers differ in what a frame shows for a JSON answer] → The handler reads a `pre` first, falls back to a generic message for any other text, and ignores only an empty document. Task 5.2 checks the refusal in Chrome and Firefox and records the versions.
- [A large file through the Node proxy] → The body is a stream end to end; the proxy test checks that parts arrive before the backend sends the last one. `undici`'s default body timeout (300 s with no data) only fires if the browser stops reading for that long.
- [The `app` loggers now write INFO lines to stderr] → One line per export and per demo cleanup that deletes something. The few other `app.*` INFO lines that exist (a model list that could not be read, an embedding that failed, a proposal call whose arguments did not fit) show too; they name a provider or a user id and an error code, never a key or thought content, and the log masking still applies (decision 17).
- [Escaped Markdown has backslashes in it] → A plain-text reader sees `\*` where the summary had `*`. Every Markdown viewer shows the text exactly, which is the point of the format; the JSON file is the exact copy for tools.
- [Memory per batch grows with raw text size] → 200 thoughts of at most 20,000 + 4,000 characters is under 5 MB in the worst case; task 2.7 measures a realistic store.

## Migration Plan

1. No migration. Backend and frontend can ship apart: a frontend without the section never calls the route, and a section on an old backend gets a 404 `not_found`, whose message the section shows in its alert.
2. Rollback: deploy the previous build. Nothing is stored by an export.

## Open Questions

None. Each choice is recorded in the decisions above.
