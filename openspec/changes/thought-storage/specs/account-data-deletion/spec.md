# Spec Delta

## Purpose

Lets a user delete everything the app stores about them, including their thoughts and search index, in one step.

## ADDED Requirements

### Requirement: Delete my data

A logged-in user SHALL be able to delete all of their stored data with one request. It SHALL delete, in one transaction, their thoughts and search indexes, provider keys, model loadout and chat settings, conversations, messages, and usage records, and their user record. Another user's data SHALL be unchanged.

#### Scenario: Everything deleted

- **WHEN** a user with thoughts, a key, conversations, and usage records deletes their data
- **THEN** none of those remain
- **AND** another user's data is unchanged

#### Scenario: Next login

- **WHEN** the user logs in again after deleting their data
- **THEN** they start as a new user with no data

### Requirement: Delete my data in settings

The settings page SHALL offer "Delete my data" with a confirmation step that says what will be deleted and that it cannot be undone. After the deletion the user SHALL be logged out. In demo mode the page SHALL NOT offer it, since "End demo" already deletes the session's data.

#### Scenario: Confirm and log out

- **WHEN** a user chooses "Delete my data" and confirms
- **THEN** their data is deleted and they are logged out

#### Scenario: Cancel

- **WHEN** a user chooses "Delete my data" and cancels
- **THEN** nothing is deleted

#### Scenario: Demo mode

- **WHEN** a demo visitor opens settings
- **THEN** "Delete my data" is not offered

### Requirement: Every deletion path removes thoughts

Every path that deletes a user, including demo session end and demo expiry, SHALL also delete that user's thoughts and search indexes.

#### Scenario: Demo expiry

- **WHEN** a demo user with stored thoughts expires and is cleaned up
- **THEN** their thoughts and search entries are deleted too
