## MODIFIED Requirements

### Requirement: Delete my content

A logged-in user SHALL be able to delete their content with one request. It SHALL delete, in one transaction, their thoughts and search indexes and their conversations, messages, and proposals. It SHALL keep their account, provider keys, model loadout and chat settings, the categories they added, and usage records, and the user SHALL stay logged in. Another user's data SHALL be unchanged.

#### Scenario: Content deleted, the rest kept

- **WHEN** a user with thoughts, a key, conversations, added categories, and usage records deletes their content
- **THEN** their thoughts, search entries, conversations, messages, and proposals are gone
- **AND** their key, model settings, added categories, and usage records remain
- **AND** another user's data is unchanged

### Requirement: Delete my account

A logged-in user SHALL be able to delete their account with one request. It SHALL delete, in one transaction, their thoughts and search indexes, provider keys, model loadout and chat settings, the categories they added, conversations, messages, proposals, and usage records, and their user record. Another user's data SHALL be unchanged.

#### Scenario: Everything deleted

- **WHEN** a user with thoughts, a key, conversations, added categories, and usage records deletes their account
- **THEN** none of those remain
- **AND** another user's data is unchanged

#### Scenario: Next login

- **WHEN** the user logs in again after deleting their account
- **THEN** they start as a new user with no data
