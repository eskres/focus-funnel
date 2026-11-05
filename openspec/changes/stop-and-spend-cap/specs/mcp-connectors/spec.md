## MODIFIED Requirements

### Requirement: A tool acts only after the user approves

A tool SHALL count as read-only only when its read or act badge says it reads. The badge SHALL start from the server's read-only hint: a tool the server marks read-only starts as reads, and every other tool starts as acts. The user SHALL be able to change a tool marked reads to acts, and SHALL NOT be able to change a tool the server does not mark read-only to reads. When the model calls a tool marked acts, the system SHALL NOT call the server. It SHALL store the call as an action awaiting approval, show it in the chat as a card with the connector, the tool, and its arguments in readable form, and tell the model that the action has not run. Approving the card SHALL call the server once and show the outcome on the card; declining SHALL call nothing. The outcome, or the decline, SHALL be passed to the model in the next turn. An action SHALL be approvable only until the next turn starts in its conversation; after that, its card SHALL show that it expired. A message refused before its first model call is sent (for example a full context, a missing model or key, or the monthly spend cap) SHALL NOT expire the conversation's actions; a message whose first model call the provider refuses or fails SHALL expire them like any sent message. The user SHALL be able to set "always allow" on a tool marked acts, and that tool SHALL then run without a card, except as the untrusted-data requirement below says.

#### Scenario: Model creates an event

- **WHEN** the model calls `calendar__create_event` in a conversation with the calendar connector on
- **THEN** the chat shows an action card with the event's details
- **AND** no call is made to the server
- **AND** the model's reply does not say that the event was created

#### Scenario: User approves

- **WHEN** the user approves the card
- **THEN** the server's tool runs once and the card shows its outcome
- **AND** the next turn's context tells the model that the action ran and what it returned

#### Scenario: User declines

- **WHEN** the user declines the card
- **THEN** nothing is sent to the server
- **AND** the next turn's context tells the model that the user declined

#### Scenario: Approve after moving on

- **WHEN** the user sends another message that is answered and then tries to approve the earlier card
- **THEN** the system responds with HTTP 409 and error code `action_expired`, and the card shows that it expired

#### Scenario: Approve after a refused message

- **WHEN** the user sends another message that is refused before its first model call is sent, such as when the context is full or the monthly spend cap is reached, and then approves the earlier card
- **THEN** the card was still pending after the refused message
- **AND** the server's tool runs once and the card shows its outcome

#### Scenario: Approve after the provider refused the message

- **WHEN** the user sends another message whose first model call the provider refuses, such as with a rejected key, and then tries to approve the earlier card
- **THEN** the chat shows the provider's error for the message
- **AND** the system responds to the approval with HTTP 409 and error code `action_expired`, and the card shows that it expired

#### Scenario: Approved twice

- **WHEN** the approval is sent twice, from two tabs
- **THEN** the server's tool runs once and both answers carry the same outcome

#### Scenario: Read-only tool

- **WHEN** the model calls a tool marked reads
- **THEN** it runs at once and its result goes back to the model

#### Scenario: Read-only hint missing

- **WHEN** the server gives no read-only hint for a tool
- **THEN** the tool is marked acts and cannot be changed to reads
