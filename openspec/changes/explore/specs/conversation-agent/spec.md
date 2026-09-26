## ADDED Requirements

### Requirement: One proposal per answer

An answer SHALL show at most one proposal. When the model calls the proposal tool again in an answer that already shows a proposal, the system SHALL store no proposal for that call and SHALL tell the model that one proposal holds every thought as its parts.

#### Scenario: Second call in one answer

- **WHEN** the model calls the proposal tool twice in one answer
- **THEN** the chat shows one proposal card
- **AND** one proposal is stored

### Requirement: The offer before an action may propose nothing

Before archive or `/compact`, when no proposal with an unsaved part is held, the system SHALL ask the model for a proposal only if the user sent a message after the latest proposal with a saved part. The model SHALL be told which thoughts this conversation already filed, SHALL be free to propose nothing, and SHALL be steered to leave out greetings, thanks, and small talk. When the model proposes nothing, the action SHALL go ahead with no offer.

#### Scenario: Nothing said since the last saved card

- **WHEN** a user confirms every card of a proposal and then sends `/compact` without another message
- **THEN** no proposal is offered and the model is not asked for one

#### Scenario: Only thanks since

- **WHEN** a user confirms a card, sends `thanks`, and then sends `/compact`
- **THEN** no proposal is offered

#### Scenario: New facts on the same topic

- **WHEN** a user files `Buy a bike lock`, asks about lock colours, strength, and prices, and then sends `/compact`
- **THEN** the offer does not repeat `Buy a bike lock`
- **AND** it may propose the new facts
