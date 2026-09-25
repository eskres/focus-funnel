## 1. Probes

- [ ] 1.1 Add the official MCP Python SDK in a scratch script, connect to a public or local Streamable HTTP server, and call `initialize`, `tools/list` (with pagination), and `tools/call`. Check by recording in `design.md` decision 1 the pinned version, the client entry point, how it reports timeouts, HTTP 401 and 403, and protocol errors, and the exact names of the tool annotation fields (`readOnlyHint` and the others) and of `structuredContent` and `isError`
- [ ] 1.2 Pick a Google Calendar MCP server that runs with the user's own Google OAuth client, and a stdio-to-Streamable-HTTP bridge, and run both in one container. Check by recording in `design.md` decision 13 both names and pinned versions, and that the scratch script from 1.1 lists the server's tools through the bridge

## 2. Settings and configuration

- [ ] 2.1 Add `MCP_ENABLED`, `MCP_USER_CONNECTORS`, and `MCP_CONNECTORS_PATH` to the backend `Settings`, with the demo guard from design decision 5. Check with pytest that both switches default to false, that demo mode with an explicit `MCP_ENABLED=true` fails naming the setting, and that demo mode otherwise forces it off
- [ ] 2.2 Add the connector configuration loader for `connectors.yaml` (operator connectors and catalog) with the shipped file holding the Google Calendar catalog entry. Check with pytest that a valid file loads, and that a bad name, a duplicate or reserved name, a URL that does not parse, an unknown auth kind, a missing auth environment variable, and a `read_only` tool not in `tools` each fail naming the connector and the field
- [ ] 2.3 Add the `connectors` section to `chat.yaml` and `ChatConfig` (`max_tools`, `tool_rounds`, `connect_seconds`, `call_seconds`, `result_max_chars`). Check with pytest that each value is checked by name as the other sections are
- [ ] 2.4 Add the new variables to `.env.example` with a one-line explanation each. Check by reading it against design decision 5

## 3. Data

- [ ] 3.1 Add the models and one migration for `connectors`, `conversation_connectors`, `tool_actions`, and `users.connector_warning_accepted_at` from design decision 4. Check that `alembic upgrade head` then `downgrade -1` runs cleanly on SQLite and on the compose Postgres, that there is one head, and that `alembic check` finds no changes
- [ ] 3.2 Add auth encryption for connectors with `connector:<id>` as associated data, and register decrypted values with log masking. Check with pytest that a round trip works, that a ciphertext moved to another connector or user fails to decrypt, and that a logged decrypted value is masked
- [ ] 3.3 Extend `delete_user_data` and the ownership helpers to cover connectors and actions. Check with pytest that deleting a user leaves none of their connector, link, or action rows, and that another user's connector responds 404

## 4. MCP client

- [ ] 4.1 Add the SDK to `pyproject.toml` with the version from task 1.1 and wrap it in `app/mcp_client.py` (connect with auth headers, list tools, call a tool, close) behind a small interface. Check with pytest against an in-process Streamable HTTP test server that listing and calling work and that auth headers arrive
- [ ] 4.2 Map failures to `connector_unreachable`, `connector_auth_failed`, and `connector_protocol_error`, with the connect and call timeouts from `chat.yaml`. Check with pytest that a closed port, a 401, a server that answers with plain HTML, and a server that sleeps past `call_seconds` each give the right code within the timeout
- [ ] 4.3 Add result conversion from design decision 8: text kept, `structuredContent` as compact JSON when there is no text, other content replaced by a note, `isError` prefixed, cut at `result_max_chars`, and wrapped in the data marking. Check with pytest for each content kind and for a cut result

## 5. Connector API

- [ ] 5.1 Add `GET /api/connectors` and `POST /api/connectors/warning`, creating and pruning operator rows per design decision 4, all returning 404 when `MCP_ENABLED` is off. Check with pytest that the response lists operator and user connectors, the catalog only when users may add, the warning state, and auth only as last 4 characters, and that a removed operator connector disappears with its conversation links
- [ ] 5.2 Add `POST`, `PATCH`, and `DELETE /api/connectors/{id}` for user connectors with the name and URL checks from design decisions 3 and 11. Check with pytest that adding works, that a bad or duplicate or reserved name, a non-http URL, and a URL with user info give `validation_error`, that the auth value never appears in a response or log, that adding with the switch off gives `403 user_connectors_disabled`, that changing an operator row gives `403 operator_connector`, and that deleting removes the connector from conversations
- [ ] 5.3 Add `POST /api/connectors/{id}/test` per design decision 6. Check with pytest against the test server that tools are stored with starting switches off and badges from the hint and the operator list, that unavailable names are marked, that switches for tools still offered are kept and others dropped, and that a failed test leaves the stored list unchanged and returns the mapped error code
- [ ] 5.4 Add `PATCH /api/connectors/{id}/tools/{tool}`. Check with pytest that switching on an unavailable tool, moving acts to reads, and setting always allow on a reads tool each give `validation_error`, and that moving reads to acts works
- [ ] 5.5 Add the new error codes to `app/errors.py`. Check with pytest that each constructor returns its documented status

## 6. Tool-provider seam

- [ ] 6.1 Add `ToolProvider` and `ToolOutcome` and move the two built-in tools behind `BuiltinTools`, with `Turn` taking a list of providers instead of `Filing` (design decision 2). Check that the existing chat turn, proposal, search tool, command, and SSE tests pass unchanged
- [ ] 6.2 Add `ConnectorTools`: definitions from the stored list with `<name>__<tool>` names, a lazy session per turn, calls through `app/mcp_client.py`, and `aclose()` from `Turn`'s cleanup. Check with pytest using a fake client that only switched-on available tools are offered, that no connection is made when the model calls none, that one session is reused for two calls, and that it is closed when the turn ends or fails
- [ ] 6.3 Build the providers for a turn from the conversation's connectors, use `connectors.tool_rounds` when any is on, check `max_tools` before the first model call, and add the system prompt paragraph only when a connector is on. Check with pytest that a conversation with none on sends exactly today's tools and prompt, that one with a connector on gets its tools and the paragraph, and that a conversation past the limit gets `too_many_tools` with the user's message stored and no model call
- [ ] 6.4 Turn connector failures into tool errors per design decision 9. Check with pytest that an unreachable server, a refused auth, and a timeout each give the model a plain error result, a `tool` end event marked failed, and a turn that ends normally
- [ ] 6.5 Show connector tools in the chat's tool indication with the connector name. Check with Vitest that `calendar__list_events` shows as `calendar: list_events` while it runs and after

## 7. Actions and approval

- [ ] 7.1 Route acts tools through `tool_actions` per design decision 7: write the row, emit the `action` event, and return the "has not run" result. Check with pytest that no call reaches the fake server, that the row and event carry the tool and arguments, and that the stored tool message and `details` let the chat rebuild the card
- [ ] 7.2 Apply always allow and the untrusted-data rule. Check with pytest that an always-allowed acts tool runs without a card at the start of a turn, and that after any connector result in the same turn it needs a card
- [ ] 7.3 Add `POST /api/conversations/{id}/actions/{action_id}`. Check with pytest that approve runs the tool once and stores the capped result, that two concurrent approvals run it once and return the same outcome, that decline calls nothing, that a failed call can be approved again, that approval during a turn gives `conversation_busy`, that a removed or switched-off tool expires the action, and that another user's action gives 404
- [ ] 7.4 Expire pending and failed actions when a turn starts, and add finished actions to the next turn's context as design decision 7 describes. Check with pytest that approving after the next turn started gives `409 action_expired`, and that `build_context` places the approved outcome (with the data marking) or the decline after the action's tool message
- [ ] 7.5 Add `action-card.tsx` and the `action` event to the chat, and the actions on `GET /api/conversations/{id}` for reload. Check with Vitest that the card shows the connector, tool, and arguments, that Approve and Decline call the route and show running, done, failed, declined, and expired, and that a reloaded conversation shows the same cards

## 8. Conversations and the meter

- [ ] 8.1 Add `PUT /api/conversations/{id}/connectors` and `connectors` on the conversation details. Check with pytest that a new conversation has none, that turning one on and off is stored and kept through archive and restore, that a connector with no switched-on tools or one past `max_tools` gives `validation_error` or `422 too_many_tools`, that another user's conversation or connector gives 404, and that the change clears `last_prompt_tokens`
- [ ] 8.2 Count tool definitions in `estimate_tokens`, `meter`, and `check_room`, and return `tool_tokens` with the meter. Check with pytest that turning on a connector raises the estimate by its definitions, that `context_full` accounts for them, and that the `context_full` message mentions turning connectors off when any are on
- [ ] 8.3 Add `connector-picker.tsx` beside the model picker, and the tools figure to `context-meter.tsx`. Check with Vitest that the picker lists connectors, shows "N of 20 tools", disables connectors with no switched-on tools, shows the `too_many_tools` message, and is hidden when connectors are off, and that the meter shows the tools figure and marks an estimate after a toggle

## 9. Connectors settings

- [ ] 9.1 Add `connectors-settings.tsx` with the warning dialog, the connector list, the catalog, the add and edit form, and Test. Check with Vitest against mocked responses that the warning blocks the first add until accepted, that picking the catalog entry fills the form, that auth shows only its last 4 characters, that a failed test shows the plain-words reason, and that operator connectors offer no edit or delete and no add when users may not add
- [ ] 9.2 Add the tool list with the switch, the reads or acts select, and always allow behind a confirmation. Check with Vitest that the select never offers reads for a tool marked acts by the server, that unavailable tools cannot be switched on, and that always allow asks first
- [ ] 9.3 Hide the section when connectors are off. Check with Vitest that the settings page shows no Connectors section when `GET /api/connectors` responds 404

## 10. Deployment and docs

- [ ] 10.1 Add `docker-compose.mcp.yml` with the server and bridge from task 1.2 on the compose network, no published port, and an operator connector pointing at it. Check that `docker compose config` accepts the overlay and that Test on that connector lists its tools
- [ ] 10.2 Write `docs/connectors.md`: the two switches, operator configuration, user connectors, the warning text, what `MCP_USER_CONNECTORS=true` exposes, approval and always allow, the limits and timeouts, and the Google Calendar example with the user's own Google credentials. Link it from the README. Check by following the Google Calendar section on a clean checkout with the overlay from 10.1

## 11. Full system check

- [ ] 11.1 Run the backend suite on SQLite and on the compose Postgres, and `npm run test`, `npm run lint`, and `npm run build` in `frontend/`. Check that all pass
- [ ] 11.2 With the overlay from 10.1 and a small tool-calling model, ask what is on the calendar this week, then ask to add an event. Check that the read runs at once, that the add shows a card and nothing is created until Approve, that the next turn's answer knows the event was created, and that a card left pending expires after another message
- [ ] 11.3 Stop the MCP container mid-conversation and ask about the calendar. Check that the chat shows the connector failure and the answer still finishes
- [ ] 11.4 Start the server with `MCP_ENABLED` unset and in demo mode. Check that no connector route, settings section, or toggle appears, and that demo mode with `MCP_ENABLED=true` refuses to start naming the setting
