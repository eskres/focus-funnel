## 1. Gate registry and configuration

- [ ] 1.1 Add `pyyaml` to `backend/pyproject.toml` and check that `uv sync` succeeds and `python -c "import yaml"` runs in the backend environment
- [ ] 1.2 Add `app/gates/registry.py` with the `Gate` record (id, label, description, features_used, handler, routable), the `ModelFeature` enum, and the four entries from design decision 1. Check with a pytest test that the registry holds exactly `router`, `push`, `pull`, `explore`, that only `explore` uses tool calling, and that only `router` is not routable
- [ ] 1.3 Add `app/gates/gates.yaml` with the `version`, `limits`, and `gates` blocks from design decision 2: per-gate `temperature`, `max_tokens`, and `hint`, and **no model ids**. Check that the file parses, holds an entry for every registry gate, and contains no model id
- [ ] 1.4 Add the config loader with `GATES_CONFIG_PATH` support and validation (every gate present, no unknown gate ids, temperature, token limit and hint present, values inside `limits`). Check with pytest fixture files that a valid file loads and that a missing gate, an unknown gate id, a missing hint, a missing setting, and an out-of-range value each raise at load time with a message naming the gate and the problem
- [ ] 1.5 Load and validate the gate config in the FastAPI lifespan next to `get_settings()`. Check with a pytest test that the app fails to start when `GATES_CONFIG_PATH` points at an invalid file

## 2. Override storage and settings resolution

- [ ] 2.1 Add the `GateOverride` model for `gate_overrides` with the columns from design decision 3 plus a nullable `reasoning_effort` (nullable `model`, `temperature`, `max_tokens`, unique `user_id` + `gate_id`, cascade on user delete). Check with a pytest test that a second row for the same user and gate is rejected and that deleting the user deletes the row
- [ ] 2.2 Add the Alembic migration for `gate_overrides` and check that `alembic upgrade head` then `downgrade -1` runs cleanly on both an empty SQLite database and the compose Postgres
- [ ] 2.3 Add the `resolve()` settings resolver from design decision 4, returning each setting's value and its `user`, `system`, or `unset` source. Check with pytest that no override gives an unset model with system temperature and token limit, a partial override gives a mixed result, and that `reasoning_effort` stays unset unless the user set it
- [ ] 2.4 Add the override read/replace/delete helpers, where a replace writes exactly the fields in the request and NULLs the rest. Check with pytest that replacing an override with a body holding only `temperature` clears a previously saved `model` override back to unset, and that delete removes the row and is a no-op when no row exists

## 3. Model listing and feature information

- [ ] 3.1 Add `app/gates/features.py` with the `FEATURE_ALIASES` map (tool calling matches the string `tools`) and the classifier that turns a model's `supported_features` into `supported`, `unconfirmed`, or `unknown`. Check with pytest that `tools` gives `supported`, a present list without it gives `unconfirmed`, and an absent or empty list gives `unknown`
- [ ] 3.2 Add the model-list fetch that calls Nebius `GET /v1/models?verbose=true` with the user's key and maps each model to `{ id, context_length?, features }`. Check against `FakeNebius` with pytest that a verbose response is mapped correctly and that a response without `supported_features` yields `unknown` for every model
- [ ] 3.3 Add `GET /api/models`. Check with pytest that it returns the mapped list for a user with a working key, and returns `nebius_key_missing`, `nebius_key_rejected`, and `nebius_unreachable` for the matching Nebius outcomes
- [ ] 3.4 Add the override validation used before a save: the model must appear in the user's model list, and the values must be in range. Feature information must not refuse a save (design decision 5). Check with pytest that an unknown model gives `gate_model_unknown`, that a model not reporting `tools` is accepted for `explore` and flagged unconfirmed in the response, and that an out-of-range value gives `validation_error`

## 4. Settings API

- [ ] 4.1 Add the new error codes `gate_model_not_set` (409), `gate_model_unknown` (400), `gate_model_unsupported` (400), `gate_model_unavailable` (409), and `routing_failed` (502) to `app/errors.py`, and extend `map_nebius_error()` with a `model_id` argument that maps a missing-model response to `gate_model_unavailable`. Check with pytest that each constructor returns the documented status and that a Nebius 404 naming the model maps to `gate_model_unavailable` while other errors map as before
- [ ] 4.2 Add `GET /api/settings/gates` returning every registry gate with its label, description, hint, features used, and resolved settings with per-setting sources. Check with pytest that a new user sees four gates with unset models, system temperature and token limits, and a hint on every gate, and that a user with one override sees the mixed sources
- [ ] 4.3 Add `PUT /api/settings/gates/{gate_id}`. Check with pytest the scenarios for a valid save, a model not in the list, a model that does not report a feature the gate uses (accepted and flagged), an out-of-range temperature, token limit and reasoning effort, an unknown gate id returning `not_found`, and that a refused save leaves an earlier override unchanged
- [ ] 4.4 Add `DELETE /api/settings/gates/{gate_id}`. Check with pytest that it removes the override so the model is unset again, returns 204, succeeds when no override exists, leaves other gates untouched, and returns `not_found` for an unknown gate id
- [ ] 4.5 Add `POST /api/settings/gates/{gate_id}/test`, sending a short prompt with the gate's resolved settings and, for a gate with features in use, a one-tool probe. Check with pytest that a working model reports success with the model id, an unset model gives `gate_model_not_set`, a model that rejects the tools parameter gives `gate_model_unsupported`, a missing model gives `gate_model_unavailable`, a refused reasoning effort is reported naming the value, a run that hits the token limit with no answer says so, a missing key gives `nebius_key_missing`, and no stored override changes in any case
- [ ] 4.6 Check with a pytest test that one user's overrides never appear in or are changed by another user's settings calls, using two users against the same gate

## 5. Gate execution and SSE

- [ ] 5.1 Add the gate call helper that resolves a gate's settings, refuses an unset model with `gate_model_not_set` before any network call, builds the per-request Nebius client, sends `reasoning_effort` only when set, and streams chat completions, mapping failures through `map_nebius_error()` with the model id. Check with pytest against `FakeNebius` that it uses the resolved model, temperature and token limit, that an unset gate never calls Nebius, and that a withdrawn model gives `gate_model_unavailable` with no second call to any other model
- [ ] 5.2 Add the SSE response writer emitting `routing`, `delta`, `error`, and `done` events as described in design decision 7. Check with pytest that events carry the documented JSON payloads and that the stream ends with `done` on success
- [ ] 5.3 Add the rule that failures before the first byte are ordinary error responses and failures after it are `error` events with the same envelope and no `done`. Check with a pytest streaming test that a key rejected before the stream starts gives HTTP 409 `nebius_key_rejected`, and one raised mid-stream arrives as an `error` event with the same code
- [ ] 5.4 Add the placeholder `push`, `pull`, and `explore` handlers that answer with a short "not available yet" message. Check with pytest that each emits a `routing` event followed by the placeholder text and a `done`

## 6. Routing and the chat endpoint

- [ ] 6.1 Add the slash-command parser: a leading command after optional whitespace, case-insensitive, followed by whitespace or end of message, with the remainder as content. Check with pytest that `/push buy milk`, `/Pull x`, and a leading-space `/explore x` parse to their gates, that `/pushing x`, `remind me to /push later`, `/archive x`, and `/router x` are not commands, and that a bare `/push` gives `validation_error`
- [ ] 6.2 Add the router gate classification from design decision 8: a non-streamed call with the router's settings, a prompt built from the routable registry entries, normalisation of the answer, and one retry before failing. Check with pytest that a clean answer routes, a wrapped answer still matches after normalisation, an unusable answer retries once and then gives `routing_failed`, and that the retry uses the same model
- [ ] 6.3 Add `POST /api/chat` that parses the command, routes when there is none, emits `routing` first, then streams the handler. Check with pytest that a commanded message never calls the router, that a routed message reports `chosen_by: router`, that `routing` precedes every `delta`, and that an empty message gives `validation_error`
- [ ] 6.4 Check with pytest that an unset router gate gives `gate_model_not_set` naming the router with advice to use a command, that an unset target gate gives `gate_model_not_set` naming that gate, and that an unavailable router model gives `gate_model_unavailable`, with no handler run and no other model called in any case

## 7. Frontend gate settings

- [ ] 7.1 Add the new error codes to `frontend/lib/api.ts` with their error classes, and check with Vitest that `gate_model_not_set`, `gate_model_unknown`, `gate_model_unsupported`, `gate_model_unavailable`, and `routing_failed` responses become the matching error types
- [ ] 7.2 Add the shadcn `select`, `textarea`, `badge`, `label`, and `skeleton` components with the CLI, and check that `npm run build` passes with each rendered once
- [ ] 7.3 Add a gate-model alert component built on shadcn `Alert` for `gate_model_not_set` and `gate_model_unavailable`, linking to gate settings, and check with a Vitest render test that each message, the gate name, and the link appear
- [ ] 7.4 Add the gate settings section to `/settings`: one card per gate with the gate's hint beside a model chooser, temperature, token limit, optional reasoning effort, Test, and Reset, showing each setting's source. Check with Vitest against mocked API responses that four cards render, that an unset gate shows "Not set" with its hint, that user and system sources are labelled, and that Reset calls the delete endpoint
- [ ] 7.5 Mark models in the chooser by feature information: every model selectable, with an "unconfirmed" note and a pointer to Test where a feature the gate uses is not reported. Check with a Vitest test that a model not reporting `tools` is selectable under `explore` and carries the note
- [ ] 7.6 Show the refusal reason on a failed save and the outcome of a Test, keeping earlier values on refusal. Check with Vitest that a `gate_model_unknown` response shows the model name, that a Test failure naming the token limit is shown as such, and that the displayed settings are unchanged
- [ ] 7.7 Show the existing Nebius key alert with empty choosers when gate settings load without a saved key, and check with a Vitest test that the alert and its link to the API key settings appear

## 8. Frontend chat

- [ ] 8.1 Add `frontend/lib/sse.ts` parsing an event stream into typed `routing`, `delta`, `error`, and `done` events. Check with Vitest that events split across chunk boundaries parse correctly and that an unknown event name is ignored
- [ ] 8.2 Replace the `/app` placeholder with the chat screen: message list, composer, and send. Check with Vitest that sending adds the user's message and clears the input, that an empty or whitespace message sends nothing, and that the composer is disabled while an answer is arriving
- [ ] 8.3 Stream answers with `fetch` and a `ReadableStream` reader through the proxy. Check with a Vitest test whose mocked fetch yields chunks with delays that partial text is rendered before the answer completes
- [ ] 8.4 Add the gate badge showing the gate and whether a command or the router chose it, rendered as soon as the `routing` event arrives. Check with Vitest that the badge appears before any `delta` text is rendered
- [ ] 8.5 Add the empty state listing `/push`, `/pull`, and `/explore` with one-line descriptions, and check with a Vitest test that all three appear on a chat with no messages
- [ ] 8.6 Render errors in place of an answer, keeping the user's message: key errors linking to API key settings, `gate_model_not_set` and `gate_model_unavailable` linking to gate settings, `routing_failed` suggesting an explicit command. Check with Vitest that each code renders its message and link and that the user's message stays
- [ ] 8.7 Handle a stream that stops early: keep the received text and show that the answer was cut short. Check with a Vitest test whose mocked stream aborts mid-answer
- [ ] 8.8 Add a Vitest test for the proxy route that a `text/event-stream` response keeps its content type and reaches the client in parts

## 9. Full system check

- [ ] 9.1 Run the backend test suite on SQLite and on the compose Postgres, and run `npm run test`, `npm run lint`, and `npm run build` in `frontend/`. Check that all pass
- [ ] 9.2 On a fresh `docker compose up` with a real Nebius key, open gate settings and check that every gate shows "Not set" with its hint, that sending a message first gives `gate_model_not_set` with a link to settings, and that choosing a model for each gate from the chooser makes the gates usable
- [ ] 9.3 Test each gate from settings with a chosen model, including one reasoning model, and check that success names the model and that a token limit too small for a reasoning model reports the token limit as the reason
- [ ] 9.4 In the chat, send `/push`, `/pull`, and `/explore` messages and confirm each reaches its gate with the placeholder answer and a badge saying the command chose it
- [ ] 9.5 Send messages with no command that clearly call for filing, for recall, and for discussion, and check that the router picks push, pull, and explore respectively and that the badge says the router chose them
- [ ] 9.6 Point a gate at a model, then make it unusable (revoke the key or choose a withdrawn model), send a message, and check that the chat shows the error with a link to settings and that no answer from another model appears
- [ ] 9.7 Confirm the answer streams rather than arriving at once, by watching text appear progressively in the browser with the default compose setup
