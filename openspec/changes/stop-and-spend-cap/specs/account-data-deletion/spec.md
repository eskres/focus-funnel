## MODIFIED Requirements

### Requirement: Deleting in settings

The settings page SHALL offer "Delete content", "Delete usage history", and "Delete account" as separate choices, each with a confirmation step that says what will be deleted, what stays, and that it cannot be undone. The confirmation for "Delete usage history" SHALL also say that a monthly spend cap, if one is set, counts from zero again for this month. After deleting the content or the usage history the user SHALL stay on the page. After deleting the account the user SHALL be logged out, and the app SHALL ask the login provider to end its session without a confirmation step. In demo mode the page SHALL NOT offer any of them, since "End demo" already deletes the session's data.

#### Scenario: Delete the account and log out

- **WHEN** a user chooses "Delete account" and confirms
- **THEN** their account is deleted and they are logged out, with no sign-out confirmation from a provider set up as `docs/login.md` says

#### Scenario: Delete content and stay

- **WHEN** a user chooses "Delete content" and confirms
- **THEN** their content is deleted and they stay logged in on the settings page

#### Scenario: Cancel

- **WHEN** a user chooses any of the three and cancels
- **THEN** nothing is deleted

#### Scenario: Demo mode

- **WHEN** a demo visitor opens settings
- **THEN** none of the three is offered

#### Scenario: Usage history and the spend cap

- **WHEN** a user chooses "Delete usage history"
- **THEN** the confirmation says that a monthly spend cap, if one is set, counts from zero again for this month
