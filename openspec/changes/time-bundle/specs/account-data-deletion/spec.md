## ADDED Requirements

### Requirement: Reminders, notifications, the calendar feed, and push subscriptions are deleted with the user's data

Deleting a user's content SHALL also delete their reminders and their notifications, and SHALL keep their calendar feed and their push subscriptions, which are settings. Deleting the account SHALL also delete all four. After the content is deleted, the calendar feed SHALL still answer, with no events. Another user's data SHALL be unchanged.

#### Scenario: Content deleted

- **WHEN** a user with a dated thought with a reminder, notifications, a calendar feed, and a push subscription deletes their content
- **THEN** their reminders and notifications are gone, no reminder comes due later, and their calendar feed answers with no events

#### Scenario: Account deleted

- **WHEN** the same user deletes their account
- **THEN** their reminders, notifications, push subscriptions, and calendar feed are gone, and the feed address answers as an unknown address

### Requirement: The delete confirmations name reminders, notifications, the feed, and push

The confirmation before deleting content SHALL name reminders and notifications among what is deleted, and the calendar feed and browser notifications among what stays. The confirmation before deleting the account SHALL name all four among what is deleted.

#### Scenario: What the confirmations say

- **WHEN** a user opens the "Delete content" confirmation, and then the "Delete account" confirmation
- **THEN** the first says reminders and notifications are deleted and the calendar feed and browser notifications stay
- **AND** the second says reminders, notifications, the calendar feed, and browser notifications are deleted
