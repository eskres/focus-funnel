## MODIFIED Requirements

### Requirement: Backend API requires a valid access token

The backend API SHALL reject every request, except the health check, the start of a demo session, and a calendar feed request, that does not carry a valid credential for the configured auth mode:

- In `oidc` mode, an ID token with a correct signature from a key the provider publishes, the configured issuer, the configured client id as its audience, and an expiry time that has not passed.
- In `firebase` mode, a Firebase ID token with a correct signature from Google's published keys, the configured project as issuer and audience, and an expiry time that has not passed.
- In `demo` mode, a demo session value whose hash matches a live anonymous user.

The backend SHALL accept only asymmetric signature algorithms for tokens, and SHALL NOT accept a credential meant for another mode. A calendar feed request SHALL carry no credential for the auth mode; its feed token SHALL be its only credential, SHALL give access to that one feed and nothing else, and SHALL NOT be accepted by any other route.

#### Scenario: Missing token

- **WHEN** a request reaches a protected backend endpoint with no credential
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

#### Scenario: Expired token

- **WHEN** a request carries a token whose expiry time has passed
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

#### Scenario: Wrong audience or issuer

- **WHEN** a request carries a token issued for a different audience or by a different issuer
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

#### Scenario: Invalid signature

- **WHEN** a request carries a token whose signature does not match a key the configured provider publishes
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

#### Scenario: Symmetric or unsigned token

- **WHEN** a request carries a token signed with a shared-secret algorithm or not signed at all
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

#### Scenario: Credential for another mode

- **WHEN** the backend runs in `oidc` mode and a request carries a demo session value
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

#### Scenario: Valid token

- **WHEN** a request carries a valid credential
- **THEN** the backend handles the request as the user named by the credential's issuer and subject

#### Scenario: Provider keys cannot be fetched

- **WHEN** a token names a signing key the backend has not seen and the provider's keys cannot be fetched
- **THEN** the backend responds with HTTP 503 and error code `service_unavailable`, not `unauthenticated`

#### Scenario: Calendar feed

- **WHEN** a request with no credential asks for a user's calendar feed address
- **THEN** the backend answers with that user's feed

#### Scenario: Feed token used elsewhere

- **WHEN** a request to `/api/thoughts/upcoming` carries a feed token as its bearer credential
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`
