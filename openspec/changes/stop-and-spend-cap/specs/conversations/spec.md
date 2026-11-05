## MODIFIED Requirements

### Requirement: A conversation can be deleted with /delete

A message that is only `/delete` SHALL ask the user to confirm and then delete the current conversation and all of its messages for good. The sidebar SHALL offer the same deletion with the same confirmation. Nothing in the product, including the model, SHALL suggest deleting a conversation, and `/delete` SHALL NOT appear in the command list. Deleting SHALL NOT delete usage records. A running answer in the conversation SHALL be stopped before the delete (conversation-agent "Deleting stops a running turn first"). When that answer has not ended within the wait, or a message in the conversation is still being opened, the system SHALL respond with HTTP 409 and error code `conversation_busy` and delete nothing, and the confirmation SHALL show a message that says an answer in this conversation is still running and to try deleting again in a moment.

#### Scenario: Delete confirmed

- **WHEN** a user sends `/delete` and confirms
- **THEN** the conversation and its messages are deleted
- **AND** the chat shows a new, empty conversation

#### Scenario: Delete cancelled

- **WHEN** a user sends `/delete` and cancels
- **THEN** the conversation is unchanged

#### Scenario: Deleting is never suggested

- **WHEN** a discussion ends, a proposal is held, or a conversation is archived
- **THEN** the chat does not suggest deleting the conversation

#### Scenario: Delete with extra text

- **WHEN** a user sends `/delete` followed by other text
- **THEN** nothing is deleted
- **AND** the system responds with HTTP 422 and error code `validation_error`, saying the command takes no message

#### Scenario: Delete while the answer does not end in time

- **WHEN** a user confirms deleting a conversation from the sidebar, and its answer has not ended within the wait after the delete stopped it
- **THEN** the system responds with HTTP 409 and error code `conversation_busy`
- **AND** the confirmation says that an answer in this conversation is still running and to try deleting again in a moment
- **AND** the conversation and its messages are unchanged
