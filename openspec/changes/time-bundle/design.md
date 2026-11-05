## Context

See `proposal.md` for why. This change sits on top of other changes and plans against their specs and design.

Built on this branch, and shaping the approach:

- `thought-dates`: `when` (`{start, end, time_zone}`) parsed by one function, `parse_when()` in `app/thoughts/dates.py`, into five columns (`starts_on`, `starts_at`, `ends_on`, `ends_at`, `time_zone`), and back by `when_of()`. One clock, `utc_now()`, which tests replace. `when_choices` on proposal parts. `list_upcoming()` in `app/thoughts/store.py` and `GET /api/thoughts/upcoming?from=`. `dated_from`/`dated_to` on the search tool, with a plain select in date order when there is no query. `components/chat/date-fields.tsx` used by the proposal card and the sheet's edit mode, which sends `when` only when the start or end changed.
- `background-turns`: the backend runs as one process (`backend/Dockerfile` `CMD`). The lifespan in `app/main.py` releases stale turn claims before serving (`release_stale_turns`), opens setup, starts the demo cleanup loop with `asyncio.create_task`, and on exit runs `running.shutdown(5.0)`, cancels the cleanup loop, and disposes the engine. `running.shielded()` runs a step to its end even when the caller is cancelled.
- `auth-modes`: demo mode forces some features off and refuses settings that turn them on (`MCP_ENABLED=true`, `SETUP_WIZARD=true`) in `Settings.check_auth_mode()`. The Next.js catch-all `app/api/[...path]/route.ts` attaches the user's credential to every call and answers 401 without one; `proxy.ts` lets `/api/` through and runs every request in demo mode through `demoRequest()`.
- `self-hosting-setup`: the setup token is stored as a SHA-256 hash and compared with `hmac.compare_digest`; `.env.example` and `docs/setup.md` list every operator setting.
- `app/crypto.py`: `encrypt_secret()` / `decrypt_secret()` with AES-GCM and associated data bound to a user id.
- `app/user_data.py`: every user-owned table cascades from `users`; "Delete content" deletes thoughts, search indexes, and conversations.

Planned below this change, and treated as in place:

- `thought-status`: `thoughts.status` (`open`/`done`), `set_status()`, marks on proposal parts, the status card ("Mark done: <title>"), and the Upcoming page listing only open thoughts (its `upcoming-thoughts` delta).
- `thought-library`: `app/log_masking.py` drops the query string from every `uvicorn.access` record by replacing `args[2]` (decision 4 there). This change extends that same rewrite.
- `thought-export`: the export writes each thought's `when` through the shared `thought_view()`, so it carries `repeat` and `reminders` with no change there.
- `stop-and-spend-cap`: `stop_turns()` before the deletes in `app/user_data.py`; nothing here touches it.

No new service is allowed: one backend process, Postgres as the only store.

## Goals / Non-Goals

**Goals:**

- One small, general job runner that feature 7 can reuse without changing it.
- A reminder is shown once, never twice, whatever restarts happen.
- One `when` shape still carries everything about a thought's date: the date, its repeat, and its reminders.
- A repeating thought is one thought, one row, one status.
- The feed token is never stored, logged, or sent anywhere but to the user who made it.

**Non-Goals:**

- Done for one occurrence of a repeating thought, and skipping or moving one occurrence (exceptions). Decision 6.
- Repeat rules beyond the subset: "the last Friday of the month", "the second Tuesday", several days of the month, or hourly repeats.
- Email (SMTP), SMS, chat apps, or any other reminder channel. Web push is the only one beside the in-app list.
- A default reminder for every dated thought, a per-user "untimed reminders at" hour, snooze, and quiet hours.
- Alarms (`VALARM`) in the calendar feed; the app sends its own reminders.
- Importing a calendar, or two-way sync. The feed is read-only.
- An operator switch to turn the feed off; it is off only in demo mode.
- More than one backend process, and moving the demo cleanup loop into the runner. Both can come later.
- Showing a repeat in the library rows or the sources list.
- The weekly review and resurfacing jobs themselves (feature 7).

## Decisions

### 1. One job runner, in the backend process, with its schedule in Postgres

`app/jobs/runner.py` holds a `Job` (`name`, `every: timedelta`, `run: async (JobContext) -> None`, `timeout`) and one loop task. `app/jobs/__init__.py` builds the list from the settings (`build_jobs(settings)`): this change registers `reminders` (every 30 seconds) and `prune-notifications` (every 24 hours), both added with the reminders (task group 3). Feature 7 adds its own entries to this list.

A new table `scheduled_jobs` keeps one row per job: `name TEXT PRIMARY KEY`, `next_run_at TIMESTAMPTZ NOT NULL`, `running_since TIMESTAMPTZ NULL`, `last_finished_at TIMESTAMPTZ NULL`, `last_error TEXT NULL`. At start the runner inserts a row for each job that has none, with `next_run_at` now. A row whose job is no longer registered is left alone.

The loop, while not stopping:

1. `now = utc_now()` (the clock from `app/thoughts/dates.py`, so tests fix it).
2. For each job, in list order, claim it: `UPDATE scheduled_jobs SET next_run_at = :now + every, running_since = :now WHERE name = :name AND next_run_at <= :now`. One row changed means this loop owns the run. Run it under `asyncio.timeout(job.timeout)`, with a `JobContext(sessionmaker, now)`. Then set `running_since = NULL`, `last_finished_at`, and `last_error` (the exception's class name, or null).
3. Sleep until the earliest `next_run_at`, at most 30 seconds, or until `stop()` sets the stop event.

Jobs run one after another in the one task. A job opens its own sessions from the context, as the turn does. `run_due(now)` does steps 1 and 2 once; tests call it directly instead of starting the loop.

The runner gives each due run at least once, never two at the same time. A job that must not repeat its effect makes its writes idempotent itself (decision 9). The claim also keeps a second process, started by mistake, from running the same job at the same moment, as `TURN_CLAIM_TIMEOUT` guards turns.

**Alternatives:** APScheduler (rejected: a dependency with its own job store and its own idea of misfires, for two interval jobs); a worker container or host cron (rejected: a second service, which this project avoids); `pg_cron` (rejected: an extension not every Postgres has, and the work is Python); one ad hoc loop per feature, like the demo cleanup (rejected: each would redo its own shutdown, catch-up, and error handling, and none would survive a restart's timing).

### 2. Catch-up, failures, and shutdown in the runner

- **Catch-up.** A job whose `next_run_at` passed during downtime runs once at start, not once per missed interval: the claim sets the next run from now, not from the missed time. What a job missed is the job's business (decision 9 caps reminders).
- **Failure.** An exception or a timeout is logged with the job name (`logger.exception`), `last_error` gets the class name, and the job is next due at `now + min(every, 5 minutes)`. The loop goes on with the next job. A failing job never stops the others, and never loops hot.
- **Crash.** A row with `running_since` set at start belongs to a run that never finished. The start sets its `next_run_at` to now, so it runs again at once. With one process, as for turn claims, every such row is from a stopped process.
- **Shutdown.** The lifespan exit calls `runner.stop(5.0)` first, before `running.shutdown()`. It sets the stop event, waits up to 5 seconds for a running job to finish, then cancels it. A cancelled job's open transaction rolls back. Under `running.shielded()`, the runner then sets that job's `next_run_at` back to its claim time and clears `running_since`, so the next start runs it again.
- **Start.** The lifespan starts the runner after `release_stale_turns` and `open_setup`, and only when `JOBS_ENABLED` is true (the default). Tests set it false, except the runner's own tests. The runner starts in demo mode too: demo users get in-app reminders.

**Alternatives:** retry a failed job at once (rejected: a job that fails on every run would loop); keep `next_run_at` as claimed after a cancel (rejected: a weekly job stopped by a deploy would wait a week).

### 3. The repeat is a small shape of our own inside `when`

```
"when": {
  "start": "2026-11-09", "end": null, "time_zone": "Europe/Oslo",
  "repeat": {"every": "week", "interval": 1, "weekdays": ["mon"], "until": null},
  "reminders": [0, 1440]
}
```

- `every`: `day`, `week`, `month`, or `year`.
- `interval`: 1 to 99, default 1. "Every other week" is `week` with 2.
- `weekdays`: only with `week`: a list of `mon` … `sun`. The start's weekday is always added; a missing or empty list means the start's weekday only.
- A `month` repeat falls on the start's day of the month, a `year` repeat on the start's month and day. A month without that day is skipped, as RFC 5545 and calendar apps do: a repeat from 31 January skips February.
- `until`: an optional last day, `YYYY-MM-DD`, not before the start day. An occurrence on that day still counts.
- A repeating date's end, when it has one, must be on its start day ("10:00 to 11:00 every Tuesday"). So an occurrence never spans days, and two occurrences never overlap.
- The start is the first occurrence.

`parse_when()` checks `repeat` with the rest and refuses it naming `when` (`when: the repeat …`). `repeat: null` or a missing key means no repeat. A `when_choices` choice takes the same fields as `when`, apart from the zone.

**Alternatives:** an RRULE string on the wire (rejected: the model writes bad RRULEs, and the card and the sheet would have to parse one); the full RRULE (rejected: `BYSETPOS` and `BYDAY=-1FR` need a much harder form, for rare cases; listed as a non-goal); a weekday bit mask on the wire (rejected: unreadable for the model).

### 4. Four columns for the repeat

`thoughts` gains `repeat_every TEXT NULL` (check constraint `repeat_every IN ('day','week','month','year')`, named `repeat_every` so the convention makes it `ck_thoughts_repeat_every`, added in batch mode as `thought-status` does), `repeat_interval SMALLINT NULL`, `repeat_weekdays TEXT NULL` (canonical `mon,wed`, Monday first), and `repeat_until DATE NULL`. All are null when the thought does not repeat. `DateColumns` gains the four fields, so `parse_when()` and `when_of()` stay the one pair of converters. No new index: the existing `(user_id, starts_on)` index still narrows by start, and a user's repeating thoughts are few.

**Alternatives:** one JSON column (rejected, as `thought-dates` decision 1 rejected it: the Upcoming and search queries need `repeat_every IS NOT NULL` and `repeat_until`); a separate `thought_repeats` table (rejected: one-to-one data with a join on every date read).

### 5. Expanding a repeat: `dateutil.rrule`, one entry per thought

`app/thoughts/repeats.py` turns the columns into a `dateutil.rrule.rrule` (`DAILY`/`WEEKLY`/`MONTHLY`/`YEARLY`, `interval`, `byweekday` for weeks, `bymonthday` for months, `bymonth` and `bymonthday` for years, `wkst=MO`, `until`, `dtstart` the start day) and answers two questions: the first occurrence that ends on or after a day (`next_on_or_after`), and the first occurrence inside a range of days (`first_between`). It also writes the repeat as text: `every week on Mon`, `every 2 weeks on Mon, Thu`, `every month on day 15`, `every year on 3 Nov`, `every day`, with `until 2026-12-31` when it has a last day.

A repeating thought shows as **one entry**, at one occurrence, never as one entry per occurrence:

- **Upcoming.** `list_upcoming()` runs its query for thoughts that do not repeat (as now, plus `repeat_every IS NULL`), and a second query for the user's open repeating thoughts whose `repeat_until` is null or not before `from`, at most 1,000, by start. For each, it takes `next_on_or_after(from)`, and drops one with none. It merges both lists in date order by the shown occurrence, then filing time, and cuts at 200 (`more` as now). Each item gains `occurs: {start, end}`, the occurrence shown; for a thought that does not repeat it equals the stored start and end. The page groups by `occurs.start` and shows the repeat text under the title.
- **Search by the thought's date.** Before the main query, `search_thoughts()` loads the user's repeating thoughts that could fall in the range (`starts_on <= :dated_to`, `repeat_until` not before `:dated_from`) and keeps the ids with a `first_between()` occurrence. The date filter becomes `(repeat_every IS NULL AND <overlap test>) OR id IN (:ids)`. With a query, ranking works as now inside that filter. With no query, the plain select returns both kinds, and the date order is applied in Python by each thought's shown occurrence (`first_between()`), then cut at the limit. `format_search_result()` prints the shown occurrence after `on`, then `· repeats every week on Mon`.

`dateutil` is pure Python and also comes with `icalendar` (decision 13), so the rule the app expands is the same rule a calendar app reads from the feed.

**Alternatives:** expand into one entry per occurrence (rejected: "every day" would fill the 200-item page and the search result, and spend the model's tokens on copies); our own expansion code (rejected: month-end and leap-day rules would differ from what calendar apps do with the same feed); materialise occurrences in a table (rejected: a table to keep in step on every edit, for a few rows per user).

### 6. Done ends the series

Status stays one column per thought. Marking a repeating thought done (from a status card or the sheet's toggle) works as for any thought: it leaves the Upcoming page, its reminders stop (decision 8), and it leaves the feed. Setting it back to open brings it all back from the next occurrence.

So one occurrence is never marked done. The prompt says so (decision 7), and the status card for a repeating thought adds a line, "Marking it done stops it repeating." `thought-status`' card and confirm otherwise do not change; the card reads the thought's `repeat` from its `target` fields.

**Alternatives:** a table of done occurrences (rejected: a per-occurrence state on the Upcoming page, the feed, and reminders, for a brain-dump app whose repeating items are mostly reminders to do something); Done moves the start to the next occurrence and keeps the thought open, as some to-do apps do (rejected: it silently rewrites the stored date, a reopen cannot undo it, and `thought-status`' rule that a status change touches nothing else would break).

### 7. The model, the card, and the sheet

**Tool schema and prompt.** `DATE_SCHEMA` gains `repeat` and `reminders`, both optional. The `when` description adds:

- Give `repeat` only when the user says the thing repeats ("every Monday", "each month on the 1st", "every other week", "daily"). Then the start is the first occurrence, today or later, and today counts: "every Friday" said on a Friday starts today. A repeat never gets two choices.
- Give `reminders` only when the user asks to be reminded: minutes before the start, `0` for "at the time". "Remind me" with no time gives `[0]`. A day with no time is reminded at 09:00, so "remind me the day before" is `[1440]`.

The status lines of the prompt add: a repeating thought is not marked done because one occurrence happened; mark it done only when the user says it has ended or they stopped it.

**Parsing.** `parse_proposal()` checks `repeat` and `reminders` with the date. A bad `repeat` is dropped and the date is kept; bad `reminders` are dropped and the rest is kept (spec: "Not valid from the model"), as a bad `when` is dropped and the part kept. `held_proposal_note()`'s `Date:` line adds `, repeats every week on Mon` and `, reminders 0 and 1440 minutes before`.

**Confirm and `PATCH`.** `when` stays one value: the object replaces the date, its repeat, and its reminders together. A missing `repeat` key is no repeat, and a missing `reminders` key is no reminders. Merge keeps the first part's `when` whole.

**Fields.** `date-fields.tsx` gains two small parts, used by the card and the sheet alike:

- `repeat-fields.tsx`: a select (Does not repeat, Every day, Every week, Every month, Every year), an "every N" number, weekday toggles for weeks (the start's weekday on and locked), and an optional "Until" date. A repeat with an end on another day is not offered: choosing a repeat sets the end day to the start day.
- `reminder-fields.tsx`: up to five rows, each a select. With a time: At the time, 5, 10, 15, 30 minutes, 1 or 2 hours, 1 or 2 days, 1 week before. With no time: On the day (09:00), 1 day, 2 days, 1 week before. "Add reminder" and a remove button per row. A stored value with no preset shows as "N minutes before".

**The zone on a sheet save.** `thought-dates` decision 13 sends `when` only when the start or end changed, with the browser's zone. Now `when` is also sent when the repeat or the reminders changed. When only those changed, the sheet sends the stored `time_zone`, not the browser's, so adding a reminder from another zone does not move the times.

**Alternatives:** `repeat` and `reminders` as part fields beside `when` (rejected: the request names `when.repeat`, clearing the date must clear both, and one value keeps `PATCH`'s missing-key rules simple); a separate reminders endpoint (rejected: a second way to change a thought's date data, and the card would need two writes).

### 8. Reminders are rows with their next fire time

`thought_reminders`: `id`, `user_id` (cascade), `thought_id` (cascade), `offset_minutes INTEGER NOT NULL` (0 to 40,320, four weeks), `next_fire_at TIMESTAMPTZ NULL`, `occurrence_on DATE NULL`, `occurrence_at TIME NULL`. Unique `(thought_id, offset_minutes)`; index on `next_fire_at` where it is not null (Postgres only, declared like the date index). At most five per thought.

`sync_reminders(session, thought, now)` in `app/reminders.py` rewrites a thought's rows from its `when` and status: one row per offset; `next_fire_at` is the fire time of the earliest occurrence whose fire time is after `now`, and `occurrence_on`/`occurrence_at` are that occurrence. The fire time is the occurrence's start in the thought's zone (`ZoneInfo(time_zone)`), at 09:00 for a day with no time, minus the offset, as UTC. A done thought, a thought with no date, and a series that has ended get `next_fire_at = NULL`. A fire time already past when the reminder is set is skipped: "1 day before" set on a dinner tonight sends nothing for tonight.

It is called in the same transaction as every write that can change the answer: confirm (`store_thought()`), `update_thought()` when `when` is in the patch, and `set_status()`. A delete cascades the rows.

A local time that does not exist (a spring-forward gap) resolves with `fold=0`, as `zoneinfo` does: 02:30 on that day fires at 03:30.

**Alternatives:** scan every dated thought on each tick (rejected: work grows with all users' thoughts, and "already sent" would need its own record); reminders as JSON on the thought (rejected: no index on the next fire time); a fixed 08:00 or a per-user hour for untimed days (09:00 chosen; per-user is a non-goal).

### 9. The reminder job delivers once and catches up with a cap

Every 30 seconds, the `reminders` job runs batches until nothing is due:

1. In one transaction, select up to 200 rows with `next_fire_at <= now`, `ORDER BY next_fire_at`, `FOR UPDATE SKIP LOCKED` (ignored on SQLite), with their thought.
2. For each row, find the **latest** occurrence whose fire time is at or before `now` (after downtime this can be later than the stored one). When `now` minus that fire time is at most 24 hours, insert a notification (decision 10) with the key `reminder:<reminder id>:<occurrence start>` and `ON CONFLICT (user_id, dedupe_key) DO NOTHING`. Older than 24 hours, insert nothing.
3. Move the row on: the next occurrence whose fire time is after `now`, or null.
4. Commit. Then hand the notifications this batch actually inserted to the push sender (decision 11).

So one reminder sends at most one notification per run, a backlog of daily occurrences becomes one notification, and a reminder late by more than a day is dropped. A batch is capped at 200, and a run at 10 batches; the next run, 30 seconds later, goes on.

The notification and the move commit together. A crash before the commit redoes the batch; the unique key makes a redo after the commit insert nothing. Push is sent only after the commit, so a crash between the commit and the push loses that push, never doubles it; the in-app notification is there either way.

**Alternatives:** send every missed occurrence (rejected: a week down would send seven "bins" reminders); no cap on lateness (rejected: "dinner at 19:00" three days late is noise); a separate `sent_reminders` table (rejected: the notification row with its unique key is that record); push before the commit (rejected: a crash after the push would push again).

### 10. Notifications: one table, a list page, and a polled count

`notifications`: `id`, `user_id` (cascade), `thought_id` (cascade, nullable for later kinds), `kind TEXT` (`reminder`; feature 7 adds its own kinds), `title TEXT` (the thought's title when it fired), `body TEXT` (the occurrence, for example `Fri 2 Oct, 19:00 · in 1 hour` or `Mon 9 Nov · today`, written by the server in English, as `lib/dates.ts` writes dates), `dedupe_key TEXT`, `created_at`, `read_at NULL`. Unique `(user_id, dedupe_key)`; index `(user_id, created_at)`. Deleting a thought deletes its notifications, so a title never outlives "Delete content".

API, all owner-scoped:

- `GET /api/notifications?limit=50` → `{items: [{id, kind, title, body, thought_id, created_at, read_at}], unread}`, newest first, `limit` 1 to 100.
- `GET /api/notifications/unread` → `{unread}`, for the badge.
- `POST /api/notifications/read` with `{ids: [...]}` (at most 200) → `{unread}`. Ids that are unknown or another user's are skipped; the answer is the same either way.

The sidebar gets "Notifications" under "Upcoming", with the unread count as a badge and in its accessible name ("Notifications, 3 unread"). It loads the count on mount, every 60 seconds while the page is visible, and on window focus. `app/app/notifications/page.tsx` lists the newest 50; opening the page marks the listed unread ones read (one `POST`), and they show as read the next time. An item opens its thought in the side sheet over the page, as the Upcoming page does.

The `prune-notifications` job deletes notifications older than 30 days, once a day.

**Alternatives:** a toast or the browser `Notification` API while the tab is open (rejected: a second channel to test; push covers the closed tab when the operator turns it on); server-sent events for the count (rejected: one more long-lived connection per tab for a number that can be a minute late); the occurrence as structured data the browser formats (rejected: push needs the same text from the server anyway).

### 11. Web push: VAPID keys from the environment, encrypted subscriptions, known push services only

**Settings.** `WEB_PUSH_VAPID_PUBLIC_KEY`, `WEB_PUSH_VAPID_PRIVATE_KEY` (base64url, as `python -m app.notifications.push keys` prints them), and `WEB_PUSH_SUBJECT` (a `mailto:` or `https:` address, required by VAPID, default `mailto:admin@localhost`). Push is on only when both keys are set. One key without the other stops the backend at start with a message naming the missing one. Demo mode refuses either key, as it refuses `MCP_ENABLED=true`. The setup script does not generate them; `docs/notifications.md` shows the command.

**Subscriptions.** `push_subscriptions`: `id`, `user_id` (cascade), `endpoint_hash TEXT UNIQUE` (SHA-256 of the endpoint URL), `secret` (the subscription JSON, `{endpoint, keys: {p256dh, auth}}`, encrypted with `encrypt_secret()` bound to the user id and the label `web-push`), `created_at`, `last_sent_at`. At most 10 per user; an eleventh replaces the oldest. No endpoint ever returns a subscription.

- `GET /api/notifications/push` → `{enabled, public_key, subscribed: false}`; with `?endpoint_hash=` it says whether this browser's subscription is stored. The browser hashes its own endpoint with `crypto.subtle.digest`, so the endpoint itself is not in the URL.
- `POST /api/notifications/push/subscriptions` with the browser's `PushSubscription.toJSON()` → 204. 404 `not_found` when push is off.
- `DELETE /api/notifications/push/subscriptions` with `{endpoint}` → 204, also when it is unknown.

**Allowed endpoints.** The backend sends an HTTP request to whatever endpoint is stored, so a stored `http://db:5432/` would be a server-side request to the operator's network. A subscription is refused (422 `validation_error` naming `endpoint`) unless its endpoint is `https` on a known push service host: `fcm.googleapis.com`, `updates.push.services.mozilla.com`, `web.push.apple.com`, or a subdomain of `push.apple.com` or `notify.windows.com`. The list is in code.

**Sending.** `pywebpush` (`webpush()`, sync) runs in `asyncio.to_thread` with a 10-second timeout per send, TTL 3,600 seconds, one send at a time. The payload is `{"title", "body", "url": "/app/notifications?thought=<id>"}`, which the browser decrypts; the push service sees only the encrypted bytes. A 404 or 410 answer deletes that subscription. Any other failure is logged with the push service's host and status code only, never the endpoint, and is not retried. `last_sent_at` is set on success.

**Browser.** `public/sw.js` handles only `push` (show the notification) and `notificationclick` (focus an open tab of the app or open the `url`). It holds no token and makes no request. `proxy.ts`'s matcher leaves `/sw.js` out, so it loads without a session. The Settings section "Notifications" shows "Browser notifications" only when `enabled` is true, with four states: not supported by this browser, blocked in the browser's settings, on, off. Turning it on asks for permission, registers `sw.js`, subscribes with the public key, and posts the subscription; turning it off unsubscribes and sends the `DELETE`.

**Alternatives:** our own RFC 8291 encryption with `cryptography` and `httpx` (rejected: more security code to own than one maintained library); a push relay (rejected: an extra service); store subscriptions in plain text (rejected: anyone who reads the table could push to the user's devices, and `crypto.py` makes encryption one call); a payload with only an id that the service worker fetches (rejected: the worker would need the session, and a logged-out browser would show nothing); allow any `https` host (rejected: an internal service with TLS is still reachable).

### 12. The feed token: one per user, shown once, stored hashed

`calendar_feeds`: `user_id` primary key (cascade), `token_hash TEXT UNIQUE` (SHA-256 hex), `created_at`, `last_fetched_at NULL`. The token is `secrets.token_urlsafe(32)` (43 characters, 256 bits).

- `GET /api/settings/calendar-feed` → `{active, created_at, last_fetched_at}`.
- `POST /api/settings/calendar-feed` → 201 `{path: "/api/calendar/<token>.ics"}`. It makes a new token and replaces any old one in one write, so the old address stops at once. This is the only answer that holds the token.
- `DELETE /api/settings/calendar-feed` → 204, also when there is none.

Settings shows "Calendar feed": when off, "Make a feed address"; when on, when it was made and last fetched, "Regenerate" and "Turn off" (each with a confirmation that says the old address stops working). After a `POST`, the section shows the full address (`window.location.origin` plus `path`) once, with Copy and a `webcal://` link, and says it will not be shown again. In demo mode the section is not shown and all three routes answer 404 `not_found`.

**Alternatives:** store the token encrypted and show it any time (rejected: a token that can be shown again can leak again; regenerating is one click); a token per feed with several feeds per user (rejected: no use for more than one); the token in a query string (rejected: same exposure as the path, and some calendar apps drop query strings).

### 13. The feed request: its own Next.js route, a rate limit, and no token in the log

**Route.** `frontend/app/api/calendar/[file]/route.ts` handles only `GET`. A static segment wins over the catch-all, so `/api/calendar/...` never reaches `app/api/[...path]/route.ts` and its credential. The route checks the file name against `^[A-Za-z0-9_-]{43}\.ics$` (else 404 `not_found` without calling the backend), forwards `GET /api/calendar/<file>` to `BACKEND_URL` with no `Authorization`, no cookies, and only `if-none-match`, and passes back the status, `content-type`, `etag`, `cache-control`, `retry-after`, and the body. In demo mode it answers 404 at once. `proxy.ts` already lets `/api/` through outside demo mode; in demo mode it lets `/api/calendar/` through to the route's 404 without starting a session. A failed backend call is logged without the path.

**Backend.** `GET /api/calendar/{file}` in `app/routers/calendar.py` is the one route with no user dependency. It looks up `sha256(token)`; an unknown token, a malformed name, or demo mode answers 404 `not_found` with the body every unknown address gets. It sets `last_fetched_at`.

**Rate limit.** `app/rate_limit.py` is a token bucket like `frontend/lib/rate-limit.ts`, in this process's memory: 60 requests per hour per token hash, and 120 per hour shared by all requests whose token is unknown. Over either, 429 `rate_limited` with `Retry-After`. Calendar apps poll every few minutes to a day, so 60 an hour leaves room. The shared bucket for unknown tokens slows a guess loop without affecting real feeds; guessing 256 bits is out of reach anyway.

**Caching.** The answer has `Content-Type: text/calendar; charset=utf-8`, `Cache-Control: private, max-age=300`, and an `ETag` (SHA-256 of the body); `If-None-Match` with that tag answers 304.

**Access log.** The access-log rewrite from `thought-library` (which already replaces `args[2]` of each `uvicorn.access` record with the path before `?`) also replaces a path starting `/api/calendar/` with `/api/calendar/[REDACTED].ics`. The Next.js server writes no access log.

**Alternatives:** an exception for `calendar` inside the catch-all (rejected: one shared route deciding per path whether to attach a credential is easy to break); a route outside `/api/`, such as `/calendar/<token>.ics` (rejected: the request names `/api/calendar/`, and `proxy.ts` would need a public-page rule); the rate limit in the Next.js route (rejected: the backend is where the token is known, and it is one process).

### 14. What the feed holds

The feed is built with `icalendar`: `VERSION:2.0`, `PRODID:-//Focus Funnel//Thoughts//EN`, `CALSCALE:GREGORIAN`, `X-WR-CALNAME:Focus Funnel`, `REFRESH-INTERVAL;VALUE=DURATION:PT1H`, and `X-PUBLISHED-TTL:PT1H`. It lists the user's **open** dated thoughts whose last day (or `repeat_until`, or no end for a repeat with none) is no more than 30 days before today in UTC, at most 2,000, latest start first. Each is one `VEVENT`:

- `UID:<thought id>@focus-funnel`, `DTSTAMP` and `LAST-MODIFIED` from `updated_at`.
- `SUMMARY` the title, `DESCRIPTION` the summary, `CATEGORIES` the category when there is one.
- A day with no time: `DTSTART;VALUE=DATE`, `DTEND;VALUE=DATE` the day after the end day (or the start day).
- A time: `DTSTART;TZID=<time_zone>` and `DTEND;TZID=…` when there is an end; no `DTEND` without one. `Calendar.add_missing_timezones()` adds a `VTIMEZONE` for each zone used, so repeats keep their local time across daylight saving.
- A repeat: `RRULE` with `FREQ`, `INTERVAL`, `BYDAY` (weeks), `BYMONTHDAY` (months), `BYMONTH` and `BYMONTHDAY` (years), `WKST=MO`, and `UNTIL` (the date, or for a timed repeat the end of that day in the thought's zone, as UTC).

It holds nothing else: no raw text, tags, reminders, status, user id, email, or link back to the app. A done thought is not in it, as it is not on the Upcoming page.

**Alternatives:** write the iCalendar text by hand (rejected: line folding, escaping, and `VTIMEZONE` are easy to get wrong, and the library is small and pure Python); times as UTC (`Z`) with no `VTIMEZONE` (rejected: a weekly 19:00 would move by an hour across daylight saving); include done thoughts (rejected: the feed follows the Upcoming page); all past events (rejected: the feed would grow without end; 30 days back keeps last month visible).

### 15. Spec deltas and archive order

New requirements are added wherever possible, so this change does not rewrite other changes' blocks:

- `thought-store`, `thought-filing`, `conversation-agent`, `thought-search`, `thought-detail-view`, `chat-interface`, and `account-data-deletion` get only added requirements. The added `thought-search` requirement refines "Filters and order" for repeating thoughts, without copying it.
- `upcoming-thoughts` "The Upcoming page lists dated thoughts from today on" must change: it says a thought dated before today is not listed, which a weekly thought started last month would break. The delta is `thought-status`' version, with the repeating rule and two scenarios added. **Archive after `thought-status`.**
- `user-auth` "Backend API requires a valid access token" must name the feed as an exception. The delta is `auth-modes`' version with the feed added. **Archive after `auth-modes`.**

If either base delta changes before it is archived, copy the new version into this delta again.

## Risks / Trade-offs

- [A reminder is up to about a minute late: a 30-second job, a 30-second sleep at most] → Accepted for reminders set in minutes. The interval is one number in the job list.
- [A crash between the commit and the push loses that push] → Accepted: the in-app notification is there, and a doubled push is worse than a lost one.
- [A user with more than 1,000 repeating thoughts] → Upcoming reads the first 1,000 by start; the rest are found by search. Not expected for a brain dump.
- [Months without the 31st, and 29 February] → Skipped, as calendar apps skip them. The repeat text says "on day 31", and the Upcoming page shows the real next occurrence.
- [Calendar apps that ignore `VTIMEZONE` or `REFRESH-INTERVAL`] → The `TZID` is an IANA name, which the large clients read; refresh timing is up to the client.
- [The feed address leaks (a shared screenshot, a synced calendar)] → It shows titles and summaries of dated thoughts only; "Regenerate" or "Turn off" ends it at once.
- [Push services change hosts] → The list is in one place; a refused subscription says the browser's push service is not supported, and in-app notifications still work.
- [The token passes through the Next.js server's memory and the calendar app's storage] → Unavoidable for a subscribable feed. It never reaches the access log, the database, or the browser after the one answer.
- [A second backend process started by mistake] → Jobs are claimed in the database, and notifications have a unique key, so nothing is sent twice; `background-turns` still rules the second process out.
- [A job that hangs] → `asyncio.timeout` per job (60 seconds by default), recorded as a failure.

## Migration Plan

1. One Alembic revision per task group that adds data, chained in group order on top of the head left by the changes below this one (keep the single-head test passing): group 1 `scheduled_jobs`; group 2 the four nullable repeat columns and the check constraint on `thoughts` (batch mode); group 3 `thought_reminders` and `notifications`; group 4 `push_subscriptions`; group 5 `calendar_feeds`. No backfill: no thought repeats or has reminders yet.
2. The task groups can ship one at a time, as separate pull requests. The runner (group 1) ships with an empty job list; it is harmless alone, and group 3 adds the first jobs. Old frontends send `when` without `repeat` or `reminders`, which stores neither, and ignore the new keys in answers.
3. New dependencies: `python-dateutil` (group 2), `pywebpush` (group 4), `icalendar` (group 5). The offline bundle picks them up from `uv.lock`.
4. Rollback: downgrade drops the columns and tables. Repeats, reminders, notifications, subscriptions, and feeds are lost; the dates stay. A calendar app subscribed to the feed gets 404 and keeps its last copy.
