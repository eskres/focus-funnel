## MODIFIED Requirements

### Requirement: Save a provider API key

The system SHALL check a key against its provider before keeping it, and SHALL keep a key only when the provider accepts it. In `oidc` and `firebase` modes the system SHALL store the key on the server. In `demo` mode the system SHALL NOT store it on the server, and the browser SHALL hold it as the `demo-mode` capability describes.

#### Scenario: Valid key

- **WHEN** a user submits a key that the provider accepts
- **THEN** the system keeps the key for that user and provider
- **AND** the system shows the key as saved, with only its last 4 characters visible

#### Scenario: Valid key in demo mode

- **WHEN** a visitor in `demo` mode submits a key that the provider accepts
- **THEN** no key record is written to the database
- **AND** the system shows the key as held, with its last 4 characters and the time it will be forgotten

#### Scenario: Invalid key

- **WHEN** a user submits a key that the provider rejects as unauthorized
- **THEN** the system does not keep the key
- **AND** the system responds with error code `provider_key_invalid` and a message that says the provider rejected the key

#### Scenario: Provider whose model list needs no key

- **WHEN** a user submits a wrong key for a provider that serves its model list without authentication
- **THEN** the system checks the key with an authenticated call that the provider rejects for a wrong key
- **AND** the system does not keep the key, and responds with error code `provider_key_invalid`

#### Scenario: Provider cannot be reached

- **WHEN** a user submits a key and the provider does not answer, times out, or returns a server error
- **THEN** the system does not keep the key
- **AND** the system responds with error code `provider_unreachable` and a message that says the key could not be checked and to try again

#### Scenario: Empty key

- **WHEN** a user submits an empty key or a key made only of whitespace
- **THEN** the system does not call the provider and does not keep anything
- **AND** the system responds with a validation error

#### Scenario: A provider that needs no key

- **WHEN** a provider is configured to accept requests without a key, as a local model server may
- **THEN** the user can save the provider with no key, and the check calls the provider's model list without one

### Requirement: Key used only on the server

The system SHALL decrypt a user's key only on the server, only to make calls to that key's provider for that same user. In `oidc` and `firebase` modes the key SHALL NOT be sent to the browser. In `demo` mode the browser SHALL hold the key only in an encrypted cookie that JavaScript cannot read, and the backend SHALL use a key sent with a request for that request only and SHALL NOT store it.

#### Scenario: Provider call for a user

- **WHEN** the backend calls a provider for a user
- **THEN** it uses that user's key for that provider and no other key

#### Scenario: Provider call in demo mode

- **WHEN** the backend calls a provider for a visitor in `demo` mode
- **THEN** it uses the key sent with that request
- **AND** after the request the key is not in the database, in a cache, or in a log
