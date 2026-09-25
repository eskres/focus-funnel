## Why

A chat turn lives inside its HTTP response today. When the user switches conversations or closes the tab while an answer streams, the browser drops the SSE connection, Starlette cancels the response task, and the cancellation reaches the model call and the stream's cleanup. The answer is lost, `release_turn` never runs, and the conversation answers `conversation_busy` ("Still answering") until `TURN_CLAIM_TIMEOUT` (15 minutes) passes. Switching conversations mid-answer is a normal thing to do, so this breaks everyday use.

## What Changes

- A turn runs to completion on the server whether or not the browser stays connected. The request starts the turn; a background task in the backend process runs it.
- The POST `/api/chat` response becomes a view of the running turn. Dropping it stops the view, not the turn.
- A new endpoint lets a returning chat reattach to a running turn: it replays the turn's events so far, then streams the rest live. It is owner-scoped: another user's conversation is 404.
- The conversation detail says whether a turn is running, so the chat knows to reattach.
- The turn claim is released as soon as the turn ends, however it ends: complete, failed, cut, or cancelled at shutdown. The release cannot be skipped by a cancelled request.
- On server start, claims left by the previous process are released and their unfinished answers are stored as failed. `TURN_CLAIM_TIMEOUT` stays as a backstop.
- `/compact` stays tied to its request (it stores nothing until the user accepts), but its claim release also becomes cancellation-safe.
- The chat shows a running answer as in progress when the user comes back, and picks up the rest. An answer that finished while the user was away shows in full, with tool results, proposal cards, and sources.
- No stop button. Leaving the chat no longer stops the model call; the reply length cap and the tool round limit bound what a turn can spend.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `conversation-agent`: "Conversations run independently" gains that a turn runs to completion without the browser, that the claim is freed when the turn ends, and what happens on a server restart.
- `chat-interface`: "Answers arrive a piece at a time" changes the "Connection drops in the middle" case, and adds how the chat shows an answer that is still running or that finished while the user was away.

## Impact

- Backend: `backend/app/routers/chat.py` (start the turn as a task, new reattach route), `backend/app/chat/sse.py` (the writer reads from a turn's event log), new `backend/app/chat/running.py` (the running-turn registry), `backend/app/chat/conversations.py` (startup release), `backend/app/main.py` (lifespan: release stale claims on start, cancel and settle running turns on shutdown), `backend/app/routers/conversations.py` (detail says a turn is running).
- Frontend: `frontend/lib/chat.ts` (reattach stream), `frontend/components/chat/chat.tsx` (reattach on open, treat a dropped stream as "look again", not "cut short").
- API: new `GET /api/chat/{conversation_id}/stream`; `ConversationDetail` gains `turn`. No breaking change to POST `/api/chat` or its events.
- Deployment: the registry is in-process, so the backend must run as one process (the current `uvicorn` command in `backend/Dockerfile` has no `--workers`). Design records this constraint.
- No database migration.
