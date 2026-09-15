> **Planning status:** Proposal only. Write the specs, design, and tasks when this change is picked up. Depends on `platform-foundation`.

## Why

The /push, /pull, and /explore gates each need to call a Nebius model. Users want to choose the model for each gate. When a message has no slash command, something must decide which gate handles it. A shared gate framework keeps model choice, routing, and model calls in one place. It also leaves room to add more gates after the MVP.

## What Changes

- Add a gate registry with four gates: `router`, `push`, `pull`, and `explore`. Settings, model selection, and the API all loop over the registry, so a new gate needs only a registry entry and a handler. User-defined gates are out of scope.
- Give each gate 3 settings: `model`, `temperature`, and `max_tokens`. System prompt editing is out of scope.
- Keep system defaults for each gate in a server config file (`gates.yaml`), and store user overrides per user in Postgres.
- Pick each gate's settings from the user override when one exists, and from the system default otherwise. "Reset to default" deletes the override.
- Add a settings API:
  - `GET /api/models` lists Nebius models using the user's key.
  - `GET /api/settings/gates` returns each gate's current settings and where they came from (user or system).
  - `PUT /api/settings/gates/{gate_id}` saves an override.
  - `DELETE /api/settings/gates/{gate_id}` resets a gate to its default.
  - `POST /api/settings/gates/{gate_id}/test` sends a small prompt to check the model.
- Check that the model exists before saving an override.
- Let each registry entry declare required model features. For example, `explore` requires tool calling. Saving an override rejects a model that lacks a required feature, and the model dropdown marks such models as not supported for that gate.
- If a gate's model call fails because the model is unavailable, return a clear error that points to settings. Never switch to another model on its own.
- Add gate settings to the settings page: a model dropdown, temperature, max_tokens, Test, and Reset to default.
- Add a chat interface where a leading `/push`, `/pull`, or `/explore` always picks the gate.
- Send messages without a slash command to the router gate. It classifies the message as push, pull, or explore, and the chat shows which gate it picked.
- Stream answers from FastAPI through the Next.js proxy using server-sent events (SSE).
- Until their own changes land, the push, pull, and explore handlers are placeholders that answer with a "not available yet" message.

## Capabilities

### New Capabilities
- `gate-model-config`: Per-gate model settings: system defaults, user overrides, model list, validation, test, reset, and the error when a model is unavailable.
- `message-routing`: Slash-command routing, the router gate's classification, and visible routing results.
- `chat-interface`: The chat screen, message input, streaming answers, and gate labels on messages.

### Modified Capabilities
- `nebius-api-key`: Gate calls and model listing need a saved, valid key and show a clear prompt when no key exists. Confirm while writing specs whether this needs a delta.

## Impact

- **Backend:** gate registry, settings resolver, settings endpoints, router gate, SSE streaming, `gates.yaml`, a new `gate_overrides` table.
- **Frontend:** chat page, gate settings UI, streaming proxy route handlers.
- **External services:** Nebius model listing and chat completions.
