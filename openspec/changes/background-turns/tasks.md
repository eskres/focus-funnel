## 1. Running turns

- [ ] 1.1 Add `backend/app/chat/running.py` with the `RunningTurn` registry from design decision 1: start a turn as an `asyncio` task with a strong reference, append each event to its log, end with the same terminal `done` or `error` event `event_stream` sends today, and in a shielded `finally` close the call, commit, release the claim, close the session, and remove the entry. Add a subscriber that replays the log from the start and then follows it. Check with pytest that two subscribers get the same events in order, that a cancelled subscriber does not cancel the turn, that an `ApiError` ends the log with its `error` event and anything else with `internal_error`, and that the entry is gone after the turn ends
- [ ] 1.2 Change `POST /api/chat` to hand the opened turn to the registry and return a subscriber stream; keep every error before `turn.open()` an ordinary error response. Check with pytest through the endpoint that a client that disconnects after the first `delta` still leaves a `complete` answer, its tool messages with `details.sources` or `details.proposal_id`, and a usage row per model call, that `turn_started_at` is null once the turn ends, and that the next message is answered instead of `conversation_busy`
- [ ] 1.3 Check the failure paths with the browser gone. With pytest through the endpoint and a disconnected client: a provider error mid-stream stores a `failed` answer with its code, a reply at the length limit stores `cut` with `output_limit_reached`, the tool round limit stores `tool_loop_limit`, and in each case the claim is released
- [ ] 1.4 Shield the rollback and `release_turn` in `/compact`'s `_closer` (design decision 4). Check with pytest that a client that disconnects mid-draft leaves `turn_started_at` null and stores nothing

## 2. Following a turn

- [ ] 2.1 Add `GET /api/chat/{conversation_id}/stream` from design decision 2. Check with pytest that the owner gets every event of a running turn from the first, then the rest, then `done`; that a conversation with no running turn answers 204; and that another user's conversation and an unknown id both answer 404 `not_found` with the same body
- [ ] 2.2 Add `turn: {"after_position"} | null` to `ConversationDetail` from the registry. Check with pytest that it is set to the user message's position while a turn runs, is null after, and is null for a conversation with only a `/compact` claim

## 3. Keys and usage without a request

- [ ] 3.1 Check design decision 6 in demo mode with pytest: send a `/pull` message with the key in `X-Provider-Keys`, disconnect before the search tool runs, and check that the model call and the embedding call both used that key, that the answer and the usage rows are stored, and that no key appears in the database, the event log, or the log output

## 4. Restart and shutdown

- [ ] 4.1 Store a cancelled turn's round in flight as `failed` with the text so far and the new stream-only code `answer_interrupted` (add it to `ErrorCode`), under `asyncio.shield`. In the lifespan exit, cancel running turns and await them with a short bound. Check with pytest that cancelling a running turn's task stores the partial text as `failed` / `answer_interrupted` and releases the claim
- [ ] 4.2 Add the startup sweep from design decision 3 to `backend/app/chat/conversations.py` and run it in the lifespan before serving. Add a comment to the `uvicorn` command in `backend/Dockerfile` that the backend must run as one process. Check with pytest on Postgres that a conversation left with `turn_started_at` set and a user message last gets a `failed` / `answer_interrupted` assistant message and a null claim, that one whose last message is a finished answer only gets its claim cleared, and that conversations with no claim are untouched

## 5. Chat screen

- [ ] 5.1 Add `followTurn(conversationId, signal)` to `frontend/lib/chat.ts` that yields the reattach stream's events, returns nothing on 204, and throws the usual `ApiError` otherwise; add `turn` to the conversation detail type; add `answer_interrupted` to `chat-error.tsx` as "This answer did not finish. Send the message again to retry." Check with vitest against `test/fake-api.ts` for the events, the 204, and the 404 cases
- [ ] 5.2 In `chat.tsx`, when a loaded conversation has `turn`, render stored messages through `after_position`, follow the turn with the same event handling `send` uses, show the answer as in progress, and lock the input until the terminal event; on 204 reload the conversation. Stop following (not the turn) when the user leaves. Check with vitest for each "Coming back to an answer" scenario: finished while away shows text, tools, proposal card, and sources; still running shows the answer so far and then the rest with the input locked; failed while away shows the reason; two chats on one turn both show it
- [ ] 5.3 When the POST stream ends without a terminal event, reload the conversation and follow the turn if it is still running; mark the answer `cut` only if the reload fails or the stored answer did not finish. Check with vitest for each "Answers arrive a piece at a time" connection scenario
- [ ] 5.4 In the running app, send a message that makes a search and a proposal, switch to another conversation before the answer ends, and switch back: check that the answer is still arriving or shows in full with its sources and proposal card, and that the next message is answered at once. Then restart the backend container mid-answer and check that the answer shows as not finished and the next message is answered

## 6. Specs and checks

- [ ] 6.1 Run `openspec validate background-turns --strict`, the full default and `postgres` pytest runs, and the frontend vitest run and type check, and check that all pass
