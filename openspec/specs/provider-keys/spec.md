# provider-keys Specification

## Purpose
Lets each user bring their own API key for each model provider they use. A key is checked before it is stored, is stored encrypted, and is never shown in full after it is saved.

## Requirements

### Requirement: One key per provider

The system SHALL let a logged-in user save one API key for each provider. The system SHALL list every provider available on the server with whether the user has a key saved for it.

#### Scenario: Listing providers

- **WHEN** a logged-in user asks for their providers
- **THEN** the system returns every available provider with its name and whether a key is saved for it

#### Scenario: Keys for two providers

- **WHEN** a user saves a key for one provider and another key for a second provider
- **THEN** both keys are stored, and each is used only for its own provider

### Requirement: Save a provider API key

The system SHALL check a key against its provider before storing it, and SHALL store a key only when the provider accepts it.

#### Scenario: Valid key

- **WHEN** a user submits a key that the provider accepts
- **THEN** the system stores the key for that user and provider
- **AND** the system shows the key as saved, with only its last 4 characters visible

#### Scenario: Invalid key

- **WHEN** a user submits a key that the provider rejects as unauthorized
- **THEN** the system does not store the key
- **AND** the system responds with error code `provider_key_invalid` and a message that says the provider rejected the key

#### Scenario: Provider whose model list needs no key

- **WHEN** a user submits a wrong key for a provider that serves its model list without authentication
- **THEN** the system checks the key with an authenticated call that the provider rejects for a wrong key
- **AND** the system does not store the key, and responds with error code `provider_key_invalid`

#### Scenario: Provider cannot be reached

- **WHEN** a user submits a key and the provider does not answer, times out, or returns a server error
- **THEN** the system does not store the key
- **AND** the system responds with error code `provider_unreachable` and a message that says the key could not be checked and to try again

#### Scenario: Empty key

- **WHEN** a user submits an empty key or a key made only of whitespace
- **THEN** the system does not call the provider and does not store anything
- **AND** the system responds with a validation error

#### Scenario: A provider that needs no key

- **WHEN** a provider is configured to accept requests without a key, as a local model server may
- **THEN** the user can save the provider with no key, and the check calls the provider's model list without one

### Requirement: Key is stored encrypted and never returned

The system SHALL store every API key encrypted at rest. After a key is saved, no API response and no log entry SHALL contain the full key.

#### Scenario: Database contents

- **WHEN** someone reads the stored key record directly from the database
- **THEN** the record does not contain the key in plain text

#### Scenario: Key status response

- **WHEN** a user requests their key status for a provider
- **THEN** the response contains at most the last 4 characters of the key

#### Scenario: Logging

- **WHEN** the system logs a request that saves, checks, or uses a key
- **THEN** no log entry contains the full key

#### Scenario: Stored record copied to another user

- **WHEN** an encrypted key record is copied onto another user's record in the database
- **THEN** the system fails to decrypt it for that other user and treats that user as having no usable key

### Requirement: View key status

The system SHALL let a logged-in user see, for each provider, whether they have a saved key.

#### Scenario: No key saved

- **WHEN** a user with no saved key for a provider opens the providers section of settings
- **THEN** the system shows that no key is saved for that provider and offers a field to add one

#### Scenario: Key saved

- **WHEN** a user with a saved key for a provider opens the providers section of settings
- **THEN** the system shows the last 4 characters of the key and the date it was saved

### Requirement: Replace a provider API key

The system SHALL let a user replace a saved key. A replacement SHALL go through the same check as a new key.

#### Scenario: Valid replacement

- **WHEN** a user with a saved key submits a different key that the provider accepts
- **THEN** the system stores the new key in place of the old one

#### Scenario: Invalid replacement

- **WHEN** a user with a saved key submits a key that the provider rejects
- **THEN** the system keeps the old key unchanged
- **AND** the system responds with error code `provider_key_invalid`

### Requirement: Delete a provider API key

The system SHALL let a user delete a saved key.

#### Scenario: Delete saved key

- **WHEN** a user deletes their saved key for a provider
- **THEN** the system removes the stored key
- **AND** the key status for that provider shows that no key is saved
- **AND** the keys for other providers are unchanged

### Requirement: Key used only on the server

The system SHALL decrypt a user's key only on the backend, only to make calls to that key's provider for that same user. The key SHALL NOT be sent to the browser.

#### Scenario: Provider call for a user

- **WHEN** the backend calls a provider for a user
- **THEN** it uses that user's key for that provider and no other key

### Requirement: Clear errors when a key is missing or stops working

Any feature that needs a provider SHALL tell the user plainly when they have no usable key for it, or when the provider rejects a saved key, and SHALL point them to the provider settings.

#### Scenario: No key saved

- **WHEN** a user without a saved key for a provider uses a feature that needs it
- **THEN** the system responds with error code `provider_key_missing`, naming the provider
- **AND** the user sees a message with a link to the provider settings

#### Scenario: Saved key rejected by the provider

- **WHEN** a provider rejects a saved key as unauthorized during a call
- **THEN** the system responds with error code `provider_key_rejected`, naming the provider
- **AND** the user sees a message that the saved key no longer works, with a link to the provider settings

### Requirement: Keys belong to one user

A key SHALL be readable and changeable only by the user who saved it. One user's keys SHALL NOT affect another user's providers.

#### Scenario: Two users, two keys for one provider

- **WHEN** two users each save a key for the same provider
- **THEN** each user's calls use only their own key
