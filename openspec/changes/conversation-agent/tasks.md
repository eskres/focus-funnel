## 1. Groundwork and probes

- [x] 1.1 With `model-providers` landed, bring the reusable backend code over from the local branch `backup/gate-build`, as listed in `design.md` decision 12, with `gate` removed from module, class, and test names (for example `git checkout backup/gate-build -- <path>`, then rename). Check that `uv run pytest` passes for the brought-over code and its tests and that nothing imports a gate registry, resolution, storage, or handler module
- [x] 1.2 Probe forced tool use (`tool_choice` naming a function) on `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`. Done: honoured on 8 of 8 calls including streamed, `required` works, and a forced call ends with `finish_reason: stop`. Recorded in `design.md` decisions 2 and 5
- [x] 1.3 Probe `stream_options.include_usage` on a streamed call. Done: usage arrives on a final chunk with no choices only when the option is set, and matched the non-streamed prompt count. Recorded in `design.md` decision 9. The price unit is not verified: task 14.8 checks it against the Nebius console
- [x] 1.4 With `model-providers` landed, bring the reusable frontend code over from `backup/gate-build` as listed in `design.md` decision 12, with `gate` removed from names. Check that `npm run test`, `npm run lint`, and `npm run build` pass and that a search of `frontend/` for `gate`, `routing_failed`, and `GateModel` finds nothing

## 2. Chat configuration and error codes

- [x] 2.1 Add `chat.yaml` and its loader with `CHAT_CONFIG_PATH` support and validation (temperature default and range, reply length limit, tool round limit, soft context share, recent messages kept by `/compact`, model hint, effort table), loaded in the lifespan. Check with pytest fixture files that a valid file loads, that each missing or out-of-range value fails at load with a message naming it, that the file holds no model id, and that the app refuses to start on an invalid file
- [x] 2.2 Add the backend error codes `model_not_set` (409), `model_unknown` (400), `model_unsupported` (400), `model_unavailable` (409), and `context_full` (409) and `conversation_busy` (409), plus the stream-only `output_limit_reached` and `tool_loop_limit`, and give the provider error mapper from `model-providers` a `model_id` argument. Check with pytest that each constructor returns its documented status and that a provider 404 naming the model maps to `model_unavailable` while other errors map as before
- [x] 2.3 Add the new codes and classes to `frontend/lib/api.ts` and a model alert that links to the model settings. Check with Vitest that each new code becomes its error type and that the model alert links to the model settings

## 3. Data model and migration

- [x] 3.1 Add the `Conversation` and `Message` models from design decision 3, with cascade on user delete and the unique position per conversation. Check with pytest that a duplicate position is rejected, that deleting the user deletes both, and that deleting a conversation deletes its messages
- [x] 3.2 Add the `UsageEvent`, `ChatModel`, and `UserSettings` models. Check with pytest that a duplicate model per user is rejected, that deleting a conversation sets the usage event's conversation to null and keeps the row, and that deleting the user deletes all three
- [x] 3.3 Add one Alembic revision that creates the new tables, with `down_revision` `bf3f5a046190` and no data migration, and reset the local database (it ran the prototype's overrides migration). Check that `alembic upgrade head` then `downgrade -1` runs cleanly on an empty SQLite database and on a fresh compose Postgres, that there is a single Alembic head, and that the app starts on the upgraded database
- [ ] 3.4 Check with a pytest test that one user's conversations, messages, usage, and loadout are never visible to or changed by another user, on each table

## 4. Model settings API

- [ ] 4.1 Add `GET` and `PUT /api/settings/models` returning and replacing the loadout, the default, and the temperature, where a save writes exactly the body. Check with pytest for a valid save, a sixth model refused, a model not in the user's list giving `model_unknown`, a model that does not report tool calling accepted and flagged unconfirmed, an out-of-range temperature giving `validation_error`, and a refused save leaving the earlier loadout unchanged
- [ ] 4.2 Add the effort table to `chat.yaml` with the Nano and `gpt-oss` entries, and return the offered efforts per model from the settings API. Check with pytest that `none` is not offered for Nano, that `none` and `minimal` are not offered for a `gpt-oss` model, and that an unlisted model offers every documented effort
- [ ] 4.3 Add `POST /api/settings/models/test` with a short prompt and a one-tool probe. Check with pytest that a working model reports success with its id, an empty answer reports failure naming the effort, a model rejecting tools gives `model_unsupported`, a missing model gives `model_unavailable`, a refused effort is reported naming the value, a missing key gives `provider_key_missing`, and no stored setting changes in any case
- [ ] 4.4 Use the model list from `model-providers` for loadout choices and the usage estimate. Check with pytest that a loadout entry stores a provider and a model, that a provider with no saved key gives `provider_key_missing`, and that prices and context length come through when the provider reports them
- [ ] 4.5 Check with a pytest test that no model set gives `model_not_set` for a chat call and that removing the default returns to that state

## 5. Conversations API

- [ ] 5.1 Add `GET /api/conversations` (main list newest activity first, and the archived list), `GET /api/conversations/{id}` with all messages including compacted ones, and `PATCH` for title, archived state, model, and effort. Check with pytest for ordering, archive and restore leaving messages unchanged, a title change persisting, and a model change persisting
- [ ] 5.2 Add `DELETE /api/conversations/{id}`. Check with pytest that it removes the conversation and its messages, returns 204, keeps the user's usage records, and returns `not_found` for another user's conversation
- [ ] 5.3 Set a new conversation's title from the start of the first message and its model and effort from the default, leaving the model empty when no default is set. Check with pytest that the title starts with the message, that a later change of the default does not change an existing conversation, and that a conversation with no model takes the default at its next message and stores it
- [ ] 5.4 Apply a model change to a conversation: set the effort to the new model's loadout effort, or none, drop an effort the effort table refuses for it, and clear the stored prompt token count. Check with pytest for each of those, and that the earlier messages are unchanged

## 6. Chat turn and tool loop

- [ ] 6.1 Adapt the brought-over command parser to the new set (`/push`, `/pull`, `/explore`, `/compact`, `/delete`) and the same matching rules. Check with pytest that commands parse case-insensitively with leading whitespace, that `/pushing x`, `remind me to /push later`, `/archive x`, and `/router x` are ordinary text, that a bare `/push` gives `validation_error`, and that `/compact x` and `/delete x` give `validation_error`
- [ ] 6.2 Add the system prompt and the context builder (system prompt, the summary if any, then every non-compacted message). Check with pytest that compacted messages are left out, that the summary comes first, and that tool messages are included in order
- [ ] 6.3 Extend `FakeProvider` with streamed responses: text deltas, tool-call deltas, a final usage chunk, and a mid-stream error. Check with pytest that each shape is delivered as a provider delivers it
- [ ] 6.4 Add the streamed model call that forwards text deltas and collects tool-call deltas, ignoring the reasoning field, and sends the reasoning effort only when set. Check with pytest that text is forwarded in order, that split tool-call arguments are joined, and that no effort is sent when none is set
- [ ] 6.5 Add the tool loop: run the tools, store the tool messages, call the model again, and stop after the configured rounds with `tool_loop_limit`. Check with pytest that a tool result reaches the next call, that the loop stops at the limit keeping the text so far, and that malformed tool arguments go back as a tool error for one retry
- [ ] 6.6 Add `POST /api/chat` with the events from design decision 4, where a failure before the first byte is an error response and one after is an `error` event without `done`. Check with pytest that `conversation` comes first for a new conversation, that events arrive in order and end with `done`, that the user's message is stored before the model is called and kept after a failure, and that an error mid-stream carries the same code
- [ ] 6.7 Force the named tool for `/push` and `/pull` using the method chosen in task 1.2. Check with pytest that `/push text` sends the proposal tool as required and `/pull text` the search tool, and that `/explore text` sends neither
- [ ] 6.8 Add the reply length limit and empty-reply handling. Check with pytest that a reply with `finish_reason` length ends with `output_limit_reached` keeping its text, that an empty reply is reported the same way, and that the server's limit is sent on every call
- [ ] 6.9 Add the model checks and the no-fallback rule. Check with pytest that an unset model gives `model_not_set` before any network call, that a withdrawn model gives `model_unavailable` with no second call to any model, that a provider being unreachable gives `provider_unreachable`, that a provider 429 gives `provider_rate_limited`, and that another client error gives `provider_request_refused`
- [ ] 6.10 Lock a conversation to one running turn. Check with pytest that a second turn started during the first gets `conversation_busy` and that the lock is released after a failure
- [ ] 6.11 Check that conversations are independent. Check with pytest that two conversations on two different models, run at the same time, each call their own model with only their own messages, that a turn in one is not blocked by a turn in the other, and that each usage record names the model that made the call
- [ ] 6.12 Check that a conversation whose model left the loadout keeps working, and that a withdrawn model gives `model_unavailable` after which switching model continues with the same history. Check with pytest for both

## 7. Proposals and held proposals

- [ ] 7.1 Add the `propose_thought` tool: validate its arguments, store the proposal in `held_proposal` and as a message, and emit a `proposal` event, saving nothing. Check with pytest that a valid call emits the proposal and stores nothing else, and that invalid arguments are refused
- [ ] 7.2 Add the confirm endpoint with the `save_thought` seam that answers "not available yet". Check with pytest that confirming with edited text returns the edited text and the not-available outcome, and that the seam can be replaced in a test to report success
- [ ] 7.3 Add the `search_thoughts` stub that returns "not available yet" from one function. Check with pytest that the result reaches the model and that the function can be replaced in a test
- [ ] 7.4 Run a smoke check against a real Nebius key: send a greeting, a to-do, a recall question, an idea, and a `/push` and a `/pull` message. Check that the greeting calls no tool, that each other message calls the expected tool, and that answers stream. The full probe set is task 12.1
- [ ] 7.5 Add the held-proposal note to the turn context so an already-shown conclusion is not proposed again. Check with pytest that the note is present when a proposal is held and absent otherwise, and that a proposal stays held across turns
- [ ] 7.6 Add the forced proposal call used before archive, before `/compact`, and when the model has produced none, recorded with `kind` proposal. Check with pytest that it returns a proposal for a conversation with a discussion, and that it is not called when a held proposal already exists
- [ ] 7.7 Check that time never brings a held proposal back. Check with pytest that opening a conversation with a held proposal after a long time shows it only as held and that no model is called

## 8. Context management

- [ ] 8.1 Store the provider's prompt token count after each answer and emit it in a `usage` event with the model's context length from a five-minute per-user cache. Check with pytest that the count is stored and emitted, that switching model changes the context length, and that a missing context length is emitted as absent
- [ ] 8.2 Add the soft limit: a `compact_suggested` notice once per crossing. Check with pytest that the notice appears when the count passes the configured share, not before, and not again on the next turn
- [ ] 8.3 Add the pre-call estimate and refuse with `context_full` when it cannot fit, mapping a provider context error to the same code. Check with pytest that no model is called for an estimate over the limit, that the user's message is kept, and that a provider context error maps to `context_full`
- [ ] 8.4 Add `/compact` as a chat command that streams a summary draft of all but the recent messages as a `compact_draft` event, with no tools. Check with pytest that the draft is produced, that nothing changes in the stored conversation, and that the call is recorded with `kind` compact
- [ ] 8.5 Add `POST /api/conversations/{id}/compaction` that stores the accepted summary and marks the replaced messages as compacted. Check with pytest that the next call sends the summary and the recent messages only, that the transcript endpoint still returns every message, and that a second compaction includes the first summary
- [ ] 8.6 Check with a pytest test that a failed summary call leaves the conversation unchanged and reports the error
- [ ] 8.7 Add the choice of a larger model for `/compact` when the conversation does not fit its own model. Check with pytest that the response lists the loadout models with a large enough context and their context lengths, that no model is called until one is chosen, and that the chosen model writes the summary and is recorded in usage
- [ ] 8.8 Check that switching model changes the meter's limit and marks the figure as an estimate until the next answer, and that a switch to a smaller context gives `context_full` for the next message. Check with pytest for both

## 9. Usage tracking

- [ ] 9.1 Add the helper that records a `usage_events` row after every model call (chat rounds, `/compact`, forced proposals, tests). Check with pytest that each kind records its tokens and model and that no record holds message text
- [ ] 9.2 Calculate the estimated cost from the per-token prices at the time of the call. Check with pytest for a priced model, an unpriced model recording an unknown cost with tokens, and a call with no reported tokens recording nothing
- [ ] 9.3 Add `GET /api/usage` returning daily totals, the split by model, and the month to date. Check with pytest for ordering, the period parameter, an empty result, and that another user's records never appear
- [ ] 9.4 Add the warning threshold to the model settings API and emit a `usage_warning` notice once per month when it is reached. Check with pytest for a dollar threshold, a token threshold, no repeat in the same month, a repeat in the next month, and no notice when none is set
- [ ] 9.5 Read streamed usage according to each provider's `stream_usage` capability from `model-providers`. Check with pytest against `FakeProvider` that a final chunk is recorded, that incremental reports record the last value, and that a provider with no usage records the cost as unknown

## 10. Frontend: conversations and chat

- [ ] 10.1 Add the typed client for the conversation, chat, and compaction endpoints and update `lib/sse.ts` to the new events. Check with Vitest that each event parses, that events split across chunks parse, and that an unknown event is ignored
- [ ] 10.2 Add the sidebar with the main list, an Archived section, and a new-conversation button, and route `/app/[id]` for a stored conversation. Check with Vitest against mocked responses that conversations list newest first, that an empty list shows its message, and that selecting one loads its messages
- [ ] 10.3 Add rename, archive, and restore to the sidebar row menu. Check with Vitest that each calls its endpoint and moves the row, and that sending a message in an archived conversation moves it back
- [ ] 10.4 Add `/delete` with a confirm dialog, and the same dialog from the row menu. Check with Vitest that confirming calls the delete endpoint and opens a new conversation, that cancelling changes nothing, that `/delete` is not in the command list, and that no proposal or archive text mentions deleting
- [ ] 10.5 Rewrite the chat state around a stored conversation, with the thinking indicator and tool indications. Check with Vitest that sending adds the message and clears the input, that an empty message sends nothing, that the composer is disabled while an answer arrives, that thinking shows before the first text, and that a tool indication shows before later text
- [ ] 10.6 Add the proposal card with editable title, summary, and tags and a Confirm action, and hold it when the user carries on. Check with Vitest that edits are what is confirmed, that the not-available outcome is shown, and that sending another message keeps the conversation going
- [ ] 10.7 Add the composer dropdown for model and effort from the loadout, with the link to the model settings. Check with Vitest that choosing a model sends it with the next message, that `none` is not offered where the table excludes it, that a new conversation starts from the default, and that a conversation's own model is listed and marked when it is not in the loadout
- [ ] 10.8 Add the context meter and the compact notice, and the `/compact` draft dialog with edit, accept, and cancel. Check with Vitest that the meter follows the `usage` event, that accepting calls the compaction endpoint with the edited text, that cancelling changes nothing, that the meter is marked as an estimate after a model switch, and that a conversation too long for its model asks the user to choose a larger loadout model
- [ ] 10.9 Update the error display for `model_not_set`, `model_unavailable`, `context_full`, `output_limit_reached` with a retry, `tool_loop_limit`, `provider_rate_limited`, `provider_request_refused`, `provider_key_missing`, and `conversation_busy`, and show the usage warning notice. Check with Vitest that each renders its message and link and that the user's message stays
- [ ] 10.10 Update the empty-state command list to `/push`, `/pull`, `/explore`, and `/compact`. Check with Vitest that all four appear and `/delete` does not
- [ ] 10.11 Show the held proposal before archive, before `/compact`, and on a topic change from the `proposal` event. Check with Vitest that each shows the card first and that the action then continues, and that opening an old conversation does not show it

## 11. Frontend: settings

- [ ] 11.1 Add the model section to the settings page: loadout slots, the default marked, an effort choice per model, temperature, and the hint. Check with Vitest against mocked responses that a first visit shows "Not set" with the hint, that a model not reporting tool calling carries the unconfirmed note, that a sixth model is refused, and that no token limit field exists
- [ ] 11.2 Add Test and the refusal reasons to the model section. Check with Vitest that a `model_unknown` response names the model, that an empty-answer failure names the effort, and that the displayed values are unchanged after a refusal
- [ ] 11.3 Show the provider key alert, with a link to the provider settings and empty choosers, when a provider's model list loads without a key. Check with a Vitest test that the alert and its link appear
- [ ] 11.4 Add the usage section with an SVG bar chart of daily spend, a period choice, the split by model, the month total, the estimate label, and the link to the provider's console for the balance when one is known. Check with Vitest that bars render for the mocked days, that an empty state shows, that changing the period refetches, and that no balance is shown
- [ ] 11.5 Add the warning threshold field with a unit choice. Check with Vitest that saving sends the unit and amount and that a warning notice from the chat names the threshold

## 12. Prompt tuning and probes

- [ ] 12.1 Add a probe script under `backend/scripts/` that sends a labelled message set (about 40 messages: recall, to-do, idea, greeting, unfinished, discussion, multi-turn, tangent) to a model with the system prompt and the two tools and prints the tool chosen, argument validity, time, and tokens. Check by running it against a real Nebius key and saving the baseline result in the change folder
- [ ] 12.2 Tune the system prompt against the probe set from task 12.1 and record the result. Check that the tool chosen matches the label on at least 90% of cases over two runs and that no greeting or unfinished message triggers a tool
- [ ] 12.3 Probe topic changes: multi-turn discussions with a held proposal followed by an unrelated message, and by a related one. Check that the model offers the held summary on the unrelated one and not on the related one on at least 8 of 10 cases each, otherwise record the decision to compare embeddings instead in `design.md` decision 6
- [ ] 12.4 Probe repeat proposals: 10 long discussions where the user keeps going after a proposal. Check that the same conclusion is not proposed again in more than one of them
- [ ] 12.5 Probe `/compact`: summarise five long conversations and check that the decisions, names, and open questions in a hand-written checklist survive in each summary

## 13. Realign the planned changes

- [ ] 13.1 Update the project context in `openspec/config.yaml` to describe one model with two tools, stored conversations, and no router. Check by reading it against this change's proposal
- [ ] 13.2 Update the proposals for `explore-gate`, `push-and-pull-gates`, and `thought-storage`: sessions become conversations, the tools replace the placeholder handlers, the proposal card replaces the push preview trigger, and account deletion covers conversations and usage. Check that each proposal names this change as a dependency and no longer mentions the router or gates
- [ ] 13.3 After this change is archived, check with `openspec validate --specs` that no spec mentions the router or per-gate models

## 14. Full system check

- [ ] 14.1 Run the backend suite on SQLite and on the compose Postgres, and `npm run test`, `npm run lint`, and `npm run build` in `frontend/`. Check that all pass
- [ ] 14.2 On a fresh `docker compose up --build` with a real Nebius key, check that a new user's first message gives `model_not_set` with a link, that choosing a model in settings makes the chat work, and that the stopped message can be sent again in the same conversation
- [ ] 14.3 In the chat, send a greeting, a to-do, a recall question, and `/explore` text. Check that each behaves as specified, that tool use and thinking show, and that answers stream
- [ ] 14.4 Have a discussion that reaches a decision. Check that a proposal appears, that carrying on holds it, that a topic change offers it, that archiving offers it, and that editing and confirming reports that saving is not available yet
- [ ] 14.5 Reload and use the sidebar. Check that resume shows every message, that archive and restore work, that `/delete` asks and deletes, and that no text suggests deleting
- [ ] 14.6 Switch model and effort in the input box mid-conversation. Check that the next answer uses the new model and that the context meter changes with its context length
- [ ] 14.7 Fill a conversation past the soft limit and use `/compact`. Check that the suggestion appears, that the draft can be edited, that accepting lowers the meter, and that the transcript still shows everything
- [ ] 14.8 Check the usage section against a few calls. Check that the estimate matches the tokens shown for one call at the listed prices, that a day's estimate is within a few percent of the same day in the Nebius console (this verifies the price unit), that the graph and month total update, and that a low warning threshold gives one notice
- [ ] 14.9 Point the default at a withdrawn model or revoke the key, and send a message. Check that the chat shows the error with a link and that no answer from another model appears
- [ ] 14.10 Run two conversations on two different models at once, with a model switch in one of them, and remove one model from the loadout. Check that each answer comes from its own conversation's model, that both keep working, that the meters follow each conversation, and that usage lists both models
