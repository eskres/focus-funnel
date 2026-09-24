# Spec Delta

## Purpose

Lets a user delete their content, their usage history, or their whole account, including their thoughts and search index, each in one step.

## ADDED Requirements

### Requirement: Delete my content

A logged-in user SHALL be able to delete their content with one request. It SHALL delete, in one transaction, their thoughts and search indexes and their conversations and messages. It SHALL keep their account, provider keys, model loadout and chat settings, and usage records, and the user SHALL stay logged in. Another user's data SHALL be unchanged.

#### Scenario: Content deleted, the rest kept

- **WHEN** a user with thoughts, a key, conversations, and usage records deletes their content
- **THEN** their thoughts, search entries, conversations, and messages are gone
- **AND** their key, model settings, and usage records remain
- **AND** another user's data is unchanged

### Requirement: Delete my usage history

A logged-in user SHALL be able to delete their usage records with one request, and nothing else.

#### Scenario: Only usage deleted

- **WHEN** a user with thoughts, conversations, and usage records deletes their usage history
- **THEN** their usage records are gone and everything else remains

### Requirement: Delete my account

A logged-in user SHALL be able to delete their account with one request. It SHALL delete, in one transaction, their thoughts and search indexes, provider keys, model loadout and chat settings, conversations, messages, and usage records, and their user record. Another user's data SHALL be unchanged.

#### Scenario: Everything deleted

- **WHEN** a user with thoughts, a key, conversations, and usage records deletes their account
- **THEN** none of those remain
- **AND** another user's data is unchanged

#### Scenario: Next login

- **WHEN** the user logs in again after deleting their account
- **THEN** they start as a new user with no data

### Requirement: Deleting in settings

The settings page SHALL offer "Delete content", "Delete usage history", and "Delete account" as separate choices, each with a confirmation step that says what will be deleted, what stays, and that it cannot be undone. After deleting the content or the usage history the user SHALL stay on the page. After deleting the account the user SHALL be logged out, and the app SHALL ask the login provider to end its session without a confirmation step. In demo mode the page SHALL NOT offer any of them, since "End demo" already deletes the session's data.

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

### Requirement: Every deletion path removes thoughts

Every path that deletes a user, including demo session end and demo expiry, SHALL also delete that user's thoughts and search indexes.

#### Scenario: Demo expiry

- **WHEN** a demo user with stored thoughts expires and is cleaned up
- **THEN** their thoughts and search entries are deleted too
