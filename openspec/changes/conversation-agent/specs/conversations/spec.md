## Purpose

Keeps a user's chats so they can leave one and come back to it. A sidebar lists the conversations, and the user can resume, rename, archive, restore, and delete them.

## ADDED Requirements

### Requirement: Conversations are stored per user

The system SHALL store each conversation with its messages, in order, for the user who started it. A conversation SHALL have a title, a time of last activity, an archived state, and the model and reasoning effort it uses. The first message a user sends with no conversation open SHALL start a new conversation. A conversation SHALL be readable and changeable only by its owner: another user's conversation SHALL respond as if it does not exist.

#### Scenario: First message starts a conversation

- **WHEN** a user with no conversation open sends a message
- **THEN** the system stores a new conversation holding that message and the answer
- **AND** the conversation appears in the sidebar

#### Scenario: Later messages join the same conversation

- **WHEN** a user sends a second message in an open conversation
- **THEN** the message and its answer are stored in the same conversation, after the earlier ones

#### Scenario: Another user's conversation

- **WHEN** a user asks for a conversation that belongs to someone else
- **THEN** the system responds with HTTP 404 and error code `not_found`

#### Scenario: A failed answer keeps the user's message

- **WHEN** a message cannot be answered and the chat shows an error
- **THEN** the user's message is still stored in the conversation

### Requirement: The sidebar lists conversations

The chat screen SHALL show a sidebar on the left that lists the user's conversations that are not archived, with the most recently active first. Each entry SHALL show the conversation's title. A title SHALL start as the beginning of the first message and SHALL be editable by the user. The sidebar SHALL offer a way to start a new conversation. Opening the chat screen SHALL start a new, empty conversation.

#### Scenario: Newest activity first

- **WHEN** a user sends a message in an older conversation
- **THEN** that conversation moves to the top of the sidebar

#### Scenario: Title from the first message

- **WHEN** a conversation's first message is `buy oat milk tomorrow`
- **THEN** the conversation's title starts with `buy oat milk tomorrow`

#### Scenario: Rename

- **WHEN** a user renames a conversation
- **THEN** the sidebar shows the new title and the change is kept after a reload

#### Scenario: Opening the chat

- **WHEN** a user opens the chat screen
- **THEN** the conversation area is empty and shows the command list
- **AND** the sidebar lists the user's earlier conversations

#### Scenario: No conversations yet

- **WHEN** a user with no conversations opens the chat screen
- **THEN** the sidebar says there are no conversations yet

### Requirement: A conversation can be resumed

Selecting a conversation in the sidebar SHALL show all of its stored messages in order and let the user carry on. The conversation SHALL keep using the model and reasoning effort stored with it. Messages that `/compact` replaced for the model SHALL still be shown.

#### Scenario: Resume an earlier conversation

- **WHEN** a user selects an earlier conversation and sends a message
- **THEN** the earlier messages are shown
- **AND** the answer takes the earlier messages into account

#### Scenario: Reload during a conversation

- **WHEN** a user reloads the page and selects the same conversation
- **THEN** every stored message is shown again

### Requirement: A conversation can be archived and restored

The user SHALL be able to archive a conversation. An archived conversation SHALL leave the main list and appear in an "Archived" section of the sidebar. The user SHALL be able to restore it to the main list, and sending a message in an archived conversation SHALL restore it. Archiving SHALL NOT delete any message.

#### Scenario: Archive

- **WHEN** a user archives a conversation
- **THEN** it disappears from the main list and appears under "Archived"
- **AND** its messages are unchanged

#### Scenario: Restore

- **WHEN** a user restores an archived conversation
- **THEN** it appears in the main list again

#### Scenario: Carry on in an archived conversation

- **WHEN** a user opens an archived conversation and sends a message
- **THEN** the conversation returns to the main list

### Requirement: A conversation can be deleted with /delete

A message that is only `/delete` SHALL ask the user to confirm and then delete the current conversation and all of its messages for good. The sidebar SHALL offer the same deletion with the same confirmation. Nothing in the product, including the model, SHALL suggest deleting a conversation, and `/delete` SHALL NOT appear in the command list. Deleting SHALL NOT delete usage records.

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

### Requirement: Conversations are deleted with the account

When a user's data is deleted, the system SHALL delete their conversations, their messages, and their usage records.

#### Scenario: Account data deleted

- **WHEN** a user's data is deleted
- **THEN** no conversation, message, or usage record of that user remains
