## Context

`platform-foundation` is in place: Auth0 token checks and `current_user`, the Next.js catch-all proxy that streams response bodies unbuffered, async SQLAlchemy with Alembic, the shared error format, and `backend/app/nebius.py` with a per-request client and one error mapper (`map_nebius_error()`). Nothing calls a model for a user yet.

A gate-based prototype (a router model plus four gates with their own model settings) was built and measured before this design. It is not part of this change and was never pushed. It is kept on the local branch `backup/gate-build`, and decision 12 lists what carries over. See `proposal.md` for why it was replaced. This change depends on `model-providers`, which supplies provider keys, the per-provider client, and the model list.

Findings from probing a real account, which shape the decisions below:

- Tool calling on `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` chose the right tool on 32 of 34 runs over 17 messages, including multi-turn cases. Tool arguments were valid on 15 of 16 calls.
- 4 of 34 runs hit a 1,024-token limit while still reasoning. A follow-up of 10 calls each at 2,048 and 4,096 tokens had no truncated run. Samples are small.
- `reasoning_effort: none` returned an empty answer on 10 of 10 calls, for both routing and chat. `low` and `minimal` were no faster.
- Streaming works with tools. Tool-call arguments and text arrive as deltas. Reasoning arrives in a separate `reasoning` field that the server ignores. Median time to a finished turn was 2.4 to 3.4 s.
- A forced tool (`tool_choice` naming a function) was honoured on 8 of 8 calls, including streamed, with valid arguments, and `tool_choice: "required"` also worked. A forced call ends with `finish_reason: stop`, not `tool_calls`.
- A streamed call returns no token counts unless `stream_options.include_usage` is set. With it, a final chunk with no choices carries `usage`, and its prompt tokens matched the non-streamed count for the same prompt (45 and 45).
- Nebius offers no balance or usage endpoint for an inference key. Every reply carries `usage` token counts, and the model list carries per-token prices and `context_length`.
- Nano costs about $0.06 per million input tokens and $0.24 per million output tokens. A turn of about 550 prompt and 360 completion tokens is about $0.00012.

Constraints that stay: the browser talks only to the Next.js proxy, one provider client per request per user, one error envelope, and never fall back to another model. Thoughts are stored as plain text in Postgres, and conversations follow the same rule.

## Goals / Non-Goals

**Goals:**

- One model call decides and answers, with the conversation as context.
- Conversations that survive a reload, with a sidebar to resume, archive, and delete them.
- A discussion that ends in an editable proposal to file, without nagging.
- The user always knows how full the context is and what their usage costs.
- Reusing the sound parts of the prototype (provider client, SSE writer, chat UI) without carrying its gate concepts.

**Non-Goals:**

- Storing, searching, or summarising thoughts. `thought-storage` and `push-and-pull-gates` do that. The tools exist here, and the search tool and the confirm step answer that they are not available yet.
- Embeddings and a classifier. They are not needed without a router.
- Editing the system prompt, user-defined tools, or providers with their own API shape.
- Sharing conversations, search inside conversations, and model-written titles.

## Decisions

### 1. One model with tools, and no router

Each turn is a single streamed call to the conversation's model with the system prompt, the conversation, and two tool definitions: `search_thoughts(query)` and `propose_thought(title, summary, tags)`. The model replies in text, calls a tool, or both. There is no classification step, no `none` outcome, and no `routing_failed`.

**Alternatives:** keep the router and add an embedding classifier in front (rejected: it solved routing without context, which the conversation now supplies, and it needs a labelled example set and another model); keep the router LLM with a `clarify` outcome and a client timer (rejected: two calls per message, and the timer only patches missing context).

### 2. Slash commands are parsed by the server, except `/delete`

The prototype's slash-command parser is the starting point, with this command set: `/push`, `/pull`, `/explore`, `/compact`, `/delete`. Commands are matched at the start of the message, ignoring leading whitespace and letter case, and only when followed by whitespace or the end of the message. `/push` and `/pull` require text, and `/compact` and `/delete` reject any text with `validation_error`.

- `/push text` and `/pull text` ask the model to use the named tool. The call sets `tool_choice` to that function. This was probed and honoured on Nano, so no prompt fallback is needed. Because a forced call ends with `finish_reason: stop`, the loop detects tool calls by their presence, never by the finish reason.
- `/explore text` is an ordinary turn with the command removed.
- `/compact` is handled by the chat endpoint (decision 8).
- `/delete` is handled in the browser: it asks for confirmation and calls `DELETE /api/conversations/{id}`. It never reaches the model, is not in the command list, and no text in the product mentions it as an option after a proposal or an archive.

### 3. Data model

New tables, all cascading on user delete:

```
conversations   id UUID pk, user_id FK, title TEXT, provider_id TEXT null, model TEXT null, reasoning_effort TEXT null,
                archived_at TIMESTAMPTZ null, last_activity_at, created_at, updated_at,
                last_prompt_tokens INT null, held_proposal JSONB null

messages        id UUID pk, conversation_id FK, position INT, role TEXT
                ('user'|'assistant'|'tool'|'summary'), content TEXT null,
                tool_calls JSONB null, tool_call_id TEXT null,
                status TEXT ('complete'|'cut'|'failed'), error_code TEXT null,
                compacted BOOL default false, created_at
                UNIQUE (conversation_id, position)

usage_events    id UUID pk, user_id FK, conversation_id FK ON DELETE SET NULL,
                kind TEXT ('chat'|'compact'|'proposal'|'test'), provider_id TEXT, model TEXT,
                prompt_tokens INT, completion_tokens INT, cost_usd NUMERIC null, created_at
                INDEX (user_id, created_at)

chat_models     id UUID pk, user_id FK, provider_id TEXT, model TEXT, reasoning_effort TEXT null,
                is_default BOOL, position INT
                UNIQUE (user_id, provider_id, model)

user_settings   user_id UUID pk FK, temperature FLOAT null, warning_unit TEXT null
                ('usd'|'tokens'), warning_amount NUMERIC null, warning_notified_month TEXT null
```

- `messages` holds everything a resumed conversation must show, including tool calls and results, so a resume can rebuild both the transcript and the model's context. The context sent to the model is the system prompt, then the `summary` message if any, then every message with `compacted = false`.
- `held_proposal` holds the latest proposal the user has not confirmed: the title, summary, tags, and the message position it was made at.
- `usage_events` deliberately has no message text and uses `SET NULL`, so deleting a conversation keeps the spend history.
- The loadout limit of five is enforced in code, not by a constraint, so raising it needs no migration.
- Conversation text is stored as plain text, like thoughts. Provider keys stay AES-GCM encrypted. The "delete my data" endpoint in `thought-storage` must also remove these rows, which cascade from the user.

**Alternative:** one JSON blob per conversation. Rejected: it makes appending under concurrent writes, listing, and compaction awkward.

### 4. Chat endpoint and event stream

`POST /api/chat` takes `{ conversation_id?, message }`. Before the first byte it validates, loads the conversation (404 if not the user's), creates one when `conversation_id` is absent, checks the model is set and the context has room, and checks that no other turn is running for that conversation (`409 conversation_busy`, from a row lock). These failures are ordinary error responses. After the first byte, failures are `error` events with the same envelope and the stream ends without `done`.

Events, each with a JSON payload:

```
conversation  { id, title }                        first, for a new conversation
tool          { name, phase: "start"|"end", summary? }
proposal      { title, summary, tags }
delta         { text }
usage         { prompt_tokens, completion_tokens, context_length? }
notice        { kind: "compact_suggested"|"usage_warning", ... }
error         { error: { code, message } }
done          {}
```

`routing` is removed. The user message is stored before the model is called, so a failure keeps it. The assistant message is stored as the answer arrives and is finished with `complete`, `cut`, or `failed`.

The proxy needs no change: it already streams `text/event-stream` and preserves it. The browser keeps using `fetch` and a stream reader.

### 5. The tool loop

The server streams a call, forwards `delta` text, and collects tool-call deltas. If the collected calls are not empty (checked by presence, not by `finish_reason`), the server runs them, stores the tool messages, sends the results back, and calls the model again, up to a configured number of rounds (3). Past that, it ends with an `error` event `tool_loop_limit` and keeps the text so far.

- `search_thoughts` returns "not available yet" until `thought-storage` lands. Its implementation sits behind one function, so that change replaces it.
- `propose_thought` validates its arguments, stores the proposal in `held_proposal` and as a message, and emits a `proposal` event. It saves nothing. The confirm endpoint calls a `save_thought` seam that returns "not available yet" until `push-and-pull-gates` lands, and the card keeps the text.
- Malformed tool arguments (one of 16 in the probe) go back to the model as a tool error for one retry in the same loop, so they count against the round limit.

### 6. System prompt and how a discussion ends in a proposal

One system prompt is kept in code and not user-editable. It tells the model to talk with the user and help them think, to keep replies short, to use `search_thoughts` for questions about what the user filed before, to use `propose_thought` for something clearly worth keeping or when a discussion reaches a conclusion, to reply in plain text to greetings and unfinished messages, and to ask a short question when unsure. The probe prompt scored 32 of 34, and the real prompt is tuned against a probe set during the build.

**The three triggers for offering a held proposal are not all model judgment:**

- **Topic change** is the only model judgment. The system note for a turn with a held proposal says: do not repeat it, unless this message is about an unrelated topic, in which case call `propose_thought` first with a summary of everything discussed so far, then answer. It is tested by a probe (task 12.2) and, if unreliable, replaced by a comparison of embeddings of the new message and the held summary.
- **Archive or leave** and **`/compact`** are checked by the app. When a held proposal exists, the action first shows the proposal card. If the model has not produced one for the open discussion, the app asks it to (a forced `propose_thought` call, recorded as `kind = proposal`).

Time never brings a proposal back. A user who returns to an old conversation carries on as normal, and the held proposal waits for one of the three triggers.

The system never mentions deleting a conversation. That is a rule for the prompt and for every card and notice.

### 7. Settings: one model section

`GET /api/settings/models` and `PUT /api/settings/models` The body holds the loadout (up to five entries with a model and an optional effort), the default, and the temperature. `POST /api/settings/models/test` runs a test of one model and effort. The models a user can choose come from `GET /api/providers/{id}/models` (see `model-providers`), which carries `context_length`, per-token prices, and the advisory tool-calling status when the provider reports them.

`PUT` replaces the loadout with exactly what the body holds, one rule, with no partial merge. A model must appear in its provider's list for that user's key (`model_unknown`), and an effort must be a documented value. Feature information stays advisory: a model that does not report tool calling is stored and marked unconfirmed.

**`max_tokens` is not a setting.** The server sends its own limit on every call, 8,192 to start, from `chat.yaml`. That leaves room for the 2,300 reasoning tokens the worst probed case used, plus an answer. A reply that stops with `finish_reason = length`, and an empty reply, end with an `error` event `output_limit_reached`. Text received so far is kept, and the UI offers a retry or a lower effort.

**Effort options** come from a table in server configuration, matched by model id, which lists efforts a model is known not to accept. It starts with `none` for `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` (empty answers) and `none` and `minimal` for `openai/gpt-oss-*` (refused). Models not listed offer every documented effort, and Test is what finds a problem. Test also fails an empty answer, which the current Test would count as a success.

Configuration lives in `chat.yaml`, loaded and validated once at startup: an invalid file stops the server, and `CHAT_CONFIG_PATH` lets tests point at a fixture. It holds: the temperature default and range, the reply length limit, the tool round limit, the soft context share (0.7), the number of recent messages kept by `/compact` (6), the hint shown with the model chooser, and the effort table. It holds no model id.

### 8. Context meter, refusing a full context, and `/compact`

- **Meter:** each answer stores the provider's `prompt_tokens` in `conversations.last_prompt_tokens` and emits it in a `usage` event. The context length comes from the model list, held in a short-lived per-user cache (five minutes) so a chat turn does not add a list call. A stale cache can only affect the meter and the price estimate. It is never used to accept a model choice, which still reads the list fresh.
- **Soft limit:** when `last_prompt_tokens` passes 70% of the context length, the answer ends with a `notice` of kind `compact_suggested`, once per crossing.
- **Hard limit:** before a call, the server estimates the next prompt as `last_prompt_tokens` plus the new message at about 3.5 characters per token, and refuses with `context_full` if that plus the reply limit exceeds the context length. Nebius offers no tokenizer, so this is an estimate. Being wrong on the low side only means the provider refuses the call and the error is mapped to `context_full`.
- **`/compact`:** the chat endpoint runs a call without tools, asking for a summary of all but the last 6 messages that keeps decisions, facts, names, and open questions. It returns the draft as a `compact_draft` event. The user edits it and accepts through `POST /api/conversations/{id}/compaction { summary }`. Only then does the server insert a `summary` message and set `compacted = true` on the replaced messages. The transcript is untouched, so a resume still shows everything. A summary made after an earlier summary includes it, so compaction repeats.

### 9. Usage tracking

A single helper records a `usage_events` row after every model call: chat rounds, `/compact`, forced proposals, and tests. The token counts come from the stream: every streamed call sets `stream_options.include_usage`, which Nebius honours (without it a stream reports no usage). The token counts arrive on a final chunk with no choices, so the stream reader must not assume every chunk has one. How usage arrives depends on the provider's `stream_usage` capability in `model-providers`: `final_chunk` is read as described, `incremental` takes the last reported value, and `none` records the cost as unknown. If a stream ends without usage, nothing is recorded and the reply's cost is unknown, which the spec allows.

The cost is `prompt_tokens × prompt_price + completion_tokens × completion_price` from the model list at the time of the call. Prices are read as USD per token, as the list reports them. The field carries no unit, and Nebius's price page needs a login, so the unit is **not verified** against a published price. Task 14.8 compares the estimate with the Nebius console for real usage, and the settings label already calls the figure an estimate.

`GET /api/usage?days=30` returns daily totals in UTC, the split by model, and the month to date. The graph is a small SVG bar chart written for this page, so no charting dependency is added. Days are UTC to start, so a user far from UTC sees a day boundary at an odd hour. A time zone offset parameter is a later improvement.

The warning threshold lives in `user_settings`. After each recorded call the server compares the month's total with it. If the total has reached it and `warning_notified_month` is not the current month, it emits a `notice` of kind `usage_warning` and stores the month. The chat never blocks on it.

### 10. Error codes

Codes: `model_not_set` (409), `model_unknown` (400), `model_unsupported` (400), `model_unavailable` (409), `context_full` (409), `conversation_busy` (409), and the stream-only codes `output_limit_reached` and `tool_loop_limit`. The provider codes (`provider_key_missing`, `provider_key_rejected`, `provider_unreachable`, `provider_rate_limited`, `provider_request_refused`) come from `model-providers`, whose error mapper takes a `model_id` so that a missing model maps to `model_unavailable`. The frontend's `ApiErrorCode` list and error classes match, and a model alert links to the model settings.

### 11. Frontend structure

- `app/app/page.tsx` starts a new conversation. `app/app/[id]/page.tsx` shows a stored one, so a reload lands on the same conversation.
- A left sidebar component lists conversations by last activity, has an "Archived" section, a new-conversation button, and a row menu for rename, archive or restore, and delete.
- The composer gains a model and effort dropdown built from the loadout, with a link to the model settings, and the context meter beside it.
- The message list shows the thinking indicator, tool indications, and the proposal card. The card has editable title, summary, and tags, and a Confirm action. Compacted messages are shown with a marker, and the `/compact` draft opens in an editable dialog.
- Settings gains the model section and a usage section with the graph, the by-model split, the month total, and the warning threshold.
- `/delete` shows a confirm dialog and calls the delete endpoint.

### 12. Reusing the prototype code

The prototype on `backup/gate-build` is a source, not a base. The build brings over, with `gate` removed from names: the SSE writer, the slash-command parser, the chat UI (composer, message list, error display, command list), `lib/sse.ts`, `lib/chat.ts`, `redirect-to-login`, the five shadcn components, and the proxy SSE test. The provider client, error mapper, model list, feature classifier, and `FakeProvider` double come from `model-providers`, which lands first. Not brought over: the gate registry, `gates.yaml`, overrides and their storage and resolution, the gate handlers, the router, the gate settings API and cards, or the `gate_overrides` migration.

One Alembic revision creates the new tables, with `down_revision` `d06a9fe12cba` (the API key migration). There are no users yet, so no data is migrated. A developer's local database that already ran the prototype's overrides migration is reset (delete the Postgres volume, or recreate the SQLite file), since Alembic cannot find that revision. The downgrade drops the new tables.

### 13. Several conversations on several models

Nothing in the design shares state between conversations except the user's loadout, default, temperature, usage, and provider accounts. The rules that keep that safe:

- **The model is stored on the conversation.** A conversation created with no default set stores no model and takes the default at its first successful message. Changing the default or the loadout later never rewrites an existing conversation. The dropdown always shows the conversation's own model, marked when it is not in the loadout.
- **Switching model inside a conversation** clears `last_prompt_tokens`, sets the effort to the new model's loadout effort (or none), and drops an effort the effort table says the new model refuses. The history carries over unchanged. Tool calls and results are stored in the OpenAI-compatible format that chat models on every supported provider receive, and a model that rejects tools fails with `model_unsupported` on its first turn instead of part-way through a conversation.
- **Context differs per model.** The meter and the `context_full` check always use the conversation's current model's `context_length`. `/compact` summarises with the conversation's model. When the conversation does not fit that model, the dialog lists the loadout models that are large enough, with their context lengths, and the user picks one for that one summary. There is no automatic choice, in line with the rule against falling back.
- **Concurrency.** The row lock is per conversation, so turns in different conversations run at the same time. Each writes only its own conversation's messages, and each usage record names the model that made the call. Parallel turns share the provider account's rate limit. A 429 is retried by the SDK and then reported as `provider_rate_limited`. The design adds no client-side cap on parallel turns, and the first real use will show whether one is needed.
- **The held proposal, the meter, and the compaction state belong to the conversation**, so nothing leaks between conversations.

### 14. Tests

`FakeProvider` (from `model-providers`) gains streaming responses: text deltas, tool-call deltas, a final `usage` chunk, and a mid-stream error. Backend tests cover the loop, forced tools, the event order, truncation, the context refusal, compaction, usage records and the warning, and ownership on every new endpoint. Frontend tests use Vitest with a mocked `fetch`.

## Risks / Trade-offs

- [The model picks the wrong tool or none] → A proposal never saves without confirmation and search only reads, so a wrong call costs one extra message. Slash commands force the tool. A probe set of about 40 messages runs before and after the prompt is tuned.
- [A reply runs out of room while reasoning] → A high server limit (8,192), a clear `output_limit_reached` message with retry, and a lower effort choice. Empty replies are treated as failures.
- [Turns take 2 to 4 s, and text starts only after reasoning ends] → A thinking indicator, and a plain greeting takes about 1 s. Users can pick a faster model per conversation.
- [Tangent detection by the model is unreliable] → Only that one trigger depends on it. The other three are deterministic. A probe decides whether to swap in embeddings.
- [Several conversations on different models share one provider account and its rate limit] → The SDK retries a 429 twice, then the call fails with `provider_rate_limited` and a retry message. Turns in different conversations run in parallel and each is recorded against its own model.
- [A conversation's model is removed from the loadout or withdrawn by the provider] → The conversation keeps its stored model while the key can use it. A withdrawn model gives `model_unavailable`, and the user picks another in the dropdown and carries on with the same history.
- [Switching to a model with a smaller context] → The meter shows the conversation over the limit, sends get `context_full`, and `/compact` lets the user choose a loadout model large enough to write the summary. Nothing is chosen for them.
- [A model counts tokens differently, so `last_prompt_tokens` is wrong after a switch] → The stored count is cleared on a model change and the meter shows an estimate until the next answer.
- [Full history is re-sent every turn, so the cost grows] → The meter, the compact suggestion, the usage graph, and the warning threshold. At Nano prices a 10,000-token history costs about $0.0006 per turn.
- [A `/compact` summary loses something important] → The user reads and edits it before it takes effect, and the full transcript stays visible.
- [Storing conversations changes the privacy promise] → Plain-text storage like thoughts, cascade delete with the account, `/delete` and the sidebar delete for single conversations, and usage records that hold no text.
- [The `context_full` estimate is off] → A too-low estimate lets the provider refuse instead, and that error is mapped to the same code.
- [Two tabs write to one conversation] → A row lock allows one turn at a time and the second gets `conversation_busy`.
- [The prototype's code is reused in a new shape] → Only the parts listed in decision 12 come over, each with its existing tests, so the suite guards the reuse.

## Migration Plan

1. Bring over the reusable prototype code (task 1.1 and task 1.5).
2. Ship the backend, the Alembic revision, and the frontend together, because the chat request, the events, the tables, and the error codes all change.
3. Reset local databases that ran the prototype's overrides migration.
4. Rollback: `alembic downgrade -1` drops conversations, messages, usage, and the loadout.

## Open Questions

- The starting values for the temperature default (0.3, the probed value), the recent messages kept by `/compact` (6), and the tool round limit (3) are guesses to tune against real use.
- What each provider returns when an account runs out of credit. It is not probed. Until it is known, any client error without its own code reaches the user as `provider_request_refused` with the provider's own message.
- Whether daily usage buckets should follow the user's time zone rather than UTC.
- Whether the reasoning text should ever be shown to the user. It is ignored for now.
