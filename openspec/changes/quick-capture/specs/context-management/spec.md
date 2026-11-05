## MODIFIED Requirements

### Requirement: A message that cannot fit is refused

When a message, together with the definitions of the tools offered in the conversation, would take the conversation past the model's context length, the system SHALL NOT call the model and SHALL NOT drop earlier turns silently. It SHALL respond with error code `context_full` and advise `/compact`, a model with a larger context, a new conversation, or, when connectors are on, turning some off. A quick capture whose text does not fit the default model's context SHALL be refused with the same code, SHALL store nothing, and its message SHALL say to shorten the text or set a default model with a larger context.

#### Scenario: Conversation is full

- **WHEN** a user sends a message that would exceed the context length
- **THEN** the system responds with `context_full`
- **AND** the user's message is kept in the conversation and no model is called

#### Scenario: Capture too long

- **WHEN** a user makes a quick capture whose text does not fit the default model's context
- **THEN** the system responds with `context_full`, and the message says to shorten the text or set a default model with a larger context
- **AND** no model is called, and no conversation, message, or proposal is stored
