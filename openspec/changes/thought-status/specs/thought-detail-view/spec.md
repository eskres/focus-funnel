## MODIFIED Requirements

### Requirement: A thought opens in a side sheet

Opening a thought SHALL show a side sheet over the chat with its title, summary, tags, category, raw text, and the dates it was filed and last changed. The sheet SHALL also show whether the thought is done, and the date it was marked done when it is. The chat SHALL stay in place behind it. A thought with no raw text SHALL show no raw text section. A raw text that is the same as the summary SHALL NOT be shown twice. The raw text SHALL be read-only: the sheet SHALL offer no way to change it.

#### Scenario: Open from a saved card

- **WHEN** a user clicks the link on a saved proposal card
- **THEN** a side sheet shows the thought's title, summary, tags, category, raw text, and dates
- **AND** the conversation is still visible behind it

#### Scenario: Close

- **WHEN** the user closes the sheet
- **THEN** the chat is as it was, with the same scroll position and any unsent text in the input

#### Scenario: No changes from the sheet

- **WHEN** a user views a thought in the sheet and does not choose Edit, Delete, or Done
- **THEN** the thought is unchanged when the sheet closes

#### Scenario: Raw text stays as written

- **WHEN** a user opens a thought that has raw text and chooses Edit
- **THEN** the title, summary, tags, and category become editable
- **AND** the raw text shows as before, with no field to change it

## ADDED Requirements

### Requirement: The sheet marks a thought done

The sheet SHALL show whether the thought is done, with a Done toggle the user can turn on or off without choosing Edit. Turning it SHALL save at once. A done thought SHALL show the date it was marked done. A change that fails SHALL put the toggle back and SHALL show the reason. The toggle SHALL NOT change the thought's "changed" date or any of its other fields.

#### Scenario: Mark done

- **WHEN** a user opens the open task `Call the plumber` and turns on Done
- **THEN** the sheet shows the task as done, with today's date
- **AND** its "changed" date is as before

#### Scenario: Reopen

- **WHEN** a user opens a done task and turns off Done
- **THEN** the sheet shows the task as open, with no done date

#### Scenario: Change fails

- **WHEN** a user turns on Done and the change is refused
- **THEN** the toggle is off again, and the sheet shows the reason

#### Scenario: Still found

- **WHEN** a user marks a task done in the sheet and then searches for its title
- **THEN** the search finds the task
