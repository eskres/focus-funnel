## 1. Probes

- [x] 1.1 Probe NVIDIA and OpenRouter with a real key each (Groq dropped): list models, stream a chat, call a tool, and read streamed usage. Check by recording, in `design.md` decision 10 and in `providers.yaml`, the model list fields each reports, its tool calling result, and how it reports usage
- [x] 1.2 Probe a local OpenAI-compatible server (Ollama) with no key. Check by recording whether its model list, tool calling, and streamed usage work and what the list reports

## 2. Provider configuration

- [x] 2.1 Add `providers.yaml` and its loader with `PROVIDERS_CONFIG_PATH` support and validation, loaded in the lifespan. Check with pytest fixture files that a valid file loads, that a missing base URL, an unknown `stream_usage` value, a missing capability, and a duplicate id each fail at load naming the preset, that the file holds no key, and that the app refuses to start on an invalid file
- [x] 2.2 Add the presets for Nebius, NVIDIA, and OpenRouter (Groq dropped) with the results of task 1.1, and the `custom` provider rules. Check with pytest that every preset loads and that `custom` has the cautious capability set
- [x] 2.3 Add the `ALLOW_CUSTOM_PROVIDER` setting to the app settings. Check with pytest that it defaults to on and that turning it off is read

## 3. Data

- [x] 3.1 Add the `ProviderKey` model and one migration that renames `nebius_api_keys`, adds `provider_id` (default `nebius`) and `base_url`, and keeps existing rows, then reset any local database that cannot run it. Check that `alembic upgrade head` then `downgrade -1` runs cleanly on an empty SQLite database and on the compose Postgres, that a Nebius row survives the upgrade as the `nebius` provider, and that there is a single Alembic head
- [x] 3.2 Bind the ciphertext to the provider id as well as the user. Check with pytest that a record copied to another user, or to another provider of the same user, fails to decrypt

## 4. Client and errors

- [x] 4.1 Bring the model-missing case and the `FakeNebius` double over from `backup/gate-build`, renaming to `FakeProvider`, and replace `client_for()` with the per-provider builder. Check with pytest that the client uses the provider's base URL and that user's key, that a keyless provider gets a placeholder key, and that another user's key is never used
- [x] 4.2 Rename `map_nebius_error()` to `map_provider_error()` and the error codes to `provider_key_missing`, `provider_key_invalid`, `provider_key_rejected`, `provider_unreachable`, `provider_rate_limited`, and `provider_request_refused`. Check with pytest that each maps as specified, that a 429 maps to `provider_rate_limited`, and that another unmapped client error carries the provider's message

## 5. Provider keys API

- [x] 5.1 Add `GET /api/providers` listing presets, the custom provider, key status, and notices. Check with pytest that every preset appears with its key link and notice and that key status is per user
- [x] 5.2 Add `PUT` and `DELETE /api/providers/{id}/key` with the check before saving. Check with pytest for a valid key, an invalid key giving `provider_key_invalid`, an unreachable provider giving `provider_unreachable` with nothing stored, an empty key, a replacement that fails leaving the old key, a delete leaving other providers alone, and a keyless local provider saved with no key
- [x] 5.3 Add the custom provider rules: `base_url` accepted only for `custom`, only `http` and `https`, refused when custom providers are off, and preset URLs unchangeable. Check with pytest for each, with `validation_error` on refusal
- [x] 5.4 Check that keys never leak. Check with pytest that no response and no log entry holds a full key, that the key status holds at most 4 characters, and that two users' keys for one provider never mix

## 6. Model list

- [x] 6.1 Bring the feature classifier and model list mapping and their tests over from `backup/gate-build`, with `gate` removed from names. Check that the brought-over tests pass
- [x] 6.2 Add `GET /api/providers/{id}/models` reading only the fields a provider's capabilities say it reports. Check with pytest against `FakeProvider` that prices and context length are returned when reported and absent otherwise, that features are `supported`, `unconfirmed`, or `unknown`, that a missing key gives `provider_key_missing`, a rejected key `provider_key_rejected`, and an unreachable provider `provider_unreachable` with no partial list, and that two users' lists use their own keys

## 7. Frontend

- [x] 7.1 Rename the frontend error codes and classes and turn the Nebius key alert into a provider key alert naming the provider. Check with Vitest that each new code becomes its error type and that the alert shows the provider name and a link to the provider settings
- [x] 7.2 Replace the API key settings section with the providers section: one card per provider with status, the key field, the "Get a key" link, and a Test. Check with Vitest against mocked responses that every preset card renders, that saving sends the key, that a refused key shows its reason and keeps the earlier state, and that a saved key shows the last 4 characters and the date
- [x] 7.3 Show the data-handling notice before the first save and let the user read it later. Check with Vitest that saving is blocked until the notice is accepted and that the notice is available afterwards
- [x] 7.4 Add the custom provider card with a base URL field, hidden when custom providers are off. Check with Vitest that the field shows and sends the URL and that the card is absent when the server says custom is off

## 8. Cleanup and system check

- [x] 8.1 Remove `/api/settings/api-key`, `NEBIUS_BASE_URL`, the `nebius_*` error codes, and the old Nebius key screen and its tests. Check that a search of `backend/` and `frontend/` for `nebius_` finds only the Nebius preset and its config, and that the suites pass
- [x] 8.2 Run the backend suite on SQLite and on the compose Postgres, and `npm run test`, `npm run lint`, and `npm run build` in `frontend/`. Check that all pass
- [ ] 8.3 On a fresh `docker compose up --build`, save a key for Nebius and one other preset, list each provider's models, and check that a wrong key shows `provider_key_invalid` with the provider's name and that a stored Nebius key from before the upgrade still works
- [ ] 8.4 With an Ollama server and no key, save the custom provider and list its models. Check that it works, and that turning `ALLOW_CUSTOM_PROVIDER` off refuses the same request
