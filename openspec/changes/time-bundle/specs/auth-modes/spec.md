## MODIFIED Requirements

### Requirement: Email allow-list

In `oidc` and `firebase` modes the operator SHALL be able to set an allow-list of email addresses and whole email domains. When a list is set, the system SHALL let a user in only when the provider says their email address is verified and the address is on the list. When no list is set, any user the provider logs in may use the app. The backend SHALL enforce the list on every request. A calendar feed request, which carries no login, SHALL be the one exception to how a refusal is answered: when the feed's owner is not let in by the list, it SHALL answer HTTP 404 with error code `not_found` and the body every unknown feed address gets, not HTTP 403 `not_allowed`. Browser notifications SHALL NOT be pushed to a user the list does not let in.

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
- **AND** any API call responds with HTTP 403 and error code `not_allowed`, apart from a calendar feed request

#### Scenario: Unverified address

- **WHEN** an allow-list is set and the provider does not say the user's email address is verified
- **THEN** the user is treated as not on the list

#### Scenario: List changed while a user is logged in

- **WHEN** the operator removes a logged-in user's address from the list and restarts the server
- **THEN** the user's next API call responds with HTTP 403 and error code `not_allowed`, apart from a calendar feed request

#### Scenario: Calendar feed and pushes of a user no longer allowed

- **WHEN** the operator removes from the list the address of a user who made a calendar feed address and turned on browser notifications, and restarts the server
- **THEN** a request for that feed address responds with HTTP 404 and error code `not_found`, with the same body as an unknown address, not HTTP 403 `not_allowed`
- **AND** none of that user's reminders is pushed to their browsers
