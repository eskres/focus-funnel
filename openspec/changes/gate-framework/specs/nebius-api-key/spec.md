## ADDED Requirements

### Requirement: Model list for the user's own key

The system SHALL let a logged-in user list the models their own saved Nebius key can use. The list SHALL come from Nebius, using that user's key and no other user's key. A user with no usable key SHALL be told so, with a pointer to the API key settings, rather than shown an empty list.

#### Scenario: User with a working key

- **WHEN** a user with a saved, working key lists models
- **THEN** the system returns the models that key can use

#### Scenario: User with no saved key

- **WHEN** a user with no saved key lists models
- **THEN** the system responds with error code `nebius_key_missing`
- **AND** the user sees a message with a link to the API key settings

#### Scenario: Saved key no longer accepted

- **WHEN** Nebius rejects the user's saved key while listing models
- **THEN** the system responds with error code `nebius_key_rejected`
- **AND** the user sees a message with a link to the API key settings

#### Scenario: Nebius cannot be reached

- **WHEN** Nebius times out, cannot be connected to, or returns a server error while listing models
- **THEN** the system responds with error code `nebius_unreachable`
- **AND** the system does not present a partial or stale list as complete

#### Scenario: One user's key never lists for another

- **WHEN** two users with different keys each list models
- **THEN** each list is built with that user's own key
