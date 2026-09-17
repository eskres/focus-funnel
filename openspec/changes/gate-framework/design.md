## Context

`platform-foundation` is in place: Auth0 token checks and `current_user`, the Next.js catch-all proxy at `frontend/app/api/[...path]/route.ts`, async SQLAlchemy with Alembic, the shared error format, and `backend/app/nebius.py` with `client_for(session, user)` plus `map_nebius_error()`. Nothing calls a model for a user yet.

This change adds the first code that does. For motivation and scope see `proposal.md`; for the required behavior see the four spec deltas under `specs/`.

Three constraints from the archived foundation design shape everything below:

- Decision 2: the browser only ever talks to the Next.js proxy, which streams response bodies through unbuffered.
- Decision 7: one Nebius client per request per user, and one error-mapping function.
- Decision 8: one error envelope, and codes (not HTTP statuses) drive the UI.

A fourth constraint comes from the project rules: never fall back to another model.

## Goals / Non-Goals

**Goals:**

- One registry that settings, the API, routing, and model calls all read, so `push-and-pull-gates` and `explore-gate` add a handler and nothing else.
- Settings resolution that is one function with one rule, used by every call path.
- A streaming path that works end to end through the existing proxy without changing it.
- Failure modes that name the gate, the model, and the place to fix it.

**Non-Goals:**

- Real push, pull, and explore behavior. Placeholder handlers only.
- Storing conversations. `explore-sessions` does that.
- Per-gate system prompt editing, user-defined gates, and per-user embedding models.
- Streaming tool calls. `explore` needs tool calling, but only the feature check and a test probe land here.

## Decisions

### 1. Registry in code, defaults in configuration

`backend/app/gates/registry.py` holds one `Gate` record per gate:

```python
@dataclass(frozen=True)
class Gate:
    id: str                       # "router" | "push" | "pull" | "explore"
    label: str                    # shown in settings
    description: str              # one line, shown in the chat command list
    required_features: frozenset[ModelFeature]
    handler: GateHandler
    routable: bool                # router is False: it can't be a routing target
```

`GATES` is an ordered mapping keyed by id. Every loop in the settings API, the settings UI payload, the config validator, and the router prompt is built from `GATES`, so a fifth gate is a registry entry plus a handler.

`required_features` is a set of an internal `ModelFeature` enum, not raw Nebius strings, because the strings Nebius reports may change and several may mean the same thing (see decision 5). Today only `ModelFeature.TOOL_CALLING` exists, on `explore`.

**Alternative:** gates defined entirely in `gates.yaml`, including handler names resolved by import string. Rejected: a handler is code, and a typo in YAML would fail at request time instead of import time.

### 2. `gates.yaml` lives next to the backend code

Path: `backend/app/gates/gates.yaml`, packaged with the app and read at startup. `GATES_CONFIG_PATH` overrides the path so tests can point at a fixture. Shape:

```yaml
version: 1
limits:
  temperature: { min: 0.0, max: 2.0 }
  max_tokens: { min: 1, max: 32768 }
gates:
  router:
    temperature: 0.0
    max_tokens: 512
    hint: "Prioritise speed and cost. Picks one gate per message, so a small model is enough; a reasoning model needs a larger token limit. e.g. nvidia/Nemotron-3_5-Lightning"
  push:
    temperature: 0.3
    max_tokens: 2048
    hint: "Prioritise reliable structure. Writes the title, summary, tags and split suggestions. e.g. nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
  pull:
    temperature: 0.3
    max_tokens: 2048
    hint: "Prioritise answer quality from your own thoughts. e.g. nvidia/nemotron-3-super-120b-a12b"
  explore:
    temperature: 0.7
    max_tokens: 4096
    hint: "Prioritise reasoning and tool use. Searches your thoughts while you talk. e.g. nvidia/Nemotron-3-Ultra-550b-a55b"
```

**There is no default model, by decision.** The catalogue changes, model ids are account-specific, and a stale default would break every new account silently. A gate starts unset, the hint says what to prioritise, and the model chooser lists exactly what that user's key can call. `gate_model_not_set` is the error when an unset gate is used.

Loaded and validated once in the FastAPI lifespan, beside `get_settings()`, into a frozen object. Validation: every registry gate has an entry, no unknown gate ids, temperature, token limit and hint all present, values within `limits`. A failure raises at startup, which is what the spec's "server fails to start" scenarios check. The same `limits` block is the range used to validate user overrides, so defaults and overrides can never disagree.

The hints name Nemotron examples because Nemotron is this project's preferred family. They are examples in text, not configuration the code reads, so a retired example costs nothing but an edit.

This adds `pyyaml` to `backend/pyproject.toml` — the first new backend dependency since the foundation.

**Alternatives:** environment variables per gate per setting (12 variables, and adding a gate means adding three more), and a `gate_defaults` table (defaults become data an operator must migrate rather than config they can read in the repo). Both rejected.

### 3. `gate_overrides` table

```
id           UUID  primary key
user_id      UUID  not null, FK users.id ON DELETE CASCADE
gate_id      TEXT  not null
model        TEXT  null
temperature  FLOAT null
max_tokens   INT   null
created_at   TIMESTAMPTZ not null
updated_at   TIMESTAMPTZ not null

UNIQUE (user_id, gate_id)
```

One row per user per gate that has any override. A NULL column means "no override for this setting" and resolves to the default, which is what makes the per-setting `source` in the spec possible. `gate_id` is plain text, not a database enum: adding a gate must not need a migration, and the registry is the authority on which ids are valid (an unknown `gate_id` row is ignored on read, so a removed gate leaves no broken settings page).

The unique constraint uses the foundation's naming convention, so the migration is identical on Postgres and SQLite.

`thought-storage` already plans to delete gate overrides on account deletion; the CASCADE covers it either way.

### 4. One resolver, used by every path

```python
def resolve(gate: Gate, override: GateOverride | None, config: GateConfig) -> ResolvedSettings
```

Returns the four values plus, per setting, `"user"`, `"system"`, or `"unset"`. `model` is `None` with source `unset` until the user picks one, and every call path checks for that before touching Nebius. `reasoning_effort` is `None` with source `unset` unless the user set it, and is then left out of the request entirely. The settings endpoint, the test endpoint, and every gate call go through it. There is no second place where a default is applied, which is what keeps "the settings page shows what a call will actually use" true.

`PUT` replaces the override row with exactly the fields in the request body: a field present becomes an override, a field absent becomes NULL. One rule, so "save only the temperature" and "clear the model override but keep the temperature" are the same operation. `DELETE` removes the row.

### 5. Model features come from the verbose model list

Nebius `GET /v1/models?verbose=true` returns each model with an optional `supported_features` array (along with `context_length`, `pricing`, and `supported_sampling_parameters`). `GET /api/models` calls it with the user's key and maps each model to:

```
{ id, context_length?, features: { tool_calling: "supported" | "unsupported" | "unknown" } }
```

- `supported_features` present and contains a name matching the feature → `supported`
- `supported_features` present and contains no matching name → `unsupported`
- `supported_features` absent, empty, or the verbose call is not available → `unknown`

The match is a per-feature set of accepted lowercase names held in one place (`FEATURE_ALIASES` in `backend/app/gates/features.py`), so a Nebius rename is a one-line change. The exact string Nebius uses for tool calling is an open question below; until it is confirmed the alias set holds the plausible spellings and `unknown` is the safe landing spot.

**Saving is never refused on features.** Probing this account's 22 chat models showed `supported_features` badly understates reality: 8 models advertised `structured_outputs`, but 20 of 22 actually enforced a JSON schema, including all four Nemotron models, which advertise only `tools` and `reasoning`. Schema enforcement comes from the serving engine (vLLM constrains decoding), not from the model's advertised tags. So the field is a hint for the UI, and the Test action is the only check that decides anything. The honest check for `unknown` is the Test action, which for a feature-carrying gate sends a one-tool probe and reports `gate_model_unsupported` when the model rejects the tools parameter or answers without ever being able to call it. That gives the user a real answer instead of a guess.

The model list is fetched per request and not cached: it is one call, it is per user, and a stale cache would let a withdrawn model be saved.

**Alternative:** a hand-maintained list of tool-calling model ids in `gates.yaml`. Rejected: it goes stale silently, and it would have to be updated for every new Nebius model.

### 5b. Structured output and reasoning effort

Two findings from probing this account's catalogue shape how gates call models.

**Schema enforcement is the norm, not a feature to detect.** 20 of 22 chat models returned a schema-constrained answer for `response_format: {"type":"json_schema"}`; only the two Kimi K2 models ignored it, and one model rejected the schema type outright. So a gate that needs structured data (the push gate, in a later change) asks for `json_schema` and validates the result, with one repair retry for the models that ignore it. No gate may assume `json_mode` alone, which only promises valid JSON and not the right fields. Nebius' own API reference still lists `json_object` and `text` only, so this is behavior confirmed by probe, not by documentation.

**Reasoning models need room.** Several models spend their whole token budget thinking before writing anything: one produced no answer at all within 1,200 tokens. Consequences:

- Per-gate token defaults are sized for a reasoning model, not a plain one, which is why the router's default is 512 rather than a handful of tokens.
- `reasoning_effort` (documented values `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`) is an optional per-gate setting, sent only when the user set it. It is not universal: Harmony models (`openai/gpt-oss-*`) reject both `none` and `minimal`, so a rejection is reported as a settings error naming the value, and the gate keeps working once the user clears it.
- A test that ends with the token limit reached and no answer reports exactly that, rather than a generic failure, because that is the most likely first-run mistake.

### 6. API shape and new error codes

Following decision 8's format and conventions:

```
GET    /api/models                              { models: [{ id, context_length?, features }] }
GET    /api/settings/gates                      { gates: [{ id, label, description, required_features,
                                                            settings: { model: {value, source}, ... } }] }
PUT    /api/settings/gates/{gate_id}            body { model?, temperature?, max_tokens? } -> that gate's entry
DELETE /api/settings/gates/{gate_id}            204
POST   /api/settings/gates/{gate_id}/test       { ok: true, model } or an error envelope
POST   /api/chat                                SSE stream (decision 7)
```

New codes, added to `ErrorCode` in `backend/app/errors.py` and to `ApiErrorCode` in `frontend/lib/api.ts`:

- 409 `gate_model_not_set` — the gate has no model chosen yet (matches `nebius_key_missing`: setup the user must finish)
- 400 `gate_model_unknown` — the model id is not in this user's model list
- 400 `gate_model_unsupported` — the model lacks a feature the gate requires
- 409 `gate_model_unavailable` — the model in force cannot be used for a call (matches `nebius_key_missing`/`nebius_key_rejected`, which are also "your saved configuration needs fixing")
- 502 `routing_failed` — the router gate produced no usable classification (matches `nebius_unreachable`: an upstream answer we could not use)

Existing codes carry their existing meaning: `not_found` (404) for an unknown gate id, `validation_error` (422) for out-of-range values and empty messages, and the four `nebius_*` codes unchanged. `gate_model_unavailable` is produced by extending `map_nebius_error()` with a `model_id` argument: a `NotFoundError` or a 400/404 naming the model maps to it, everything else maps as it does today.

### 7. SSE from FastAPI through the proxy to the browser

`POST /api/chat` answers with a `StreamingResponse` of `text/event-stream`. Named events, each with a JSON payload:

```
event: routing   data: {"gate":"push","chosen_by":"command"|"router"}
event: delta     data: {"text":"..."}
event: error     data: {"error":{"code":"...","message":"..."}}
event: done      data: {}
```

`routing` is always first, which is what makes the spec's "label appears before the text" scenario hold. Failures **before** the first byte are ordinary error responses with the shared envelope and the right HTTP status — the chat handles them like any other API error. Failures **after** headers are sent cannot change the status, so they arrive as an `error` event carrying the same `{code, message}` envelope, and the stream ends without a `done`. The frontend error path reads both shapes into the same `ApiError` subclasses, so `nebius_key_rejected` mid-stream shows the same alert as `nebius_key_rejected` up front.

The proxy needs **no changes**. It already forwards `accept` (so `text/event-stream` reaches FastAPI), already returns `upstream.body` as a stream with `Cache-Control: no-cache` and `X-Accel-Buffering: no`, and already forwards `content-type` back. Its existing streaming test covers the mechanism; this change adds one that asserts an SSE content type survives the round trip.

The browser uses `fetch` plus a `ReadableStream` reader, not `EventSource`. `EventSource` cannot POST a message body and cannot be given headers, which would force the message into a query string. A small `lib/sse.ts` parses the event stream into typed events.

**Alternative:** answer with newline-delimited JSON rather than SSE. Rejected: the proposal names SSE, and named events keep `routing`, `delta`, and `error` apart without a discriminator field.

### 8. Router gate classification

The router runs as a normal, non-streamed model call with the `router` gate's resolved settings, then the chosen handler streams. Its prompt is built from the registry's routable gates and their descriptions, and asks for exactly one gate id. The answer is lowercased, trimmed, stripped of punctuation, and matched against routable gate ids.

No match: one retry with the same prompt, then `routing_failed`. One retry covers a stray wrapper token; more would double a user's latency for no gain. The retry never changes the model — that would be the fallback the rules forbid.

`router` is `routable: False`, so it cannot be picked as a target, and `/router` is not a command (the spec's scenario). The router's default temperature is `0.0`, because a hot router is a wrong router. Its token default is 512 rather than a handful: the answer is one word, but a reasoning model spends tokens before writing it, and a budget that cuts thinking short returns nothing at all.

**Alternative:** classify with a tool call or JSON schema. Rejected here: it would make tool calling a requirement of the router gate too, shrinking the set of usable small models.

### 9. Frontend structure

- `frontend/app/app/page.tsx` becomes the chat, replacing the "Chat is coming soon" placeholder. `components/chat/` holds the message list, the composer, the gate badge, and the empty-state command list.
- `components/gate-settings.tsx` renders one card per gate from `GET /api/settings/gates`, joined with `GET /api/models` for the chooser. Every model the key can use is selectable; one that does not report a feature the gate uses carries an "unconfirmed" note pointing at Test. A gate with no model shows "Not set", and the gate's hint sits with the chooser.
- New shadcn components: `select`, `textarea`, `badge`, `label`, and `skeleton`, added with the CLI as decision 10 prescribes.
- Conversation state is React state only. Nothing is persisted, which matches the chat-interface spec and leaves the field clear for `explore-sessions`.
- The existing `NebiusKeyAlert` is reused for `nebius_key_missing` and `nebius_key_rejected`; it gains a sibling for `gate_model_unavailable` that links to gate settings.

### 10. Tests

Backend tests reuse `FakeNebius` from `backend/tests/conftest.py` (an `httpx2.MockTransport`), so no test touches the network. SSE endpoints are exercised with `TestClient` streaming requests, asserting the event order (`routing` first) and that an error raised mid-stream arrives as an `error` event rather than a 500. Config validation is tested against fixture YAML files through `GATES_CONFIG_PATH`. Frontend tests use Vitest: the SSE parser against a hand-built stream, the chat against a mocked `fetch` that yields chunks with delays, and the settings UI against mocked API responses.

## Risks / Trade-offs

- [Nebius does not report `supported_features`, or reports a name we don't recognise] → Everything lands on `unknown`, saving stays possible, and the Test probe is the real check. The alias set is one file to fix. A model that turns out not to do tool calling fails at Test or at first explore use with `gate_model_unsupported`, never silently.
- [Nothing works until the user picks four models] → The cost of having no defaults. Mitigation: the hint on each chooser says what to prioritise with an example, gate settings show "Not set" plainly, and `gate_model_not_set` names the gate and links to settings from the chat. Worth revisiting if first-run setup proves annoying; a "use this for every gate" shortcut would be the cheapest fix.
- [A reasoning model returns nothing within a gate's token limit] → Defaults are sized for reasoning models, Test reports "token limit reached before an answer" by name, and `reasoning_effort` is available per gate.
- [`reasoning_effort` is rejected by some models] → Sent only when the user set it; a rejection is reported as a settings error naming the value, and clearing it restores the gate.
- [The router adds latency to every message without a command] → Small model, `temperature 0.0`, and a token limit of roughly one word. The `routing` event is emitted as soon as the classification returns, so the UI is not silent while the handler starts.
- [A buffering layer between the browser and FastAPI defeats streaming] → The proxy already sets `X-Accel-Buffering: no` and `Cache-Control: no-cache`, and a test asserts parts arrive separately. Any reverse proxy added later must be checked the same way.
- [An error after the first byte cannot set an HTTP status] → The `error` event carries the same envelope and the frontend funnels both shapes into the same error types. The trade-off is that a mid-stream failure returns HTTP 200 to anything that only reads the status line.
- [Per-setting overrides make "reset" ambiguous] → One rule: `PUT` replaces the row with exactly what the body holds, `DELETE` removes it. No partial-merge path exists.
- [`pyyaml` is a new dependency] → Widely used, and the file is read once at startup from inside the image, never from user input.

## Migration Plan

1. Alembic revision adds `gate_overrides`. It has no data to migrate: the table starts empty, and a user with no row already means "all defaults".
2. `gates.yaml` ships with the image. Changing a hint or a temperature default is a config change and a restart, not a migration, and it never touches a user's own choices.
3. Deploy order does not matter: the frontend's new screens only call endpoints this same change adds.
4. Rollback: `alembic downgrade -1` drops `gate_overrides`. Users lose their overrides and fall back to the defaults; nothing else is affected.

## Settled by probing a real account

Three earlier questions are answered, and the answers are why the decisions above look as they do.

- **Default model ids:** no longer needed. Gates ship unset with a hint, so nothing in the repo can go stale.
- **The feature string for tool calling is `tools`**, and `?verbose=true` works on this account. `supported_features` returns `tools`, `reasoning`, `json_mode`, and `structured_outputs`.
- **`supported_features` under-reports.** 8 of 22 chat models advertised `structured_outputs`; 20 of 22 enforced a JSON schema when asked. All four Nemotron models enforce it while advertising neither. The two exceptions are `moonshotai/Kimi-K2.7-Code` and `moonshotai/Kimi-K2.6`, which accept the parameter and ignore it, and `openbmb/MiniCPM-V-4_5`, which rejects the schema type.

## Open Questions

- **Whether `reasoning_effort` should also have per-gate system defaults** once real usage shows how much thinking each gate needs. It ships unset, which is safe on every model.
