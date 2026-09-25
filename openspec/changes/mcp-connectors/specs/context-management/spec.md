# Spec Delta

## MODIFIED Requirements

### Requirement: The chat shows how full the context is

The chat SHALL show how much of the conversation model's context window is in use. The figure SHALL include the definitions of the tools offered to the model, built-in and from connectors. The figure SHALL be updated after each answer from the token count the provider reports for the call, and SHALL use the context length reported for the conversation's current model. It SHALL be recalculated when the user switches model or turns a connector on or off, and the meter SHALL show how many of the tokens are tool definitions.

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

#### Scenario: Turning a connector on

- **WHEN** a user turns on a connector with 5 switched-on tools
- **THEN** the meter adds an estimate of those tools' definitions
- **AND** the figure is marked as an estimate until the next answer
- **AND** the meter shows the tokens used by tool definitions

### Requirement: A message that cannot fit is refused

When a message, together with the definitions of the tools offered in the conversation, would take the conversation past the model's context length, the system SHALL NOT call the model and SHALL NOT drop earlier turns silently. It SHALL respond with error code `context_full` and advise `/compact`, a model with a larger context, a new conversation, or, when connectors are on, turning some off.

#### Scenario: Conversation is full

- **WHEN** a user sends a message that would exceed the context length
- **THEN** the system responds with `context_full`
- **AND** the user's message is kept in the conversation and no model is called
