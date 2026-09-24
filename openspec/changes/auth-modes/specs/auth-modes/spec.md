## Purpose

Lets an operator choose how people log in: through any OpenID Connect provider, through a Firebase project, or not at all on a throwaway demo instance. Whatever the mode, login tokens stay on the server, and the rest of the app sees only the current user.

## ADDED Requirements

### Requirement: One auth mode per instance

The system SHALL read one auth mode from server configuration, with the values `oidc`, `firebase`, and `demo`. The system SHALL refuse to start when the mode is missing or unknown, or when a setting that the chosen mode needs is missing. The failure message SHALL name the missing or wrong setting. The frontend server and the backend SHALL use the same mode.

#### Scenario: No mode set

- **WHEN** the server starts with no auth mode set
- **THEN** it fails to start
- **AND** the failure message names the auth mode setting and its three values

#### Scenario: Unknown mode

- **WHEN** the server starts with an auth mode that is not `oidc`, `firebase`, or `demo`
- **THEN** it fails to start and names the value it refused

#### Scenario: A needed setting is missing

- **WHEN** the server starts in `oidc` mode with no issuer set
- **THEN** it fails to start
- **AND** the failure message names the issuer setting

#### Scenario: The mode is chosen at run time

- **WHEN** an operator changes the auth mode and restarts the containers without rebuilding them
- **THEN** the app uses the new mode

### Requirement: Login through an OpenID Connect provider

In `oidc` mode the system SHALL log users in through the configured OpenID Connect provider with the authorization code flow and PKCE. The frontend server SHALL run the whole flow. The system SHALL work with any provider that publishes a standard discovery document, and SHALL NOT depend on features of one provider.

#### Scenario: Logged-out user opens the app

- **WHEN** a user who is not logged in opens a page that needs a login
- **THEN** the system sends the user to the provider's login page
- **AND** after a successful login the user returns to the page they asked for

#### Scenario: Login is cancelled or fails

- **WHEN** the provider returns an error, or the returned state does not match the login that was started
- **THEN** the user is not logged in
- **AND** the user sees a page that says the login did not complete, with a link to try again

#### Scenario: Logout

- **WHEN** a logged-in user selects "Log out"
- **THEN** the system ends the user's session
- **AND** the system also ends the session at the provider when the provider offers a logout endpoint

#### Scenario: Another provider through the same settings

- **WHEN** an operator sets the issuer, client id, and client secret of Pocket ID, Authentik, Keycloak, or Auth0
- **THEN** login works without a code change

### Requirement: Login through Firebase

In `firebase` mode the system SHALL log users in through the configured Firebase project. The browser SHALL run the Firebase sign-in step, hand its tokens to the frontend server at once, and keep no copy. From then on the frontend server SHALL hold the session.

#### Scenario: Successful sign-in

- **WHEN** a user completes Firebase sign-in on the login page
- **THEN** the frontend server checks the token, starts a session, and sends the user to the page they asked for
- **AND** no Firebase token remains in the browser's storage or in memory that page scripts can read

#### Scenario: Sign-in with a token from another project

- **WHEN** the browser hands over a token issued for a different Firebase project
- **THEN** no session starts and the user sees that the login did not complete

#### Scenario: Logout

- **WHEN** a logged-in user selects "Log out"
- **THEN** the system ends the user's session

### Requirement: The session lasts beyond one token

In `oidc` and `firebase` modes the frontend server SHALL renew a user's token before it expires, while the session is valid, so that a user is not sent back to login every hour. When renewal fails, the system SHALL treat the user as logged out.

#### Scenario: Token expires during a visit

- **WHEN** a logged-in user's token has expired and the session can still be renewed
- **THEN** the next call is sent with a renewed token and succeeds

#### Scenario: Renewal is refused

- **WHEN** the provider refuses to renew the token
- **THEN** the call responds with HTTP 401 and error code `unauthenticated`
- **AND** the next page that needs a login sends the user to log in

### Requirement: Email allow-list

In `oidc` and `firebase` modes the operator SHALL be able to set an allow-list of email addresses and whole email domains. When a list is set, the system SHALL let a user in only when the provider says their email address is verified and the address is on the list. When no list is set, any user the provider logs in may use the app. The backend SHALL enforce the list on every request.

#### Scenario: Address on the list

- **WHEN** a user whose verified email address is on the allow-list logs in
- **THEN** the user can use the app

#### Scenario: Domain on the list

- **WHEN** the allow-list holds `@example.org` and a user with the verified address `ana@example.org` logs in
- **THEN** the user can use the app

#### Scenario: Address not on the list

- **WHEN** a user whose email address is not on the allow-list logs in
- **THEN** no user record is created for them
- **AND** the user sees a page that says this instance does not accept their account
- **AND** any API call responds with HTTP 403 and error code `not_allowed`

#### Scenario: Unverified address

- **WHEN** an allow-list is set and the provider does not say the user's email address is verified
- **THEN** the user is treated as not on the list

#### Scenario: List changed while a user is logged in

- **WHEN** the operator removes a logged-in user's address from the list and restarts the server
- **THEN** the user's next API call responds with HTTP 403 and error code `not_allowed`

### Requirement: No login-free mode keeps data

The system SHALL NOT offer a mode that has no login and keeps data beyond the demo expiry.

#### Scenario: Looking for a no-login mode

- **WHEN** an operator reads the list of auth modes
- **THEN** the only mode without login is `demo`, and its data expires
