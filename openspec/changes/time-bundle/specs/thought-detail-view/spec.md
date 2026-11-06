## ADDED Requirements

### Requirement: The sheet shows a repeat and reminders

The sheet SHALL show a dated thought's repeat, such as "Every week on Monday", with its last day when it has one, and its reminders, such as "Reminders: 1 hour before, 1 day before", next to the date. A thought with no repeat or no reminders SHALL show none.

#### Scenario: Weekly thought

- **WHEN** a user opens a thought repeating every week on Monday until 31 December 2026, with a reminder 1 day before
- **THEN** the sheet shows "Every week on Monday, until Thu 31 Dec 2026" and "Reminders: 1 day before"

#### Scenario: Neither

- **WHEN** a user opens a dated thought with no repeat and no reminders
- **THEN** the sheet shows the date and no repeat or reminder line

### Requirement: The sheet edits a repeat and reminders

The sheet's Edit SHALL offer the repeat and the reminders as fields with the date, so the user can set, change, or clear them. A refused repeat or reminder SHALL show an error that names the date and SHALL keep the user's input. A change to the repeat or the reminders SHALL NOT change how search finds the thought by its words or meaning. A saved change to the reminders alone SHALL show a new "changed" date, as any saved edit does.

#### Scenario: Add a reminder

- **WHEN** a user opens a dated thought with no reminder, chooses Edit, adds a reminder 1 hour before, and saves
- **THEN** the sheet shows "Reminders: 1 hour before" and a later "changed" date

#### Scenario: Stop repeating

- **WHEN** a user opens a repeating thought, chooses Edit, sets "Does not repeat", and saves
- **THEN** the sheet shows the date with no repeat

### Requirement: A change to one part of the date keeps the rest

A change to the repeat or the reminders alone SHALL keep the date's stored time zone. A change to the date alone SHALL keep the repeat and the reminders. Saving with nothing changed SHALL NOT change the date, its repeat, or its reminders.

#### Scenario: Start moved on a repeating thought

- **WHEN** a user opens a thought repeating every week on Monday with a reminder 1 day before, chooses Edit, moves the start to the next Monday, and saves
- **THEN** the sheet shows the new start, still repeating every week on Monday, with "Reminders: 1 day before"

#### Scenario: Reminder added from another time zone

- **WHEN** a thought dated 19:00 in `Europe/Oslo` is opened in a browser in `Asia/Tokyo`, and the user adds a reminder and saves
- **THEN** the thought keeps 19:00 in `Europe/Oslo`
