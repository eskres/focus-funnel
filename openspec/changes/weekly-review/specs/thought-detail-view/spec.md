## MODIFIED Requirements

### Requirement: A thought opens in a side sheet

Opening a thought SHALL show a side sheet over the chat with its title, summary, tags, category, raw text, and the dates it was filed and last changed. The sheet SHALL also show whether the thought is done or archived, and the date it was marked done or archived when it is. The chat SHALL stay in place behind it. A thought with no raw text SHALL show no raw text section. A raw text that is the same as the summary SHALL NOT be shown twice. The raw text SHALL be read-only: the sheet SHALL offer no way to change it. Opening a thought SHALL record when it was last opened in the side sheet, which counts as touching it for resurfacing, and SHALL change none of its shown fields or its "changed" date.

#### Scenario: Open from a saved card

- **WHEN** a user clicks the link on a saved proposal card
- **THEN** a side sheet shows the thought's title, summary, tags, category, raw text, and dates
- **AND** the conversation is still visible behind it

#### Scenario: Close

- **WHEN** the user closes the sheet
- **THEN** the chat is as it was, with the same scroll position and any unsent text in the input

#### Scenario: No changes from the sheet

- **WHEN** a user views a thought in the sheet and does not choose Edit, Delete, Done, Archive, or Restore, or undo an addition
- **THEN** its fields and "changed" date are unchanged when the sheet closes

#### Scenario: Raw text stays as written

- **WHEN** a user opens a thought that has raw text and chooses Edit
- **THEN** the title, summary, tags, and category become editable
- **AND** the raw text shows as before, with no field to change it

### Requirement: The sheet marks a thought done

The sheet SHALL show whether the thought is done, with a Done toggle the user can turn on or off without choosing Edit. The toggle SHALL NOT be shown for an archived thought. Turning it SHALL save at once. A done thought SHALL show the date it was marked done. A change that fails SHALL put the toggle back and SHALL show the reason. The toggle SHALL NOT change the thought's "changed" date or any of its other fields.

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

#### Scenario: Archived thought

- **WHEN** a user opens an archived idea
- **THEN** the sheet shows no Done toggle

## ADDED Requirements

### Requirement: The sheet archives and restores a thought

The sheet SHALL offer Archive for an open thought and Restore for an archived one, without choosing Edit. It SHALL NOT offer Archive for a done thought. Each SHALL save at once. Archive SHALL set the status `archived`, and the sheet SHALL show the thought as archived with the date. Restore SHALL set the status `open`. A change that fails SHALL show the reason and leave the thought as it was shown.

#### Scenario: Archive

- **WHEN** a user opens the open idea `Podcast about maps` and chooses Archive
- **THEN** the sheet shows it as archived, with today's date, and offers Restore
- **AND** its "changed" date is as before

#### Scenario: Restore

- **WHEN** a user opens an archived idea and chooses Restore
- **THEN** the sheet shows it as open, with the Done toggle off

#### Scenario: Done thought

- **WHEN** a user opens the done task `Buy oat milk`
- **THEN** the sheet offers no Archive, and shows the Done toggle on

#### Scenario: Archive fails

- **WHEN** a user chooses Archive and the change is refused
- **THEN** the sheet still shows the thought as open, and shows the reason
