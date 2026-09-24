## Purpose

Lets strangers try a public demo instance without an account. Each visitor gets a private, temporary identity. Their data expires, their API keys are never stored on the server, and the instance refuses settings that would expose the server or other visitors.

## ADDED Requirements

### Requirement: Anonymous session per visitor

In `demo` mode the system SHALL give each new visitor an anonymous user and a session cookie. The session value SHALL be random with at least 128 bits of entropy, and the cookie SHALL be HttpOnly, Secure, and SameSite=Lax. The server SHALL store only a hash of the session value. There SHALL be no login page.

#### Scenario: First visit

- **WHEN** a visitor with no demo session opens the app
- **THEN** the system creates an anonymous user and sets the session cookie
- **AND** the visitor sees the app without logging in

#### Scenario: Return within the session

- **WHEN** the visitor comes back with a valid session cookie
- **THEN** the system uses the same anonymous user and their data is still there

#### Scenario: Session value in the database

- **WHEN** someone reads the stored user records directly from the database
- **THEN** no record holds a session value that would work as a cookie

#### Scenario: Cookie not readable by page scripts

- **WHEN** a script on the page reads `document.cookie`
- **THEN** the demo session value is not in it

### Requirement: Visitors are isolated

In `demo` mode every read and write SHALL be scoped to the visitor's anonymous user, as for any logged-in user. A record that belongs to another visitor SHALL behave as if it does not exist.

#### Scenario: Another visitor's conversation

- **WHEN** visitor A opens the URL of a conversation that belongs to visitor B
- **THEN** the system responds with HTTP 404 and shows nothing of the conversation

### Requirement: Demo data expires

In `demo` mode each anonymous user SHALL have an expiry time, set when the session starts from a configured number of hours. After it passes, the system SHALL refuse the session and SHALL delete the user and everything they own. The visitor SHALL see when their session expires.

#### Scenario: Session past its expiry

- **WHEN** a visitor sends a request after their session's expiry time
- **THEN** the request responds with HTTP 401 and error code `demo_session_expired`
- **AND** the visitor sees that their demo session ended and its data was deleted, with a button to start a new one

#### Scenario: Cleanup

- **WHEN** an anonymous user's expiry time has passed
- **THEN** within 15 minutes the system deletes the user and all their conversations, messages, usage records, and settings

#### Scenario: Visitor ends the session

- **WHEN** a visitor selects "End demo" and confirms
- **THEN** the system deletes the anonymous user and all their data at once and clears the session cookie

#### Scenario: Expiry is shown

- **WHEN** a visitor opens the app
- **THEN** the app shows the time at which their session and data will be deleted

### Requirement: Demo keys are held by the browser

In `demo` mode the system SHALL NOT store any provider key on the server. After a key passes the provider check, the frontend server SHALL put it in an encrypted, HttpOnly cookie. The frontend server SHALL send the key to the backend with each request that needs it, and the backend SHALL use it for that request only. A held key SHALL expire after a configured idle time (30 minutes by default) and a configured maximum age (4 hours by default), whichever comes first.

#### Scenario: Saving a key in demo mode

- **WHEN** a visitor saves a key that the provider accepts
- **THEN** no key record is written to the database
- **AND** the provider shows as having a key, with its last 4 characters and the time the key will be forgotten

#### Scenario: Idle expiry

- **WHEN** a visitor makes no request for longer than the idle time
- **THEN** the key is forgotten and the next call that needs it responds with error code `provider_key_missing`

#### Scenario: Maximum age

- **WHEN** a visitor keeps using a key for longer than the maximum age
- **THEN** the key is forgotten even though the visitor was active

#### Scenario: Forget key

- **WHEN** a visitor selects "Forget key" for a provider
- **THEN** that key is removed from the browser at once and other held keys are unchanged

#### Scenario: Key not readable by page scripts

- **WHEN** a script on the page reads `document.cookie`, local storage, or session storage
- **THEN** no provider key is in them

#### Scenario: Key not logged

- **WHEN** the frontend server or the backend logs a request that carries a held key
- **THEN** no log entry holds the full key

### Requirement: Demo notice before first use

In `demo` mode the system SHALL show a notice before the visitor's first message. The notice SHALL say what is stored, when it will be deleted, that the operator can technically read stored conversations, and that keys are held in the browser for a limited time. It SHALL include the chosen provider's own data-handling notice. The visitor SHALL accept it before sending a message, and SHALL be able to read it again later.

#### Scenario: First message

- **WHEN** a visitor who has not accepted the notice tries to send a message
- **THEN** the notice is shown and the message is not sent until the visitor accepts it

#### Scenario: Accepted once per session

- **WHEN** a visitor who accepted the notice reloads the page
- **THEN** the notice is not shown again before the next message

### Requirement: Demo mode refuses unsafe settings

In `demo` mode the system SHALL refuse to start when `oidc` or `firebase` settings are present, or when the custom provider is explicitly turned on. The custom provider SHALL be off in demo mode. Every response SHALL be marked `Cache-Control: no-store`.

#### Scenario: Login settings present

- **WHEN** the server starts in `demo` mode with an OIDC issuer or a Firebase project id set
- **THEN** it fails to start and names the setting to remove

#### Scenario: Custom provider turned on

- **WHEN** the server starts in `demo` mode with the custom provider explicitly turned on
- **THEN** it fails to start and names the setting

#### Scenario: Custom provider requested

- **WHEN** a visitor submits a custom base URL
- **THEN** nothing is stored and the system responds with HTTP 422 and error code `validation_error`

#### Scenario: Responses are not cached

- **WHEN** the system sends any page or API response in demo mode
- **THEN** it carries `Cache-Control: no-store`

### Requirement: Demo mode limits use

In `demo` mode the system SHALL limit requests per client address to a configured rate, and SHALL limit the number of new sessions per client address and the total number of live sessions. A refused request SHALL say when to try again.

#### Scenario: Too many requests

- **WHEN** one client address sends more requests than the configured rate
- **THEN** the extra requests respond with HTTP 429 and error code `rate_limited`, with a `Retry-After` header

#### Scenario: Too many new sessions

- **WHEN** one client address starts more new sessions in an hour than allowed
- **THEN** no further session is created and the visitor sees that they should try again later

#### Scenario: Instance full

- **WHEN** a new visitor arrives and the number of live sessions has reached its limit
- **THEN** no session is created
- **AND** the visitor sees that the demo is full and to try again later, with error code `demo_full`
