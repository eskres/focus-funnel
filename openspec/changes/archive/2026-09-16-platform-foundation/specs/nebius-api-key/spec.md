## Purpose

Lets each user bring their own Nebius API key. The key is checked before it is stored, it is stored encrypted, and it is never shown in full after it is saved.

## ADDED Requirements

### Requirement: Save a Nebius API key
The system SHALL let a logged-in user save one Nebius API key. Before storing it, the system SHALL check the key against the Nebius API. The system SHALL store a key only when Nebius accepts it.

#### Scenario: Valid key
- **WHEN** a user submits a key that Nebius accepts
- **THEN** the system stores the key for that user
- **AND** the system shows the key as saved, with only its last 4 characters visible

#### Scenario: Invalid key
- **WHEN** a user submits a key that Nebius rejects as unauthorized
- **THEN** the system does not store the key
- **AND** the system responds with error code `nebius_key_invalid` and a message that says Nebius rejected the key

#### Scenario: Nebius cannot be reached
- **WHEN** a user submits a key and the Nebius API does not answer, times out, or returns a server error
- **THEN** the system does not store the key
- **AND** the system responds with error code `nebius_unreachable` and a message that says the key could not be checked and to try again

#### Scenario: Empty key
- **WHEN** a user submits an empty key or a key made only of whitespace
- **THEN** the system does not call Nebius and does not store anything
- **AND** the system responds with a validation error

### Requirement: Key is stored encrypted and never returned
The system SHALL store every Nebius API key encrypted at rest. After a key is saved, no API response and no log entry SHALL contain the full key.

#### Scenario: Database contents
- **WHEN** someone reads the stored key record directly from the database
- **THEN** the record does not contain the key in plain text

#### Scenario: Key status response
- **WHEN** a user requests their key status
- **THEN** the response contains at most the last 4 characters of the key

#### Scenario: Logging
- **WHEN** the system logs a request that saves, checks, or uses a key
- **THEN** no log entry contains the full key

#### Scenario: Stored record copied to another user
- **WHEN** an encrypted key record is copied onto another user's record in the database
- **THEN** the system fails to decrypt it for that other user and treats that user as having no usable key

### Requirement: View key status
The system SHALL let a logged-in user see whether they have a saved key.

#### Scenario: No key saved
- **WHEN** a user with no saved key opens the API key section of settings
- **THEN** the system shows that no key is saved and offers a field to add one

#### Scenario: Key saved
- **WHEN** a user with a saved key opens the API key section of settings
- **THEN** the system shows the last 4 characters of the key and the date it was saved

### Requirement: Replace a Nebius API key
The system SHALL let a user replace their saved key. A replacement SHALL go through the same check as a new key.

#### Scenario: Valid replacement
- **WHEN** a user with a saved key submits a different key that Nebius accepts
- **THEN** the system stores the new key in place of the old one

#### Scenario: Invalid replacement
- **WHEN** a user with a saved key submits a key that Nebius rejects
- **THEN** the system keeps the old key unchanged
- **AND** the system responds with error code `nebius_key_invalid`

### Requirement: Delete a Nebius API key
The system SHALL let a user delete their saved key.

#### Scenario: Delete saved key
- **WHEN** a user deletes their saved key
- **THEN** the system removes the stored key
- **AND** the key status shows that no key is saved

### Requirement: Key used only on the server
The system SHALL decrypt a user's key only on the backend, only to make calls to Nebius for that same user. The key SHALL NOT be sent to the browser.

#### Scenario: Nebius call for a user
- **WHEN** the backend calls Nebius for a user
- **THEN** it uses that user's key and no other user's key

### Requirement: Clear errors when a key is missing or stops working
Any feature that needs Nebius SHALL tell the user plainly when they have no usable key, or when Nebius rejects a saved key, and SHALL point them to the API key settings.

#### Scenario: No key saved
- **WHEN** a user without a saved key uses a feature that needs Nebius
- **THEN** the system responds with error code `nebius_key_missing`
- **AND** the user sees a message with a link to the API key settings

#### Scenario: Saved key rejected by Nebius
- **WHEN** Nebius rejects a saved key as unauthorized during a call
- **THEN** the system responds with error code `nebius_key_rejected`
- **AND** the user sees a message that the saved key no longer works, with a link to the API key settings
