## MODIFIED Requirements

### Requirement: Deleting in settings

The settings page SHALL offer "Delete content", "Delete usage history", and "Delete account" as separate choices, each with a confirmation step that says what will be deleted, what stays, and that it cannot be undone. The confirmation for "Delete usage history" SHALL also say that a monthly spend cap, if one is set, counts from zero again for this month. After deleting the content or the usage history the user SHALL stay on the page. After deleting the account the user SHALL be logged out, and the app SHALL ask the login provider to end its session without a confirmation step. In demo mode the page SHALL NOT offer any of them, since "End demo" already deletes the session's data.

#### Scenario: Delete the account and log out

- **WHEN** a user chooses "Delete account" and confirms
- **THEN** their account is deleted and they are logged out, with no sign-out confirmation from a provider set up as `docs/login.md` says

#### Scenario: Delete content and stay

- **WHEN** a user chooses "Delete content" and confirms
- **THEN** their content is deleted and they stay logged in on the settings page

#### Scenario: Cancel

- **WHEN** a user chooses any of the three and cancels
- **THEN** nothing is deleted

#### Scenario: Demo mode

- **WHEN** a demo visitor opens settings
- **THEN** none of the three is offered

#### Scenario: Usage history and the spend cap

- **WHEN** a user chooses "Delete usage history"
- **THEN** the confirmation says that a monthly spend cap, if one is set, counts from zero again for this month

### Requirement: Delete my content

A logged-in user SHALL be able to delete their content with one request. It SHALL delete, in one transaction, their thoughts and search indexes and their conversations, messages, and proposals. It SHALL keep their account, provider keys, model loadout and chat settings, the categories they added, and usage records, and the user SHALL stay logged in. Another user's data SHALL be unchanged. Before it deletes, it SHALL stop the user's running answers and wait for them to end, so their answers and usage are stored first (conversation-agent "Deleting stops a running turn first"). When an answer has not ended within the wait, or a message is still being opened, the request SHALL respond with HTTP 409 and error code `conversation_busy`, with a message that says an answer is still running and to try again in a moment, and SHALL delete nothing.

#### Scenario: Content deleted, the rest kept

- **WHEN** a user with thoughts, a key, conversations, added categories, and usage records deletes their content
- **THEN** their thoughts, search entries, conversations, messages, and proposals are gone
- **AND** their key, model settings, added categories, and usage records remain
- **AND** another user's data is unchanged

#### Scenario: Content deleted while an answer runs

- **WHEN** a user deletes their content while an answer is running in one of their conversations
- **THEN** the answer is stopped and its usage is recorded before the content is deleted
- **AND** that usage record remains after the delete

#### Scenario: An answer does not end in time

- **WHEN** a user deletes their content and one of their answers has not ended within the wait, or a message of theirs is still being opened
- **THEN** the system responds with HTTP 409 and error code `conversation_busy`, saying that an answer is still running and to try again in a moment
- **AND** nothing is deleted

### Requirement: Delete my account

A logged-in user SHALL be able to delete their account with one request. It SHALL delete, in one transaction, their thoughts and search indexes, provider keys, model loadout and chat settings, the categories they added, conversations, messages, proposals, and usage records, and their user record. Another user's data SHALL be unchanged. Before it deletes, it SHALL stop the user's running answers and wait for them to end (conversation-agent "Deleting stops a running turn first"). When an answer has not ended within the wait, or a message is still being opened, the request SHALL respond with HTTP 409 and error code `conversation_busy`, with a message that says an answer is still running and to try again in a moment, and SHALL delete nothing.

#### Scenario: Everything deleted

- **WHEN** a user with thoughts, a key, conversations, added categories, and usage records deletes their account
- **THEN** none of those remain
- **AND** another user's data is unchanged

#### Scenario: Next login

- **WHEN** the user logs in again after deleting their account
- **THEN** they start as a new user with no data

#### Scenario: Account deleted while an answer runs

- **WHEN** a user deletes their account while an answer is running in one of their conversations
- **THEN** the answer is stopped and no further model call starts
- **AND** none of the user's data remains, including that answer's usage record

#### Scenario: Account delete while an answer does not end in time

- **WHEN** a user deletes their account and one of their answers has not ended within the wait, or a message of theirs is still being opened
- **THEN** the system responds with HTTP 409 and error code `conversation_busy`, saying that an answer is still running and to try again in a moment
- **AND** nothing is deleted and the user stays logged in
