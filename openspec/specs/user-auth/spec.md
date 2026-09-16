# user-auth Specification

## Purpose

Makes sure only logged-in users can use Focus Funnel. Each user gets exactly one account record, and each user can reach only their own data.

## Requirements

### Requirement: Login through Auth0
The system SHALL require users to log in through Auth0 before they can use any page except the public landing page. The system SHALL let a logged-in user log out.

#### Scenario: Logged-out user opens the app
- **WHEN** a user who is not logged in opens a page that needs a login
- **THEN** the system redirects the user to the Auth0 login page

#### Scenario: Successful login
- **WHEN** a user completes login on Auth0
- **THEN** the system returns the user to the app as a logged-in user

#### Scenario: Logout
- **WHEN** a logged-in user selects "Log out"
- **THEN** the system ends the user's session
- **AND** the next page that needs a login redirects to the Auth0 login page

### Requirement: Backend API requires a valid access token
The backend API SHALL reject every request, except the health check, that does not carry a valid Auth0 access token. A valid token has a correct signature from the configured Auth0 tenant, the configured issuer, the configured API audience, and an expiry time that has not passed.

#### Scenario: Missing token
- **WHEN** a request reaches a protected backend endpoint with no access token
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

#### Scenario: Expired token
- **WHEN** a request carries an access token whose expiry time has passed
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

#### Scenario: Wrong audience or issuer
- **WHEN** a request carries an access token issued for a different audience or by a different issuer
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

#### Scenario: Invalid signature
- **WHEN** a request carries an access token whose signature does not match a signing key from the configured Auth0 tenant
- **THEN** the backend responds with HTTP 401 and error code `unauthenticated`

#### Scenario: Valid token
- **WHEN** a request carries a valid access token
- **THEN** the backend handles the request as the user named by the token's subject

### Requirement: User record created on first authenticated request
The system SHALL create exactly one user record per Auth0 subject. It SHALL create the record on the first authenticated backend request from that subject.

#### Scenario: First request from a new user
- **WHEN** the backend gets a valid token for a subject that has no user record
- **THEN** the system creates one user record for that subject
- **AND** the system handles the request as that user

#### Scenario: Later requests from the same user
- **WHEN** the backend gets a valid token for a subject that already has a user record
- **THEN** the system uses the existing record and does not create another

#### Scenario: Two first requests at the same time
- **WHEN** two requests with valid tokens for the same new subject arrive at the same time
- **THEN** exactly one user record exists for that subject after both requests finish

### Requirement: Browser never holds the access token
The browser SHALL send API calls only to the frontend's own server. The frontend server SHALL attach the access token and forward each call to the backend. The access token SHALL NOT be sent to, or be readable by, JavaScript that runs in the browser.

#### Scenario: Browser makes an API call
- **WHEN** a page in the browser requests data from the API
- **THEN** the request goes to the frontend's own origin
- **AND** the frontend server forwards it to the backend with the user's access token

#### Scenario: Token not exposed in browser responses
- **WHEN** any frontend response is sent to the browser
- **THEN** the response contains no Auth0 access token in its body or in any cookie that JavaScript can read

#### Scenario: Streamed responses pass through
- **WHEN** the backend answers a forwarded call with a streamed response
- **THEN** the frontend server passes each streamed part to the browser as it arrives, without waiting for the full response

#### Scenario: Forwarded call without a session
- **WHEN** the browser calls a frontend API route and has no logged-in session
- **THEN** the frontend server responds with HTTP 401 and error code `unauthenticated`, and does not call the backend

### Requirement: Users reach only their own data
The backend SHALL scope every user-owned record to the user who owns it. A request for a record that belongs to another user SHALL behave the same as a request for a record that does not exist.

#### Scenario: Request for another user's record
- **WHEN** user A requests a record that belongs to user B
- **THEN** the backend responds with HTTP 404
- **AND** the response does not reveal that the record exists

### Requirement: Unauthenticated health check
The backend SHALL provide a health endpoint that needs no access token. It SHALL report whether the backend can reach its database.

#### Scenario: Healthy backend
- **WHEN** a client calls the health endpoint and the database is reachable
- **THEN** the backend responds with HTTP 200 and a status of `ok`

#### Scenario: Database unreachable
- **WHEN** a client calls the health endpoint and the database is not reachable
- **THEN** the backend responds with HTTP 503 and a status that names the database as unavailable
