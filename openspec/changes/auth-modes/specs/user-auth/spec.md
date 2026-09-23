## REMOVED Requirements

### Requirement: Login through Auth0

**Reason**: Login is no longer tied to Auth0. The operator chooses an auth mode.
**Migration**: See "Login through an OpenID Connect provider" and "Login through Firebase" in the `auth-modes` capability, and "Anonymous session per visitor" in the `demo-mode` capability. Auth0 still works as an `oidc` provider.

## MODIFIED Requirements

### Requirement: Backend API requires a valid access token

The backend API SHALL reject every request, except the health check and the start of a demo session, that does not carry a valid credential for the configured auth mode:

- In `oidc` mode, an ID token with a correct signature from a key the provider publishes, the configured issuer, the configured client id as its audience, and an expiry time that has not passed.
- In `firebase` mode, a Firebase ID token with a correct signature from Google's published keys, the configured project as issuer and audience, and an expiry time that has not passed.
- In `demo` mode, a demo session value whose hash matches a live anonymous user.

The backend SHALL accept only asymmetric signature algorithms for tokens, and SHALL NOT accept a credential meant for another mode.

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

### Requirement: User record created on first authenticated request

The system SHALL create exactly one user record per pair of issuer and subject. It SHALL create the record on the first authenticated backend request from that pair, and only when the email allow-list, if set, lets the user in. The same subject from two different issuers SHALL be two users.

#### Scenario: First request from a new user

- **WHEN** the backend gets a valid token for an issuer and subject that have no user record
- **THEN** the system creates one user record for that issuer and subject
- **AND** the system handles the request as that user

#### Scenario: Later requests from the same user

- **WHEN** the backend gets a valid token for an issuer and subject that already have a user record
- **THEN** the system uses the existing record and does not create another

#### Scenario: Two first requests at the same time

- **WHEN** two requests with valid tokens for the same new issuer and subject arrive at the same time
- **THEN** exactly one user record exists for that pair after both requests finish

#### Scenario: Same subject from another issuer

- **WHEN** two providers issue tokens with the same subject
- **THEN** the system keeps two separate user records, and neither user can reach the other's data

#### Scenario: User refused by the allow-list

- **WHEN** the backend gets a valid token for a user who is not on the email allow-list
- **THEN** no user record is created

### Requirement: Browser never holds the access token

The browser SHALL send API calls only to the frontend's own server. The frontend server SHALL attach the user's credential and forward each call to the backend. No login token, refresh token, or demo session value SHALL be readable by JavaScript that runs in the browser. The one exception is the Firebase sign-in step, where the browser hands its tokens to the frontend server at once and keeps no copy.

#### Scenario: Browser makes an API call

- **WHEN** a page in the browser requests data from the API
- **THEN** the request goes to the frontend's own origin
- **AND** the frontend server forwards it to the backend with the user's credential

#### Scenario: Token not exposed in browser responses

- **WHEN** any frontend response is sent to the browser
- **THEN** the response contains no login token and no demo session value in its body or in any cookie that JavaScript can read

#### Scenario: Streamed responses pass through

- **WHEN** the backend answers a forwarded call with a streamed response
- **THEN** the frontend server passes each streamed part to the browser as it arrives, without waiting for the full response

#### Scenario: Forwarded call without a session

- **WHEN** the browser calls a frontend API route and has no session
- **THEN** the frontend server responds with HTTP 401 and error code `unauthenticated`, and does not call the backend
