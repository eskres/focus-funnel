## ADDED Requirements

### Requirement: A weekly review shows in its conversation

A weekly review message SHALL show in its conversation as a review from the app, headed "Weekly review" with its days, named as in the conversation's title whatever the browser's time zone, with its groups and lines as written, and SHALL NOT show as an answer from the model. The input SHALL be ready for a reply, and the review SHALL show the same after a reload.

#### Scenario: Open a review

- **WHEN** a user opens a review conversation from its notification
- **THEN** the chat shows "Weekly review" with the week's days and the grouped list, and the input is ready
- **AND** no answer is running and no error is shown

#### Scenario: After a reply and a reload

- **WHEN** the user replies in a review conversation, the answer arrives, and the user reloads the page
- **THEN** the review shows first, as before, followed by the reply and the answer

#### Scenario: Opened in another time zone

- **WHEN** a user whose setting is in `Europe/Oslo` opens the review `Weekly review, 1–8 Nov` in a browser set to `Pacific/Auckland`
- **THEN** the review is headed with `1–8 Nov`, as its title
