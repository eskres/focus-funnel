# conversation-agent Specification

## Purpose

Answers messages with one model that sees the conversation and can use tools, so it can reply, ask a question, search the user's thoughts, or propose a thought to file in a single step. There is no separate routing step.

## Requirements

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

### Requirement: Tools to file and find thoughts

The model SHALL be offered two tools: one that searches the user's thoughts, and one that proposes thoughts to file. A proposal SHALL hold one or more parts, each with a title, a summary, tags, and a category. A tool call SHALL NOT store or change anything by itself: a part is stored only when the user confirms it. The result of a tool SHALL be passed back to the model so it can finish its answer, for a bounded number of rounds. After a proposal, the model's reply SHALL NOT say that anything was saved. The search tool SHALL take a query and, optionally, tags and a start date, and SHALL return the user's matching thoughts in the compact form of thought search, or say that none matched. The thoughts a search returns SHALL be passed to the chat as the answer's sources, and SHALL NOT be shown to the model by id. When the search could match only by words, the tool result SHALL say why in plain words and the model SHALL tell the user; the turn SHALL NOT end with an error.

#### Scenario: Recall question

- **WHEN** a user asks what they filed about milk
- **THEN** the model uses the search tool
- **AND** the chat shows that a search ran

#### Scenario: Clear thing to keep

- **WHEN** a user sends a message that is clearly a to-do or an idea
- **THEN** the model uses the proposal tool
- **AND** the user sees a proposal to review, and nothing is stored yet
- **AND** the model's reply does not say the thought was saved or noted

#### Scenario: Several things to keep

- **WHEN** a user sends `/push buy oat milk and book the dentist`
- **THEN** the model makes one proposal with two parts

#### Scenario: Search finds thoughts

- **WHEN** the search tool runs for a user who has a thought titled `Oat milk` and the query is `milk`
- **THEN** the tool result holds that thought's title, tags, date, and summary
- **AND** the model answers from it
- **AND** the chat receives that thought as a source

#### Scenario: Search narrowed by the model

- **WHEN** a user asks what work ideas they filed this month
- **THEN** the model can call the search tool with the tag `work` and the first of the month as the start date
- **AND** the result holds only thoughts that fit both

#### Scenario: Search finds nothing

- **WHEN** the search tool runs and no thought matches well enough
- **THEN** the tool result says no filed thoughts matched
- **AND** the model tells the user

#### Scenario: Search by words only

- **WHEN** the search tool runs for a user with no saved key for the embedding provider
- **THEN** the tool result holds the matches by words and says that searching by meaning needs that provider's key in settings
- **AND** the model tells the user, and the turn ends normally

#### Scenario: Search before any thought is stored

- **WHEN** the search tool runs for a user who has not stored any thoughts yet
- **THEN** the tool result says no filed thoughts matched, without calling the embedding provider
- **AND** the model tells the user, and nothing is stored

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

The system SHALL steer the model to propose a thought when a discussion reaches a conclusion or a decision, even when there is no to-do or idea in it. The proposal SHALL be a short summary of the key findings, including the model's points the user agreed with, with a title, tags, and a category. The user SHALL be able to expand or trim the summary, and change the title, tags, and category, before confirming. Nothing SHALL be stored without the user's confirmation.

#### Scenario: Decision reached

- **WHEN** a user ends a discussion with `ok I've decided: Rust for the CLI tools, Go for the services`
- **THEN** the chat shows a proposal with a summary of the decision and the category `decision`
- **AND** the user can edit the summary, title, tags, and category

#### Scenario: Model's point agreed with

- **WHEN** the model suggests keeping the services in one repository and the user answers `yes, do that` before deciding
- **THEN** the proposal's summary includes keeping the services in one repository

#### Scenario: Confirm

- **WHEN** a user confirms a proposal
- **THEN** the thought is saved

#### Scenario: Edited before confirming

- **WHEN** a user trims the summary and then confirms
- **THEN** the trimmed text is what is saved

### Requirement: A proposal is held while the conversation carries on

When the user carries on the conversation after a proposal was made, the proposal SHALL be held until every part of it is saved or a later proposal replaces it: the system SHALL NOT propose the same conclusion again on each turn. Only the parts not yet saved SHALL be held. A held proposal SHALL be offered again, with a summary that covers what was added, in three cases: the conversation veers onto a different topic, the user archives the conversation or leaves it, and the user sends `/compact`. Time SHALL NOT bring it back: opening an old conversation SHALL NOT show the proposal again by itself. On a change of topic the system SHALL offer the earlier summary before the new topic continues. A card of a proposal that is no longer held SHALL still be confirmable. When a later proposal replaces a held one, the earlier proposal's unsaved cards SHALL be folded away with a note that a newer proposal replaced them, and the user SHALL be able to show them again.

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

#### Scenario: Every part saved

- **WHEN** a user saves both parts of a two-part proposal and then archives the conversation
- **THEN** no proposal is offered before archiving

#### Scenario: One part left

- **WHEN** a user saves one part of a two-part proposal and then sends `/compact`
- **THEN** the chat offers only the part not saved

#### Scenario: Replaced card folded

- **WHEN** the chat offers a held proposal again on a change of topic, as a new proposal
- **THEN** the earlier card is folded away with a note that a newer proposal replaced it
- **AND** the user can show it and confirm it

#### Scenario: Older card confirmed

- **WHEN** a user confirms a card from a proposal that a later proposal replaced
- **THEN** that card's thought is saved

### Requirement: An unavailable model never falls back to another model

When the conversation's model cannot be used, the system SHALL fail the message with an error that names the model and points the user to the model settings. The system SHALL NOT retry with any other model, and SHALL NOT change the stored settings.

#### Scenario: No model chosen

- **WHEN** a user who has chosen no default model sends a message
- **THEN** the system responds with error code `model_not_set`, pointing to the model settings
- **AND** no model is called

#### Scenario: Model withdrawn

- **WHEN** the provider reports that the conversation's model does not exist or is not available to the key
- **THEN** the system responds with error code `model_unavailable`, naming the model
- **AND** no other model is called

#### Scenario: The provider cannot be reached

- **WHEN** a call times out, cannot connect, or gets a server error from the provider
- **THEN** the system responds with error code `provider_unreachable`
- **AND** no other model is called

#### Scenario: Provider rate limit

- **WHEN** the provider refuses a call because the account is sending too many requests
- **THEN** the system responds with error code `provider_rate_limited`, saying to wait and try again
- **AND** no other model is called

#### Scenario: The provider refuses the call for another reason

- **WHEN** the provider refuses a call with a client error that has no other code
- **THEN** the system responds with error code `provider_request_refused` carrying the provider's message
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
