# chat-interface Specification

## Purpose

The chat screen where a user writes messages and reads answers. Answers appear a piece at a time as the model produces them, with the model's thinking and tool use shown, and problems are explained in place with a link to where they can be fixed.

## Requirements

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
- **THEN** the user cannot send another message in that conversation until that answer has finished or failed

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

### Requirement: Tool use is shown with the answer

When the model uses a tool, the chat SHALL show which tool is running, for example that the user's thoughts are being searched or that a thought is being proposed. The indication SHALL appear as soon as the tool call starts, before any text that follows it, and SHALL be replaced by the result when the tool finishes.

#### Scenario: Search shown while it runs

- **WHEN** the model starts a search of the user's thoughts
- **THEN** the chat shows that a search is running before any text of the answer appears

#### Scenario: Plain reply

- **WHEN** the model answers with no tool
- **THEN** the chat shows no tool indication

### Requirement: Thinking is shown

While the model is working and no text has arrived yet, the chat SHALL show that the model is thinking. The indication SHALL end when the first text or tool call arrives, or the answer fails.

#### Scenario: Waiting for the first text

- **WHEN** a message has been sent and no part of the answer has arrived
- **THEN** the chat shows that the model is thinking

#### Scenario: First text arrives

- **WHEN** the first text of the answer arrives
- **THEN** the thinking indication is replaced by the text

### Requirement: A proposal can be reviewed in the chat

When the model proposes a thought, the chat SHALL show the title, summary, tags, and category in a card the user can edit, with a way to confirm. A proposal with several parts SHALL show one card per part, grouped, with a way to merge them. The user SHALL be able to carry on the conversation without confirming. A confirmed card SHALL show that the thought was saved, with a link that opens it, or the reason it was not saved. Cards SHALL come back, with their saved state, when the conversation is opened again.

#### Scenario: Edit and confirm

- **WHEN** a proposal appears and the user edits the summary and confirms
- **THEN** the card shows that the edited thought was saved, with a link to it

#### Scenario: Carry on instead

- **WHEN** a proposal appears and the user sends another message
- **THEN** the conversation continues and the proposal is held

#### Scenario: Split proposal

- **WHEN** the model proposes three parts in one proposal
- **THEN** the chat shows three cards together, with a merge button

#### Scenario: Reopened conversation

- **WHEN** a user saves one card, leaves, and opens the conversation again
- **THEN** that card shows as saved with its link
- **AND** a card not yet confirmed can still be edited and confirmed

### Requirement: Errors are shown in the chat

When a message cannot be answered, the chat SHALL show the reason in place of the answer, and the user's message SHALL stay in the conversation. Errors about a provider key SHALL link to the provider settings. Errors about the model, including no model chosen and an unavailable model, SHALL link to the model settings. A full context SHALL advise `/compact`, a model with a larger context, or a new conversation. A reply that ran out of room SHALL offer to try again.

#### Scenario: No provider key saved

- **WHEN** a user with no saved key for their conversation's provider sends a message
- **THEN** the chat shows that a key for that provider is needed, with a link to the provider settings

#### Scenario: No model chosen

- **WHEN** a user with no default model sends a message
- **THEN** the chat shows that a model is needed, with a link to the model settings
- **AND** no answer from any model appears

#### Scenario: Model unavailable

- **WHEN** the conversation's model cannot be used
- **THEN** the chat shows which model failed, with a link to the model settings
- **AND** the chat does not show an answer from a different model

#### Scenario: Context full

- **WHEN** a message cannot fit in the model's context
- **THEN** the chat says the conversation is full and advises `/compact`, a model with a larger context, or a new conversation

#### Scenario: Reply ran out of room

- **WHEN** a reply stops at the system's length limit
- **THEN** the chat keeps any text received, says the model ran out of room, and offers to try again

#### Scenario: User message kept after a failure

- **WHEN** any error is shown for a message
- **THEN** the user's message is still visible in the conversation

### Requirement: Slash commands are discoverable

The chat screen SHALL show the commands `/push`, `/pull`, `/explore`, and `/compact` with a one-line description of each, so a user can see them without leaving the chat. The list SHALL NOT include `/delete`.

#### Scenario: First visit to the chat

- **WHEN** a user opens the chat with no messages in the conversation
- **THEN** the screen lists `/push`, `/pull`, `/explore`, and `/compact` with a short description of each
- **AND** `/delete` is not listed
