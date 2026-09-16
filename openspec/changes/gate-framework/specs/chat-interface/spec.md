## Purpose

The chat screen where a user writes messages and reads answers. Answers appear a piece at a time as the model produces them, and each answer is labelled with the gate that handled it.

## ADDED Requirements

### Requirement: Sending a message

The chat screen SHALL offer a message input and a way to send it. A sent message SHALL appear in the conversation straight away, and the input SHALL be cleared and ready for the next message. A message that is empty or only whitespace SHALL NOT be sent.

#### Scenario: Sending text

- **WHEN** a logged-in user types a message and sends it
- **THEN** the message appears in the conversation as the user's message
- **AND** the input is cleared

#### Scenario: Empty message

- **WHEN** a user tries to send an empty message or one made only of whitespace
- **THEN** nothing is sent and the conversation does not change

#### Scenario: Sending while an answer is still arriving

- **WHEN** an answer is still arriving
- **THEN** the user cannot send another message until that answer has finished or failed

### Requirement: Answers arrive a piece at a time

An answer SHALL be shown as it is produced, not only when it is complete. Each piece SHALL appear as it arrives.

#### Scenario: Partial answer visible

- **WHEN** the first part of an answer arrives and the rest has not
- **THEN** the part that arrived is visible in the conversation
- **AND** the chat shows that the answer is still being written

#### Scenario: Answer completes

- **WHEN** the last part of an answer arrives
- **THEN** the chat stops showing the answer as in progress
- **AND** the full answer text is the parts joined in the order they arrived

#### Scenario: Connection drops in the middle

- **WHEN** the connection breaks while an answer is arriving
- **THEN** the part already received stays in the conversation
- **AND** the chat shows that the answer was cut short and can be sent again

### Requirement: Each answer is labelled with its gate

Every answer SHALL show which gate handled it and whether that gate came from the user's command or from the router. The label SHALL appear as soon as the gate is known, before the answer is complete.

#### Scenario: Label on a routed answer

- **WHEN** a message with no command is answered
- **THEN** the answer shows the gate that handled it and that the router chose it

#### Scenario: Label on a commanded answer

- **WHEN** a message that began with `/push` is answered
- **THEN** the answer shows the push gate and that the command chose it

#### Scenario: Label appears before the text

- **WHEN** the gate is known but no answer text has arrived
- **THEN** the label is already shown for that answer

### Requirement: Errors are shown in the chat

When a message cannot be answered, the chat SHALL show the reason in place of the answer, and the user's message SHALL stay in the conversation. Errors about the Nebius key SHALL link to the API key settings. An error about a gate's model SHALL link to the gate settings.

#### Scenario: No Nebius key saved

- **WHEN** a user with no saved Nebius key sends a message
- **THEN** the chat shows that a Nebius API key is needed, with a link to the API key settings

#### Scenario: Gate model unavailable

- **WHEN** a gate's model cannot be used
- **THEN** the chat shows which gate and model failed, with a link to the gate settings
- **AND** the chat does not show an answer from a different model

#### Scenario: Routing failed

- **WHEN** the router cannot classify a message
- **THEN** the chat shows a message asking the user to start with `/push`, `/pull`, or `/explore`

#### Scenario: User message kept after a failure

- **WHEN** any error is shown for a message
- **THEN** the user's message is still visible in the conversation

### Requirement: Slash commands are discoverable

The chat screen SHALL show the available commands `/push`, `/pull`, and `/explore` with a one-line description of each, so a user can see them without leaving the chat.

#### Scenario: First visit to the chat

- **WHEN** a user opens the chat with no messages in the conversation
- **THEN** the screen lists `/push`, `/pull`, and `/explore` with a short description of each

### Requirement: The conversation lasts for the visit only

This release SHALL keep the conversation in the browser for the current visit and SHALL NOT store it on the server. Reloading the chat SHALL start an empty conversation.

#### Scenario: Reload

- **WHEN** a user reloads the chat screen after exchanging messages
- **THEN** the conversation is empty

#### Scenario: Nothing stored on the server

- **WHEN** a user sends messages in the chat
- **THEN** no conversation history is stored for later visits
