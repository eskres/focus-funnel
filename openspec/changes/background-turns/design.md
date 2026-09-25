## Context

See proposal.md for the problem. The code as it stands:

- `POST /api/chat` (`backend/app/routers/chat.py`) claims the turn, stores the user message, opens the first model call and `Turn.open()` before the response starts, then returns `sse_response(events(), on_close)`. `on_close` closes the call, commits, and runs `release_turn`.
- `event_stream` (`backend/app/chat/sse.py`) runs `Turn.events()` inside the response generator, so a disconnect cancels the model call and the `finally` that awaits `on_close`.
- `Turn.events()` (`backend/app/chat/turn.py`) already stores each round as it ends: the assistant message with its tool calls, each tool message (with `details.sources` or `details.proposal_id`), the final answer as `complete`, `cut`, or `failed`, and usage through `record_usage` per round. Only the text of the round in flight lives in memory.
- The turn already has its own DB session (`get_session_factory`), not the request's.
- `claim_turn` / `release_turn` (`backend/app/chat/conversations.py`) use `conversations.turn_started_at` with a 15-minute `TURN_CLAIM_TIMEOUT` as the only recovery.
- Demo mode: the Next.js proxy sends held keys in `X-Provider-Keys` on each request. `use_request_keys` puts them in a `ContextVar`; `load_api_key` reads it. `register_secret` (log masking) is also a `ContextVar`. The search tool resolves the embedding provider's key during the turn, so the key lookup happens after the request, not only at `open_model_call`.
- Deployment is one backend container running `uvicorn app.main:app` with no `--workers` (`backend/Dockerfile`, `docker-compose.yml`). The lifespan in `backend/app/main.py` already runs one background task (demo cleanup) with `asyncio.create_task`.
- The frontend (`frontend/components/chat/chat.tsx`) aborts its fetch on unmount and marks an answer `cut` when the stream ends without `done`. `fromStored` already rebuilds tools, proposal cards, sources, and errors from stored messages.

## Goals / Non-Goals

**Goals:**
- A turn's life does not depend on any HTTP response.
- The claim is released in every exit path, including cancellation.
- A returning chat sees the same events a watching chat saw.
- No schema change and no new service.

**Non-Goals:**
- A stop button (see Decision 5).
- Running more than one backend process. The registry is in memory.
- Resuming a turn after a restart. It is stored as failed.
- An "answering" mark in the sidebar list. The conversation detail carries it; the sidebar can use it later.
- Background `/compact`. Its draft stores nothing until the user accepts it, so losing it on leave is correct. Only its claim release changes.

## Decisions

### 1. The turn runs as a background asyncio task in a running-turn registry

`POST /api/chat` does everything up to `turn.open()` as today, so errors before the first byte stay ordinary error responses. It then hands the turn to a registry (`backend/app/chat/running.py`) that starts `asyncio.create_task(run(turn))` and keeps a strong reference keyed by conversation id. `run` iterates `Turn.events()`, appends each event to the turn's event log, and wakes subscribers. Its `finally` closes the model call, commits, releases the claim, closes the session, and removes the entry. The POST response is a subscriber to that log.

A `RunningTurn` holds: the conversation id, the owner's user id, the position of the user message it answers, the event log (a list of `(name, data)`), an `ended` flag, and an `asyncio.Condition`. A subscriber reads from index 0, waits on the condition for more, and stops after the terminal event (`done` or `error`). A cancelled subscriber cancels only its own wait.

`run` turns an exception into the terminal event the same way `event_stream` does today (`ApiError` → `error` with its code, anything else → `internal_error` and a log line), so the event names and payloads on the wire do not change.

Alternatives:
- **Shield the existing generator** (`asyncio.shield` around the cleanup only). Frees the claim, but the model call is still cancelled and the answer lost. Rejected: fixes one symptom.
- **`BackgroundTasks` / Starlette background.** Runs after the response ends, not alongside it, and gives nothing to reattach to. Rejected.
- **A queue with a worker (Redis, arq, Celery, a Postgres job table).** Survives restarts and scales to many processes, but adds a service or a polling worker, and the live text still needs a pub/sub path to the browser. Rejected for now: one process is the deployment, and Decision 3 covers restarts well enough. The registry is the seam to swap if the backend ever runs more than one process.

The task is created from the request's context, and `asyncio.create_task` copies the current `contextvars` context. So the demo held keys and the log-masking secrets the request registered stay visible to the turn for its whole run, including the embedding key lookup in the search tool. Nothing about keys is written to the registry, the event log, or the database. A test pins this (Decision 6).

### 2. A returning chat reattaches to the live stream, with the stored messages as the fallback

New route: `GET /api/chat/{conversation_id}/stream`.
- Loads the conversation with `get_conversation` (owner-scoped, another user's is 404).
- Running turn found → SSE response that replays the log from the start, then follows it live, then ends with the same terminal event.
- No running turn → `204 No Content`. Not an error: the stored messages are complete.

`ConversationDetail` gains `turn: {"after_position": int} | null`, set from the registry. The chat renders stored messages up to and including `after_position`, drops later stored messages (the rounds already stored are also in the replayed log), then reattaches and builds the in-progress answer from the replayed events with the same event handling `send` uses. On `204` it reloads the detail.

When the POST stream drops without a terminal event (network break, not the user leaving), the chat does the same thing: reload the detail and reattach if `turn` is set. It marks the answer `cut` only if that fails or the stored answer did not finish.

The input stays locked while the chat follows a running turn, as it does while it sends one.

Alternatives:
- **Poll the messages endpoint only.** Simple, but a round's text is not stored until the round ends, so a returning user sees nothing for a long answer and then all of it at once. Rejected as the main path; the detail reload is still the fallback.
- **Reattach from an offset** (`?from=n`). Saves bytes, but the client would have to count events across a reload. Rejected: a turn's log is small (the reply cap bounds it), and a full replay lets the client stay stateless.
- **Store partial text on every delta.** One write per token. Rejected.

### 3. Restart: release stale claims on start; keep `TURN_CLAIM_TIMEOUT` as a backstop

- **Graceful shutdown.** The lifespan exit cancels every running turn and awaits them with a short bound (a few seconds). On `CancelledError`, `Turn.events()` stores the round in flight as `failed` with the text so far and error code `answer_interrupted` (a new stream-only code), then `run`'s `finally` releases the claim. The store and release run under `asyncio.shield` so a second cancellation does not skip them.
- **Crash or kill.** Nothing runs. On start, before serving, the lifespan runs one sweep: for each conversation with `turn_started_at` set, it stores an `assistant` message with `status="failed"` and `error_code="answer_interrupted"` when the last stored message is not an assistant message without tool calls (so the answer shows as failed and can be sent again), then clears `turn_started_at`. With one process, every claim that exists at start belongs to a dead process.
- **`TURN_CLAIM_TIMEOUT` stays.** It covers the case the sweep cannot know about: a second process, started by mistake, that shares the database. Its value does not change.

`fromStored` in the frontend already shows any `error_code` on an assistant message as "This answer did not finish. Send the message again to retry." `answer_interrupted` gets a line in `chat-error.tsx` with the same meaning.

Alternatives:
- **Owner token per process** in the claim, so a new process only clears claims from others. Correct for many processes, but the in-memory registry already rules those out. Deferred with the queue.
- **Drop the timeout.** Rejected: it is the only guard if two processes ever share the database.

### 4. The claim release cannot be skipped

`release_turn` runs in `run`'s `finally`, inside a task nobody cancels except shutdown, and under `asyncio.shield`. `/compact` stays request-bound: its `_closer` keeps its shape, but the rollback and `release_turn` run under `asyncio.shield` so a disconnect frees the conversation. A shielded coroutine keeps running after the outer task is cancelled, which is what the release needs.

### 5. No stop button

This change leaves it out. Leaving the chat no longer stops spending, but a turn is bounded by `reply_max_tokens` per round and `tool_rounds` per turn (`chat.yaml`), so the worst case is the same cost as watching the answer to its end. A stop button needs its own spec (what is stored for a stopped answer, whether a stopped proposal is held, how usage is shown) and a cancel route. The registry makes it a small follow-up: `RunningTurn.task.cancel()` plus the `answer_interrupted` path from Decision 3, with its own code.

### 6. Usage and keys without a request

- **Usage.** `record_usage` already uses the turn's own session and the `ModelCall`; it needs nothing from the request. It keeps recording once per model call, whether or not anyone watches. The `usage` and `notice` events still go into the log, so a returning chat sees the meter and warnings.
- **Keys, saved mode.** `provider_for_user` decrypts the key into the `Provider` the turn holds in memory. Nothing changes.
- **Keys, demo mode.** The key reaches the backend only in the request's `X-Provider-Keys` header, and lives in the request's `ContextVar`. Because the task copies the context (Decision 1), the turn can still read it after the request ends. The key exists only in the task's memory and is dropped when the task ends. The held key's `expires_at` is not checked mid-turn: a turn is minutes long at most, and the key was valid when the message was sent. A reattach request carries the header too, but the reattach route never reads keys.

A test asserts the demo case end to end: send in demo mode, drop the stream before the search tool runs, and check the search used the header's key and the answer was stored.

## Risks / Trade-offs

- [One process only] → Recorded as a non-goal and in the Dockerfile comment. The registry is the single place to replace with a shared queue and pub/sub later.
- [A restart loses the round in flight] → Stored as `answer_interrupted`; the user sends again. Accepted: restarts are rare and deliberate.
- [A dropped browser keeps spending tokens] → Bounded by the reply cap and tool round limit. The stop button is the follow-up.
- [Memory held by event logs] → One log per running turn, removed when the turn ends, bounded by the reply cap per round times the round limit.
- [Two tabs following one turn] → Both are subscribers to the same log; the input stays locked in both until the terminal event. Sending from the other tab still gets `conversation_busy`.
- [A subscriber that reads slowly] → The log is a list, not a bounded queue, so a slow reader never blocks the turn.
- [A running turn at the moment the detail loads, ending before the reattach] → The reattach gets `204` and the chat reloads the detail.

## Migration Plan

No schema migration. Deploy replaces the process; the startup sweep releases any claims the old process left. Rollback is the previous image: claims left by the new code are plain `turn_started_at` values, which the old code frees after `TURN_CLAIM_TIMEOUT`.
