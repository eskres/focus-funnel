## Why

`thought-dates` gave a thought a date, and left three things out on purpose (its design, Non-Goals): reminders, repeating dates, and a calendar export. A dated task that nobody is reminded of is easy to miss. "Take the bins out every Monday" can only be filed as one Monday. And a user who lives in their phone's calendar cannot see their dated thoughts there. The stored time zone was kept so these could come later. This change adds all three, sized for a self-hoster: no new service, one backend process, Postgres as the only store.

## What Changes

- **A small job runner in the backend process.** One asyncio loop, started and stopped in the lifespan beside `background-turns`' running turns. Each job has a name and an interval. When each job is next due is kept in Postgres, so a restart neither loses nor repeats a run, and a job missed during downtime runs once at start. Reminders are its first job; feature 7 (weekly review, resurfacing) adds its own jobs to the same runner. It can be turned off with `JOBS_ENABLED=false`.
- **Repeating dates.** A dated thought can repeat: every N days, weeks (on one or more weekdays), months (on the start's day of the month), or years, with an optional last day. The `when` shape gains `repeat`, for example `{"every": "week", "interval": 1, "weekdays": ["mon"], "until": null}`. The start is the first occurrence. A repeating date's end, when it has one, is on its start day.
  - The model proposes a repeat only when the user says the thing repeats ("every Monday", "each month on the 1st"). The card and the sheet show the repeat, and the user can change or clear it.
  - The Upcoming page lists a repeating thought once, at its next occurrence. A search by the thought's date finds a repeating thought when one of its occurrences falls in the days asked for, and shows that occurrence.
  - Status stays one value per thought. Marking a repeating thought done ends the series. The model does not mark a repeating thought done because one occurrence happened, and the status card says the thought stops repeating.
- **Reminders.** A dated thought can have up to five reminders, each a number of minutes before its start (0 for "at the time"). A day with no time counts as starting at 09:00 in the thought's zone. A repeating thought reminds before each occurrence. The model adds a reminder only when the user asks to be reminded; the card and the sheet set, change, or remove them.
  - A due reminder becomes an in-app notification: a "Notifications" link in the sidebar with an unread count, and a page listing them, each opening its thought.
  - Delivery is once: a restart in the middle of a run does not send a reminder twice. After downtime, each reminder sends at most its latest missed occurrence, and only when it is at most 24 hours late.
  - A done or deleted thought sends no more reminders.
- **Web push, only when the operator turns it on.** With `WEB_PUSH_VAPID_PUBLIC_KEY` and `WEB_PUSH_VAPID_PRIVATE_KEY` set (off by default, refused in demo mode), Settings offers "Browser notifications". The browser's push subscription is stored per user, encrypted, and never returned. A reminder then also shows as a browser notification. Push goes only to known push services. No other channel is added: SMTP stays out.
- **A calendar feed.** In Settings, a user can make a private feed address, `/api/calendar/<token>.ics`, to subscribe to in a calendar app. The token is random, shown once, and stored only as a hash. "Regenerate" replaces it, and "Turn off" revokes it; the old address stops working at once.
  - The feed holds the user's open dated thoughts, with repeats as repeat rules: title, summary, and category, and nothing else. No reminders, tags, raw text, or account details.
  - The feed request needs no login: the token is its credential. The Next.js server forwards only that path to the backend, without a session. Requests are rate-limited, the token never reaches the access log, and an unknown or revoked token gets the same 404 as any unknown address.
  - Demo mode offers no feed.
- Deleting content deletes reminders and notifications. Deleting the account also deletes the feed and push subscriptions.

## Capabilities

### New Capabilities

- `scheduled-jobs`: the in-process job runner: when a job runs, what is kept in Postgres, catching up after downtime, failures, shutdown, and the off switch.
- `reminders`: reminder times on dated thoughts, when a reminder is due, delivering it once, catching up after downtime, and reminders stopping for done and deleted thoughts.
- `notifications`: the in-app notification list and unread count, how long notifications are kept, and the optional web push channel with its subscriptions.
- `calendar-feed`: the private feed address, its token, what the feed holds, rate limits, revoking it in Settings, and demo mode.

### Modified Capabilities

- `thought-store`: new requirements: a dated thought can repeat, and can have reminders; both are checked.
- `thought-filing`: new requirement: a proposal can carry a repeat and reminders, which the card shows and the user can change before confirming.
- `conversation-agent`: new requirements: the model proposes a repeat and reminders only when the user says so, and does not mark a repeating thought done for one occurrence; the search result and the held-proposal note show the repeat.
- `thought-search`: new requirement: a repeating thought passes the thought-date filter by its occurrences, and is ordered by its first occurrence in the days asked for.
- `upcoming-thoughts` (added by `thought-dates`): modified requirement "The Upcoming page lists dated thoughts from today on": a repeating thought is listed once, at its next occurrence. The delta is built on `thought-status`' version of the requirement.
- `thought-detail-view`: new requirement: the sheet shows and edits the repeat and the reminders.
- `chat-interface`: new requirement: a status card for a repeating thought says that marking it done stops it repeating.
- `account-data-deletion`: new requirement: reminders and notifications go with the content; the feed and push subscriptions go with the account.
- `user-auth`: modified requirement "Backend API requires a valid access token": the calendar feed request is an exception, with its own token. The delta is built on `auth-modes`' version.

## Impact

- Backend: new `app/jobs/` (the runner and the job list), `app/thoughts/repeats.py` (check, expand, and describe a repeat), `app/reminders.py` (reminder times and the reminder job), `app/notifications/` (store, prune job, web push), `app/calendar_feed.py` (token and feed), `app/rate_limit.py`; new routers `app/routers/notifications.py` and `app/routers/calendar.py`; changes to `app/thoughts/dates.py` (`repeat` and `reminders` in `when`), `app/thoughts/store.py` (store and update them, sync reminders, Upcoming with repeats), `app/thoughts/search.py` (repeats in the date filter), `app/chat/prompt.py` and `app/chat/tools.py` (schema, prompt lines, result text), `app/chat/proposal.py` (parts and confirm), `app/routers/thoughts.py`, `app/log_masking.py` (the feed token out of the access log), `app/config.py` (`JOBS_ENABLED`, the push settings), `app/main.py` (start and stop the runner), `app/user_data.py`. New models and one Alembic revision per task group: repeat columns on `thoughts`, and the tables `scheduled_jobs`, `thought_reminders`, `notifications`, `push_subscriptions`, `calendar_feeds`. New dependencies: `python-dateutil` (repeat rules), `icalendar` (the feed), `pywebpush` (push).
- Frontend: `components/chat/date-fields.tsx` (repeat and reminder fields, used by the card and the sheet), `components/chat/proposal-card.tsx`, `components/chat/thought-sheet.tsx`, `components/upcoming/upcoming-list.tsx`, `components/chat/sidebar.tsx` (Notifications link and count), a new `app/app/notifications/page.tsx`, Settings sections for notifications and the calendar feed, `public/sw.js` (push only), a new `app/api/calendar/[file]/route.ts`, and `proxy.ts` (`/sw.js` is public).
- API: `when.repeat` and `when.reminders` wherever `when` goes; `occurs` on Upcoming items; `GET /api/notifications`, `GET /api/notifications/unread`, `POST /api/notifications/read`; `GET /api/notifications/push`, `POST` and `DELETE /api/notifications/push/subscriptions`; `GET`, `POST`, `DELETE /api/settings/calendar-feed`; `GET /api/calendar/<token>.ics`.
- Settings: `JOBS_ENABLED` (default on), `WEB_PUSH_VAPID_PUBLIC_KEY`, `WEB_PUSH_VAPID_PRIVATE_KEY`, `WEB_PUSH_SUBJECT` (all unset by default). `.env.example`, `docs/setup.md`, and a new `docs/notifications.md`.
- Cost: none on the user's key. Reminders, notifications, push, and the feed make no model or embedding call.
- Deployment: still one backend process (`background-turns`). The runner fits that: it is one more task in the same process. A second process started by mistake would still send no reminder twice (the job claim and each notification's unique key), but `background-turns` already rules it out.
- Depends on `thought-dates` (`when`, the Upcoming page, the date search), `thought-status` (status, the status card, the open-only Upcoming list), `thought-editing` (the sheet's Edit), `background-turns` (the lifespan shape), `thought-library` (the access-log rewrite in `app/log_masking.py`), and `auth-modes` (demo mode, the user-auth requirement). Archive after `thought-status` and `auth-modes` (design decision 15). The task groups can ship as separate pull requests.
