## Why

A first design routed every message through a router model to one of four gates, each with its own model settings. A prototype of it was built and measured on a real account. It is not part of this change and was never pushed; it is kept on a local branch. The router took about 1 s for a clear message and 4 to 5 s for an unclear one, and it had no memory of the conversation. A reasoning model could also spend its whole token budget thinking and return nothing. Every message paid for context twice, once in the router and once in the gate.

One model that sees the whole conversation and has tools can answer, ask a question, search, or propose a thought to file, all in one call. Probed on a real account with `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, it picked the correct tool on 32 of 34 runs, and it streams tool calls. The push, pull, and explore behavior does not exist yet, so nothing is lost by choosing this design first. Users also need to leave a conversation and come back to it, and a discussion should end in something worth filing.

## What Changes

- Add one chat model that sees the conversation and has two tools: `search_thoughts` (what `/pull` will do) and `propose_thought` (what `/push` will do). There is no router and no classification step.
- Add slash commands: `/push` and `/pull` make the model use that tool. `/explore` starts or continues a discussion. A message with no command is a normal turn in the conversation. `/explore` is the default mode, so the model may ask a question or reply in plain text.
- Store conversations and their messages per user. Add a sidebar on the left of the chat that lists conversations, newest first, with resume, archive, and restore from archive. `/delete` deletes the current conversation for good after a confirmation, and nothing in the product ever suggests it.
- Make every discussion end in a proposal to file a thought. The model proposes a short summary at a fitting point, and the user can expand or trim it before anything is saved. If the user carries on, the proposal is held and not repeated. It comes back when the conversation veers onto a different topic, when the user archives or leaves, and on `/compact`. Coming back to an old conversation does not bring it back.
- Settings: one default chat model, a loadout of other models the user may switch to, and a reasoning effort for each. Temperature is a setting. The maximum reply length is not: the server applies its own cap and says plainly when a reply hits it. Users list the models their own Nebius key can use, with advisory feature information.
- Add a model and effort dropdown to the input box. The choice is saved with the conversation, so several conversations can use different models at the same time. A new conversation starts from the default, and later changes to the default or the loadout do not change an existing conversation. Which efforts a model accepts comes from server configuration, because the model list does not say.
- Add a context meter and a soft limit. Past the limit, the chat suggests `/compact`. `/compact` replaces older turns with an editable summary and keeps the latest turns as they are.
- Record the tokens and estimated cost of every model call. Settings shows daily spend as a graph, spend by model, and the month's total, and lets the user set a warning threshold. Nebius has no balance or usage API for an inference key, so the account balance is not shown; settings links to the Nebius console.
- Run tools in a tool-calling loop over the stream. Until `thought-storage` and `push-and-pull-gates` land, the search tool and the confirm step answer that they are not available yet.
- Add a chat screen that streams answers through the existing proxy over server-sent events, with a thinking indicator, tool indications, and errors that link to the place that fixes them.
- **Replaces `gate-framework`.** That planned change is removed, because this design supersedes it.

## Capabilities

### New Capabilities

- `conversations`: Stored conversations, the sidebar, resume, archive and restore, and `/delete`.
- `conversation-agent`: One model with the conversation as context and two tools, slash commands, and the rule that a discussion ends in a proposal to file.
- `chat-interface`: The chat screen: sending, streaming, thinking and tool indications, the proposal card, errors, and the command list.
- `chat-model-loadout`: The default model, the loadout, the per-conversation model and effort, temperature, and the effort table.
- `context-management`: The context meter, the soft limit, and `/compact`.
- `usage-tracking`: Usage records, the spend graph, and the warning threshold.

### Modified Capabilities

- `nebius-api-key`: Adds listing the models a user's own key can use.

## Impact

- **Backend:** new `conversations`, `messages`, `usage_events`, `chat_models`, and `user_settings` tables in one migration; a tool-calling loop; `/compact`; usage recording; conversation, model settings, and usage endpoints; a model list endpoint; a `chat.yaml` config file that includes the reasoning effort table.
- **Frontend:** the chat screen, conversation sidebar, composer dropdown, context meter, held-proposal and summary editor, and in settings the model section, usage graph, and warning setting.
- **API:** `POST /api/chat` takes a conversation id and returns conversation, tool, proposal, usage, and notice events. New error codes: `model_not_set`, `model_unknown`, `model_unsupported`, `model_unavailable`, `context_full`, `conversation_busy`, `nebius_rate_limited`, and `nebius_request_refused`.
- **Data:** `thought-storage`'s "delete my data" must also delete conversations, messages, and usage records.
- **Other planned changes:** `explore-gate` mostly merges into this change, and `push-and-pull-gates` and `thought-storage` need updating for the tools. Their proposals and the `openspec/config.yaml` project context still describe a router and per-gate models. This change updates them in its last task group.
- **Dependencies:** `pyyaml` for the config file. No frontend dependency: charts are small SVG components.
