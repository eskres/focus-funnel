## MODIFIED Requirements

### Requirement: Backend API requires a valid access token

The backend API SHALL reject every request, except the health check, the start of a demo session, and a calendar feed request, that does not carry a valid credential for the configured auth mode:

- In `oidc` mode, an ID token with a correct signature from a key the provider publishes, the configured issuer, the configured client id as its audience, and an expiry time that has not passed.
- In `firebase` mode, a Firebase ID token with a correct signature from Google's published keys, the configured project as issuer and audience, and an expiry time that has not passed.
- In `demo` mode, a demo session value whose hash matches a live anonymous user.

The backend SHALL accept only asymmetric signature algorithms for tokens, and SHALL NOT accept a credential meant for another mode. A calendar feed request SHALL carry no credential for the auth mode; its feed token SHALL be its only credential, SHALL give access to that one feed and nothing else, and SHALL NOT be accepted by any other route. When an email allow-list is set, a feed request SHALL be answered as for an unknown feed unless the verified email address stored with the feed when it was made is on the list.

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

#### Scenario: Calendar feed of a user no longer allowed

- **WHEN** the operator removes a user's address from the allow-list and restarts the server, and a request with no credential asks for that user's calendar feed address
- **THEN** the backend responds with HTTP 404 and error code `not_found`, as for an unknown address

#### Scenario: Feed token used elsewhere

- **WHEN** a request to `/api/thoughts/upcoming` carries a feed token as its bearer credential
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

### Requirement: Browser never holds the access token

The browser SHALL send API calls only to the frontend's own server. The frontend server SHALL attach the user's credential and forward each call to the backend, except a calendar feed request. No login token, refresh token, or demo session value SHALL be readable by JavaScript that runs in the browser. The one exception is the Firebase sign-in step, where the browser hands its tokens to the frontend server at once and keeps no copy. A calendar feed request SHALL be forwarded to the backend without a session, and the frontend server SHALL send no cookie, login token, demo session value, or other credential with it; its feed token SHALL be its only credential. Every other frontend API route called with no session SHALL answer 401 without calling the backend.

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

- **WHEN** the browser calls a frontend API route other than a calendar feed address and has no session
- **THEN** the frontend server responds with HTTP 401 and error code `unauthenticated`, and does not call the backend

#### Scenario: From a calendar app

- **WHEN** a calendar app with no session fetches a user's calendar feed address from the frontend server
- **THEN** the frontend server forwards the request to the backend with no cookie and no credential, and does not answer 401
- **AND** the calendar app gets that user's feed
