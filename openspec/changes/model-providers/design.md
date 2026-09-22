## Context

`platform-foundation` stores one Nebius key per user in `nebius_api_keys` (AES-GCM, last 4 characters shown), checks it against Nebius before saving, and builds one OpenAI-SDK client per request through `client_for()`. Errors go through one function, `map_nebius_error()`, into the `nebius_*` codes. The base URL is one environment variable, `NEBIUS_BASE_URL`. Nothing else in the code knows about providers.

A gate-based prototype (kept on the local branch `backup/gate-build`, never pushed) added a model list with advisory feature detection and error mapping for missing models. The parts that carry over are listed in decision 8.

Findings that shape the decisions:

- Nebius, NVIDIA, and OpenRouter all offer OpenAI-compatible endpoints, per their own documentation as reported by third-party roundups. Ollama, LM Studio, and vLLM do too.
- Nebius's model list, fetched with `?verbose=true`, includes per-token prices, `context_length`, and `supported_features`. Other providers report fewer or different fields. Which ones is unverified until each is probed.
- Nebius returns stream usage only when `stream_options.include_usage` is set, on a final chunk with no choices. One source says NVIDIA reports usage incrementally, which would break a reader that expects one final chunk. This is unverified.
- NVIDIA's free key is under trial terms that allow evaluation, not production use, and its notice says use is logged. Google and Mistral free tiers use prompts for training. Notices differ per provider.

## Goals / Non-Goals

**Goals:**

- One code path for any OpenAI-compatible provider, with differences held in configuration and not in branches through the code.
- No behavior change for a Nebius user beyond names and routes.
- A preset ships only when it has been probed against a real key.

**Non-Goals:**

- Providers with their own API shape, such as Anthropic's native API. That would be a second adapter and is out of scope.
- Signing in to a provider with OAuth. Keys are pasted.
- Per-user overrides of a provider's capabilities, and several custom providers per user.
- Choosing models. That is `conversation-agent`.

## Decisions

### 1. A provider is a configuration entry plus the user's key

Presets live in `backend/app/providers.yaml`, loaded and validated once at startup, with `PROVIDERS_CONFIG_PATH` for tests. Each entry has:

```yaml
providers:
  nebius:
    label: Nebius Token Factory
    base_url: https://api.tokenfactory.nebius.com/v1/
    key_url: <where to get a key>
    notice: <data-handling text>
    key_required: true
    capabilities:
      model_list: { prices: true, context_length: true, features: true }
      stream_usage: final_chunk        # final_chunk | incremental | none
```

The startup check refuses a missing base URL, an unknown `stream_usage` value, a missing capability, or a duplicate id. The file holds no key. The `custom` provider is not a preset: its base URL is entered by the user and its capabilities are the most cautious set (nothing reported, usage read from a final chunk when present).

`NEBIUS_BASE_URL` is retired in favour of the preset. An operator who needs another base URL edits the file.

**Alternatives:** a `providers` table managed in the UI (rejected: presets are code-adjacent facts an operator should read in the repo, and a database row can drift from what was probed); one environment variable per provider (rejected: several settings each).

### 2. One client builder for every provider

`client_for(session, user, provider_id)` looks up the provider, decrypts that user's key for it, and builds the OpenAI-SDK client with the provider's base URL. It keeps the per-request lifetime and the http-client injection that tests use. A provider with `key_required: false` and no stored key gets a placeholder key, which OpenAI-compatible servers ignore. Nothing outside this function chooses a base URL.

### 3. Data model

`provider_keys` replaces `nebius_api_keys`:

```
id UUID pk, user_id FK ON DELETE CASCADE, provider_id TEXT,
base_url TEXT null,              -- only for the custom provider
encrypted_key ... null,          -- null for a keyless local provider
key_last4 TEXT null, created_at, updated_at
UNIQUE (user_id, provider_id)
```

The existing encryption and the "record copied to another user fails to decrypt" binding are kept, and the provider id is added to what the ciphertext is bound to, so a key cannot be moved between providers. One migration renames the table, adds `provider_id` with a server default of `nebius` and `base_url`, and keeps existing rows. The downgrade restores the old name and drops the new columns.

### 4. Routes

```
GET    /api/providers                 presets + custom, each with key status and notice
PUT    /api/providers/{id}/key        { key, base_url? }  checks with the provider, then stores
DELETE /api/providers/{id}/key
GET    /api/providers/{id}/models     the user's models on that provider
```

`/api/settings/api-key` and `/api/models` are removed. Saving checks the key by listing models. A `custom` provider's `base_url` is validated here.

### 5. The model list

The list call maps each model to `{ id, context_length?, prices?, features }`. What is read depends on the provider's `model_list` capabilities, so a provider that reports nothing yields models with only an id and `unknown` features. Feature information is advisory, using the classifier from the prototype: `supported`, `unconfirmed` (features reported but not tool calling), or `unknown`. The list is fetched per request and not cached here. A cache for the chat's context meter is `conversation-agent`'s concern.

### 6. Errors

`map_nebius_error()` becomes `map_provider_error()`, with a provider name and an optional model id. It maps authentication failures to `provider_key_rejected` for a saved key and `provider_key_invalid` while saving, timeouts and connection failures and 5xx to `provider_unreachable`, a 429 to `provider_rate_limited`, and any other client error that a caller has not claimed to `provider_request_refused` with the provider's message. A missing model is mapped by the caller that knows the model (`conversation-agent`). Renamed codes are new in the frontend's `ApiErrorCode` list, and the Nebius key alert becomes a provider key alert that names the provider.

### 7. Custom provider and its safety

The custom provider is on by default and can be turned off with `ALLOW_CUSTOM_PROVIDER=false` in the environment, which `auth-modes` sets for demo mode. A base URL must be `http` or `https`. On a private install a custom URL usually points at the local machine or the LAN, so private addresses are allowed. On a public instance the setting should be off, because a user-supplied URL there makes the server fetch arbitrary addresses. The design does not try to filter private ranges: an allow-list filter is fragile, and the switch is the control.

### 8. What carries over from the prototype

Brought over from `backup/gate-build` with `gate` removed from names: the feature classifier and its tests, the model list mapping and its tests, the `FakeNebius` test double (renamed `FakeProvider`), the model-missing case in error mapping, and the `pyyaml` dependency and config-loader pattern. Not brought over: the gate registry, overrides, and settings API.

### 9. Frontend

The API key settings section becomes a providers section: one card per provider with its status, the key field, a "Get a key" link, the notice (accepted before the first save), and a Test that lists models. The custom card has a base URL field, hidden when custom providers are off. Existing tests for the Nebius key screen move with it.

### 10. Each preset is probed before it ships

For each of NVIDIA, OpenRouter, and Groq, a task lists models, streams a chat, and checks tool calling and streamed usage with a real key, and records the result in `providers.yaml`. A preset whose usage arrives incrementally needs the stream reader to sum or take the last value, which `conversation-agent` implements from the `stream_usage` capability. A preset that fails tool calling is shipped with that noted, or not shipped.

Groq is dropped from this change (2026-09-22, user decision): only Nebius, NVIDIA, and OpenRouter ship as presets.

**NVIDIA probe (2026-09-22, `https://integrate.api.nvidia.com/v1/`, trial key, no credits purchased):**

- Model list (plain `GET /v1/models`, no verbose flag NVIDIA recognises) reports only `id`, `object`, `created`, `owned_by` - no context length, prices, or features. Capabilities shipped as the cautious set, same as `custom`.
- Streamed usage (`stream_options.include_usage: true`) arrives on a final chunk with empty `choices` and a `total_tokens` usage object, followed by `data: [DONE]` - a clean match for `stream_usage: final_chunk`.
- Tool calling works on the platform: `meta/llama-3.2-11b-vision-instruct` returned a clean `tool_calls` response. One model tried first, `nvidia/nemotron-3.5-lightning-30b-a3b`, hung instead of answering once a `tools` array was added (worked fine without one); reads as a model-specific gap on this NIM deployment, not a platform limit, and doesn't change the shipped capabilities, which don't claim tool-calling support at the model-list level regardless (advisory feature reporting is off for NVIDIA, so every model's `tool_calling` reports `unknown`).

**OpenRouter probe (2026-09-22, `https://openrouter.ai/api/v1/`, real key, tested against the free `nvidia/nemotron-3.5-lightning:free` model so it cost nothing):**

- Model list reports `context_length` and `pricing.{prompt,completion}` in the same shape as Nebius, with no verbose flag needed - full detail by default. Feature/parameter names are reported under `supported_parameters` (every request parameter the model accepts, e.g. `temperature`, `tools`, `reasoning`), not `supported_features` like Nebius. `app/provider_models.py` tries both field names, since both list `tools` the same way when tool calling is accepted; this needed a code change (`SUPPORTED_FEATURES_FIELDS`), not just a `providers.yaml` value.
- Streamed usage arrives attached to the last content chunk itself (`finish_reason: "stop"` and a `usage` object together, not a separate empty-choices trailer like Nebius/NVIDIA), then `data: [DONE]`. Still `stream_usage: final_chunk`: a reader that takes the last chunk's usage field, if present, covers both shapes.
- Tool calling returned a clean `tool_calls` response.
- Ships with the full capability set: `model_list: { prices: true, context_length: true, features: true }`, `stream_usage: final_chunk`.

**Ollama probe (2026-09-22, local `mistral-small3.2` via `ollama serve`, no key, `PROVIDERS_CONFIG_PATH` not involved since Ollama is exercised through the `custom` provider):**

- Model list (`GET /v1/models`) reports only `id`, `object`, `created`, `owned_by` — no `context_length`, no `pricing`, no `supported_features`. Confirms the `custom` provider's cautious `model_list` capabilities (nothing reported).
- Streamed chat (`stream_options.include_usage: true`) never sends a usage chunk, never sends a chunk with `finish_reason` set, and never sends `data: [DONE]` — the stream just ends after the last content chunk. Confirms `stream_usage: final_chunk` as the right cautious default (a reader waiting on a final usage-bearing chunk degrades to "unknown cost" instead of hanging, since the connection closing ends the read either way).
- Tool calling: inconclusive. A request with a `tools` array against the only locally available model (`mistral-small3.2`, 15GB, CPU inference) did not return a response within 6.7 minutes (`HTTP_STATUS:000`, 0 bytes). This is model/hardware speed, not a signal about Ollama's OpenAI-compat tool-calling support one way or the other; the `custom` provider's capabilities don't claim tool-calling support regardless, so this doesn't change the shipped config.

## Risks / Trade-offs

- [A provider's model list has different fields than assumed] → Capabilities are per provider and verified by probe. Missing fields degrade to unknown, never to a wrong value.
- [Streamed usage differs by provider] → It is a declared capability, and a provider without usable usage records the cost as unknown.
- [A free-tier provider's terms forbid what the user does with it] → The notice states the terms as the provider does. The app does not judge whether a use complies.
- [A user-supplied URL on a public instance] → The switch turns it off, and demo mode sets it.
- [Renaming codes and routes breaks the existing screen and tests] → One task group changes both sides together, and a final check searches for the old names.
- [A stored key moves between providers] → The provider id is part of what the ciphertext is bound to.

## Migration Plan

1. Ship the migration, backend, and frontend together, because routes and error codes change.
2. The migration keeps an existing Nebius key as the `nebius` provider's key.
3. Rollback: `alembic downgrade -1` restores the old table name. Keys saved for other providers are dropped.

## Open Questions

None outstanding. Both prior questions are resolved by the 2026-09-22 probes in decision 10: OpenRouter ships as a preset (clean tool calling and usage), and NVIDIA and OpenRouter's `providers.yaml` capabilities reflect what each was actually probed to report, not the cautious default. Groq is dropped from this change.
