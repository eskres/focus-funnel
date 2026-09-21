## Purpose

Answers messages with one model that sees the conversation and can use tools, so it can reply, ask a question, search the user's thoughts, or propose a thought to file in a single step. There is no separate routing step.

## ADDED Requirements

### Requirement: One model answers with the conversation as context

For each message, the system SHALL call the conversation's model once to start the answer, passing the conversation so far as context, subject to the context limit. The model SHALL use the conversation's temperature and reasoning effort. The system SHALL NOT call any other model to decide how a message is handled. The reasoning effort SHALL be sent only when one is set.

#### Scenario: The model sees earlier turns

- **WHEN** a user sends a second message that refers to the first
- **THEN** the model receives both messages and the first answer

#### Scenario: One call for a plain reply

- **WHEN** a user sends a greeting
- **THEN** the system makes one model call and streams its reply
- **AND** no other model is called

#### Scenario: Settings in force

- **WHEN** a conversation uses a model with an effort set
- **THEN** the call uses that model, the user's temperature, and that effort

### Requirement: Slash commands

A message that begins with a command SHALL be handled as that command. The command SHALL be matched at the start of the message, ignoring leading whitespace, without regard to letter case, and only when followed by whitespace or the end of the message. The commands are `/push`, `/pull`, `/explore`, `/compact`, and `/delete`. A word that only starts like a command, a command that is not at the start, and any other slash word SHALL be ordinary text. `/push` and `/pull` SHALL make the model use the matching tool on the rest of the message. `/explore` SHALL treat the rest of the message as an ordinary turn. `/push`, `/pull`, and `/explore` SHALL need text after them. `/compact` and `/delete` SHALL take no text after them.

#### Scenario: Push command

- **WHEN** a user sends `/push buy oat milk`
- **THEN** the model receives `buy oat milk` and is required to use the thought proposal tool

#### Scenario: Pull command

- **WHEN** a user sends `/Pull what did I say about rent?`
- **THEN** the model receives the question and is required to use the search tool

#### Scenario: Explore command

- **WHEN** a user sends `/explore how should I organise my notes`
- **THEN** the message is an ordinary turn with the command removed

#### Scenario: Leading whitespace

- **WHEN** a user sends a message that begins with spaces followed by `/explore an idea`
- **THEN** it is handled as the explore command

#### Scenario: Not a command

- **WHEN** a user sends `/pushing the deadline again`, `remind me to /push this later`, or `/archive something`
- **THEN** the message is ordinary text

#### Scenario: Command with no text

- **WHEN** a user sends only `/push`
- **THEN** no model is called
- **AND** the system responds with HTTP 422 and error code `validation_error`, saying the command needs a message

#### Scenario: Empty message

- **WHEN** a user sends an empty message or one made only of whitespace
- **THEN** no model is called
- **AND** the system responds with HTTP 422 and error code `validation_error`

### Requirement: Two tools for the thoughts

The model SHALL be offered two tools: one that searches the user's thoughts, and one that proposes a thought to file, with a title, a summary, and tags. A tool call SHALL NOT store or change anything by itself: a proposal is stored only when the user confirms it. The result of a tool SHALL be passed back to the model so it can finish its answer, for a bounded number of rounds. Until thought storage exists, the search tool SHALL return a result saying it is not available yet and the model SHALL tell the user, and confirming a proposal SHALL report that saving is not available yet and keep the proposal's text.

#### Scenario: Recall question

- **WHEN** a user asks what they filed about milk
- **THEN** the model uses the search tool
- **AND** the chat shows that a search ran

#### Scenario: Clear thing to keep

- **WHEN** a user sends a message that is clearly a to-do or an idea
- **THEN** the model uses the proposal tool
- **AND** the user sees a proposal to review, and nothing is stored yet

#### Scenario: Search before thought storage exists

- **WHEN** the search tool runs before thought storage exists
- **THEN** the tool result says it is not available yet
- **AND** the model tells the user, and nothing is stored

#### Scenario: Confirm before thought storage exists

- **WHEN** a user confirms a proposal before thought storage exists
- **THEN** the card says saving is not available yet
- **AND** the proposal's text stays available to copy

#### Scenario: Bounded rounds

- **WHEN** the model keeps calling tools without finishing
- **THEN** the system stops after the configured number of rounds
- **AND** the chat shows that the answer could not be completed

### Requirement: The model asks instead of guessing

The system SHALL steer the model to reply in plain text, without a tool, to a greeting, to small talk, and to a message that looks unfinished, and to ask a short question when it cannot tell what the user wants. A greeting SHALL NOT be filed.

#### Scenario: Greeting

- **WHEN** a user sends `Hello`
- **THEN** the model replies with a short greeting and no tool runs

#### Scenario: Unfinished message

- **WHEN** a user sends `I need to`
- **THEN** the model asks what the user wants to say and no tool runs

### Requirement: A discussion ends in a proposal to file

The system SHALL steer the model to propose a thought when a discussion reaches a conclusion or a decision, even when there is no to-do or idea in it. The proposal SHALL be a short summary of the key findings, with a title and tags. The user SHALL be able to expand or trim the summary, and the title and tags, before confirming. Nothing SHALL be stored without the user's confirmation.

#### Scenario: Decision reached

- **WHEN** a user ends a discussion with `ok I've decided: Rust for the CLI tools, Go for the services`
- **THEN** the chat shows a proposal with a summary of the decision
- **AND** the user can edit the summary, title, and tags

#### Scenario: Confirm

- **WHEN** a user confirms a proposal and thought storage exists
- **THEN** the thought is handed to thought storage for saving

#### Scenario: Edited before confirming

- **WHEN** a user trims the summary and then confirms
- **THEN** the trimmed text is what is handed on

### Requirement: A proposal is held while the conversation carries on

When the user carries on the conversation after a proposal was made, the proposal SHALL be held: the system SHALL NOT propose the same conclusion again on each turn. A held proposal SHALL be offered again, with a summary that covers what was added, in three cases: the conversation veers onto a different topic, the user archives the conversation or leaves it, and the user sends `/compact`. Time SHALL NOT bring it back: opening an old conversation SHALL NOT show the proposal again by itself. On a change of topic the system SHALL offer the earlier summary before the new topic continues.

#### Scenario: User carries on

- **WHEN** a user keeps discussing the same topic after a proposal was shown
- **THEN** the chat does not show the proposal again

#### Scenario: Topic changes

- **WHEN** a user with a held proposal sends a message about an unrelated topic
- **THEN** the chat offers the held summary first
- **AND** the new topic then continues

#### Scenario: Archive with a held proposal

- **WHEN** a user archives a conversation that has a held proposal
- **THEN** the chat offers the proposal before archiving

#### Scenario: Compact with a held proposal

- **WHEN** a user sends `/compact` with a held proposal
- **THEN** the chat offers the proposal before compacting

#### Scenario: Returning to an old conversation

- **WHEN** a user opens a conversation with a held proposal after a long time and carries on
- **THEN** the conversation continues as normal and the proposal is not shown again by itself

#### Scenario: Not suggesting deletion

- **WHEN** a proposal is offered
- **THEN** the offer does not suggest deleting the conversation

### Requirement: An unavailable model never falls back to another model

When the conversation's model cannot be used, the system SHALL fail the message with an error that names the model and points the user to the model settings. The system SHALL NOT retry with any other model, and SHALL NOT change the stored settings.

#### Scenario: No model chosen

- **WHEN** a user who has chosen no default model sends a message
- **THEN** the system responds with error code `model_not_set`, pointing to the model settings
- **AND** no model is called

#### Scenario: Model withdrawn

- **WHEN** Nebius reports that the conversation's model does not exist or is not available to the key
- **THEN** the system responds with error code `model_unavailable`, naming the model
- **AND** no other model is called

#### Scenario: Nebius cannot be reached

- **WHEN** a call times out, cannot connect, or gets a server error from Nebius
- **THEN** the system responds with error code `nebius_unreachable`
- **AND** no other model is called

#### Scenario: Nebius rate limit

- **WHEN** Nebius refuses a call because the account is sending too many requests
- **THEN** the system responds with error code `nebius_rate_limited`, saying to wait and try again
- **AND** no other model is called

#### Scenario: Nebius refuses the call for another reason

- **WHEN** Nebius refuses a call with a client error that has no other code
- **THEN** the system responds with error code `nebius_request_refused` carrying Nebius's message
- **AND** no other model is called

#### Scenario: Model rejects tools

- **WHEN** the model rejects the tools it was offered
- **THEN** the system responds with error code `model_unsupported`, naming tool calling

### Requirement: Conversations run independently

Each conversation SHALL use its own stored model and effort. A turn running in one conversation SHALL NOT block a turn in another conversation of the same user, whether in the same browser tab or another. Only one turn at a time SHALL run in a single conversation.

#### Scenario: Two conversations, two models

- **WHEN** a user has one conversation on model A and another on model B and sends a message in each
- **THEN** each message is answered by its own conversation's model
- **AND** neither answer uses the other conversation's messages

#### Scenario: Turns overlap in different conversations

- **WHEN** a user sends a message in a second conversation while the first is still answering
- **THEN** both answers arrive

#### Scenario: Second turn in the same conversation

- **WHEN** a user sends a message in a conversation that is still answering, from another tab
- **THEN** the system responds with error code `conversation_busy`
- **AND** the running turn is not affected

### Requirement: A reply that runs out of room is reported

The system SHALL apply its own limit on the length of a model's reply, which the user cannot change. When a reply stops because it reached that limit, the chat SHALL keep any text received, say that the model ran out of room, and offer to try again or to use a lower reasoning effort. An empty reply SHALL be reported the same way and SHALL NOT be shown as a successful answer.

#### Scenario: Limit reached mid-answer

- **WHEN** a reply stops because it reached the limit
- **THEN** the received text stays in the conversation
- **AND** the chat says the model ran out of room and offers to try again

#### Scenario: Reasoning uses all the room

- **WHEN** a model spends the whole limit reasoning and writes no answer
- **THEN** the chat says the model ran out of room while thinking
- **AND** it suggests a lower reasoning effort or another model
