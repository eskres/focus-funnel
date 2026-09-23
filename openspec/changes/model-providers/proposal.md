> Depends on `platform-foundation` (archived). Must land before `conversation-agent`.

## Why

The app talks to one provider, Nebius, with one saved key. Users want a free NVIDIA key to try the app, OpenRouter as an alternative, and local models such as Ollama for private and air-gapped self-hosting. Every one of those speaks an OpenAI-compatible API, so most of the work is a per-provider base URL and key, plus honest handling of the differences: what the model list reports, how token usage is reported, and how each provider treats prompts. There are no users yet and `conversation-agent` has not started storing model choices, so this is the cheapest moment to generalise.

## What Changes

- Replace the single Nebius key with one key per user per provider. A provider is an OpenAI-compatible endpoint. The server ships presets for Nebius, NVIDIA, and OpenRouter, and offers a custom provider with a base URL for Ollama, LM Studio, or vLLM.
- Keep the key rules as they are today: the key is checked with the provider before it is stored, stored encrypted, never returned in full, and used only on the server for that user.
- Hold each provider's differences in server configuration: its base URL, where to get a key, a data-handling notice, what its model list reports (prices, context length, features), and how it reports token usage in a stream. A preset ships only after it has been probed.
- List the models a user's key can use, per provider, with advisory feature information (moved here from the earlier Nebius-only design).
- Use provider-neutral error codes: `provider_key_missing`, `provider_key_invalid`, `provider_key_rejected`, `provider_unreachable`, `provider_rate_limited`, and `provider_request_refused`. A 429 and any other unmapped client error no longer surface as internal errors.
- Let an operator disable the custom provider URL in server configuration, so a public instance cannot be pointed at internal addresses.
- Show a provider's data-handling notice before its key is first used.
- **BREAKING (internal):** replace the `nebius_api_keys` table, the `/api/settings/api-key` routes, the `nebius_*` error codes, and the Nebius key settings screen. A migration renames the table and keeps existing rows as the `nebius` provider, but the ciphertext binding changes (decision 3), so a key saved before the upgrade cannot be read and is entered again. Nothing is live, so local databases are reset.

## Capabilities

### New Capabilities

- `provider-keys`: One key per user per provider: save, check, replace, delete, status, and clear errors.
- `model-providers`: The provider presets and custom provider, provider configuration, per-provider model list with feature information, the data-handling notice, and provider error mapping.

### Modified Capabilities

- `nebius-api-key`: Every requirement is removed and replaced by `provider-keys`.

## Impact

- **Backend:** `nebius.py` becomes a provider module with a client built from a provider and a key; new `provider_keys` table by migration; a `providers.yaml` config file; provider, key, and model list endpoints; renamed error codes and error mapper.
- **Frontend:** the API key settings section becomes a providers section with one card per provider; the Nebius key alert becomes a provider key alert; error codes and classes are renamed.
- **API:** `GET /api/providers`, `PUT` and `DELETE /api/providers/{id}/key`, and `GET /api/providers/{id}/models`. The `/api/settings/api-key` routes are removed.
- **Other changes:** `conversation-agent` stores a provider with each model choice and depends on this change. `thought-storage` embeds through the same provider seam. `auth-modes` restricts the custom URL in demo mode.
- **Dependencies:** none new.
