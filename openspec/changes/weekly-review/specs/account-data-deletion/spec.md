## ADDED Requirements

### Requirement: Weekly review settings stay with the content and go with the account

Deleting a user's content SHALL keep their weekly review and resurfacing settings, and SHALL delete their review conversations with the other conversations. Deleting the account SHALL delete the settings. The "Delete content" confirmation SHALL name the weekly review settings among what stays.

#### Scenario: Content deleted

- **WHEN** a user with the weekly review on and a review conversation deletes their content
- **THEN** the review conversation is gone, and Settings still shows the weekly review on at the same time

#### Scenario: Account deleted

- **WHEN** the same user deletes their account
- **THEN** their weekly review settings are gone, and no review is made for them again

#### Scenario: What the confirmation says

- **WHEN** a user opens the "Delete content" confirmation
- **THEN** it says the weekly review settings stay

### Requirement: A review made during a delete goes with it

A review being made while the user's content or account is deleted SHALL be deleted with it, or made after it with nothing of the deleted content. It SHALL NOT make the delete answer that an answer is still running.

#### Scenario: Review made during the delete

- **WHEN** a user's review is being made at the moment they delete their content
- **THEN** the delete succeeds, and the review conversation made at that moment is gone with the rest

#### Scenario: Review made during the account delete

- **WHEN** a user's review is being made at the moment they delete their account
- **THEN** the delete succeeds, and nothing of the user is left
