## MODIFIED Requirements

### Requirement: Conversations run independently

Each conversation SHALL use its own stored model and effort. A turn running in one conversation SHALL NOT block a turn in another conversation of the same user, whether in the same browser tab or another. Only one turn at a time SHALL run in a single conversation.

A turn SHALL run to completion on the server whether or not the browser that sent the message is still connected. Closing the tab, switching conversations, or losing the connection SHALL NOT stop the model call, the tools, or the storing of the answer. What the turn produces SHALL be stored the same way whether or not anyone is watching: a complete answer as complete, a failed answer as failed, and a cut answer as cut. While a turn runs, its owner SHALL be able to follow it again from the start of the answer, from any tab; another user SHALL get a not-found response. The conversation SHALL be free for the next message as soon as the turn ends, however it ends. When the server stops or restarts during a turn, the turn's answer SHALL be stored as failed, with the text received so far where the server could store it, and the conversation SHALL be free once the server is back. A user SHALL NOT be able to stop a running turn.

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

#### Scenario: Leaving mid-answer

- **WHEN** a user switches to another conversation while an answer is streaming
- **THEN** the model call continues
- **AND** the finished answer is stored, with its tool results, proposal, and sources

#### Scenario: Tab closed mid-answer

- **WHEN** a user closes the tab while an answer is streaming
- **THEN** the finished answer is stored
- **AND** the usage of every model call in the turn is recorded

#### Scenario: Free once the turn ends

- **WHEN** a turn ends after its browser disconnected
- **THEN** the next message in that conversation is answered
- **AND** the system does not respond with `conversation_busy`

#### Scenario: Failure while nobody watches

- **WHEN** the provider fails a turn after its browser disconnected
- **THEN** the answer is stored as failed with the provider's error code, as when the browser stays connected
- **AND** the conversation is free for the next message

#### Scenario: Following a running turn again

- **WHEN** the owner asks to follow a conversation's running turn
- **THEN** the system sends every event of the answer so far, then the rest as it arrives

#### Scenario: Following another user's turn

- **WHEN** a user asks to follow a running turn in another user's conversation
- **THEN** the system responds with HTTP 404

#### Scenario: Nothing running

- **WHEN** the owner asks to follow a conversation that has no running turn
- **THEN** the system says that no turn is running, without an error
- **AND** the stored messages hold the last answer

#### Scenario: Server restart mid-turn

- **WHEN** the server restarts while a turn is running
- **THEN** after the restart the answer shows as failed and can be sent again
- **AND** the conversation is free for the next message without waiting

#### Scenario: Demo key during a turn

- **WHEN** a demo visitor sends a message and then closes the tab
- **THEN** the turn finishes with the key sent with that message
- **AND** the key is not stored on the server and is not sent to the browser
