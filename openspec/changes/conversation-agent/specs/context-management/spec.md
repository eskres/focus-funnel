## Purpose

Keeps a long conversation inside the model's context window. The user sees how full it is, is advised to compact before it fills, and can replace older turns with a summary they can edit.

## ADDED Requirements

### Requirement: The chat shows how full the context is

The chat SHALL show how much of the conversation model's context window is in use. The figure SHALL be updated after each answer from the token count the provider reports for the call, and SHALL use the context length reported for the conversation's current model. It SHALL be recalculated when the user switches model.

#### Scenario: Meter after an answer

- **WHEN** an answer finishes
- **THEN** the meter shows the reported prompt tokens against the model's context length

#### Scenario: Switching model

- **WHEN** a user switches to a model with a smaller context length
- **THEN** the meter shows the conversation against the new limit
- **AND** the figure is marked as an estimate until the next answer, because models count tokens differently

#### Scenario: Switching to a model that cannot hold the conversation

- **WHEN** a user switches to a model whose context is smaller than the conversation
- **THEN** the meter shows the conversation over the limit
- **AND** the next message gets `context_full` until the user compacts or switches back

#### Scenario: Context length unknown

- **WHEN** the provider reports no context length for the model
- **THEN** the meter shows the tokens in use with no limit

### Requirement: The chat suggests compacting before the context is full

When the tokens in use pass a configured share of the context length, the chat SHALL suggest `/compact`. The suggestion SHALL NOT block sending, and SHALL be made once per crossing.

#### Scenario: Soft limit passed

- **WHEN** an answer takes the conversation past the configured share
- **THEN** the chat suggests `/compact`
- **AND** the user can still send messages

#### Scenario: Suggestion is not repeated

- **WHEN** the user carries on without compacting
- **THEN** the suggestion is not shown again on every message

### Requirement: A message that cannot fit is refused

When a message would take the conversation past the model's context length, the system SHALL NOT call the model and SHALL NOT drop earlier turns silently. It SHALL respond with error code `context_full` and advise `/compact`, a model with a larger context, or a new conversation.

#### Scenario: Conversation is full

- **WHEN** a user sends a message that would exceed the context length
- **THEN** the system responds with `context_full`
- **AND** the user's message is kept in the conversation and no model is called

### Requirement: /compact replaces older turns with a summary

A message that is only `/compact` SHALL ask the conversation's model to write a summary of the older turns. The chat SHALL show the summary and let the user edit it and accept it or cancel. Only on accepting SHALL the summary replace the older turns for the model. The most recent turns, in a configured number, SHALL be kept as they are. Replaced turns SHALL stay visible in the conversation, marked as compacted. A conversation SHALL be compactable again later. A held proposal to file a thought SHALL be offered before compacting. When the conversation is too long for the conversation's model to summarise, the chat SHALL show the loadout models whose context is large enough, with their context lengths, and let the user choose one for that summary. The system SHALL NOT choose one, and SHALL NOT use another model without the user's choice.

#### Scenario: Compact and accept

- **WHEN** a user sends `/compact` and accepts the summary
- **THEN** later calls send the summary and the latest turns to the model, not the older turns
- **AND** the meter shows a lower figure

#### Scenario: Edit the summary

- **WHEN** a user edits the summary before accepting
- **THEN** the edited text is what the model receives later

#### Scenario: Cancel

- **WHEN** a user cancels
- **THEN** the conversation the model sees is unchanged

#### Scenario: Replaced turns stay visible

- **WHEN** a conversation has been compacted and is resumed later
- **THEN** every stored message is still shown, with the replaced ones marked as compacted

#### Scenario: Conversation too long for its own model

- **WHEN** a user sends `/compact` and the conversation does not fit the conversation's model
- **THEN** the chat offers the loadout models with a large enough context and waits for the user to choose one
- **AND** no model is called until the user chooses

#### Scenario: Summary fails

- **WHEN** the summary call fails
- **THEN** the conversation is unchanged and the chat shows the error

#### Scenario: Compact with text

- **WHEN** a user sends `/compact` followed by other text
- **THEN** nothing is compacted
- **AND** the system responds with HTTP 422 and error code `validation_error`, saying the command takes no message
