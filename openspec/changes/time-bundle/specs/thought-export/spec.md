## MODIFIED Requirements

### Requirement: A user can export all their thoughts

A logged-in user SHALL be able to download every thought they own in one file, as JSON or as Markdown. Each thought SHALL carry its id, title, summary, raw text, tags, category, status and the time of its last status change, date, the date's repeat and reminders when it has them, the times it was filed and last changed, its origin, and its additions. A thought with no origin, date, repeat, reminders, raw text, or additions SHALL still be exported. Exporting SHALL change nothing.

#### Scenario: Everything a thought has

- **WHEN** a user has a done `task` titled `Call the plumber`, dated `2026-11-09` in `Europe/Oslo`, saved from the conversation `Weekend plans` and added to once from the conversation `Plumber chat`, and exports as JSON
- **THEN** the file holds that thought with its title, summary, raw text, tags, the category `task`, the status `done` with the time it was marked done, the date `2026-11-09` in `Europe/Oslo`, and its filed and changed times
- **AND** its origin names `Weekend plans`, the proposal, and when it was proposed
- **AND** it lists one addition that names `Plumber chat`

#### Scenario: The same thought in Markdown

- **WHEN** the same user exports as Markdown
- **THEN** the thought's section shows the same title, status, category, tags, date, times, origin, summary, raw text, and addition

#### Scenario: A plain thought

- **WHEN** a thought was stored with no origin, no date, no raw text, and no additions, and the user exports
- **THEN** the file holds that thought with its title, summary, and the status `open`, and with no origin, date, raw text, or additions

#### Scenario: No thoughts

- **WHEN** a user with no thoughts exports as JSON or as Markdown
- **THEN** the file is complete and says there are no thoughts

#### Scenario: Nothing changes

- **WHEN** a user exports
- **THEN** every thought's changed time is as before, and no usage record is added

#### Scenario: A repeating thought with reminders in JSON

- **WHEN** a user has `Take the bins out`, dated `2026-11-09` in `Europe/Oslo`, repeating every week on Monday with no last day, with reminders 60 and 1,440 minutes before, and exports as JSON
- **THEN** that thought's date in the file has the repeat every week on Monday with no last day, and the reminders 60 and 1,440

#### Scenario: A repeating thought with reminders in Markdown

- **WHEN** the same user exports as Markdown
- **THEN** that thought's date line shows `2026-11-09 (Europe/Oslo)` and that it repeats every week on Monday
- **AND** its section has a line giving the reminders 60 and 1,440 minutes before

#### Scenario: No repeat and no reminders

- **WHEN** a thought dated `2026-11-09` has no repeat and no reminders, and the user exports as JSON and as Markdown
- **THEN** the JSON gives it no repeat and no reminders, and its Markdown section has no repeat text and no reminders line

### Requirement: The Markdown export

The Markdown file SHALL be one file. It SHALL start with a heading and the export time, then give each thought a section, oldest first, headed by its title, with its status and the time of its last status change when it has one, category, tags, date with its repeat, its reminders when it has any, filed and changed times, origin, and id, then its summary, its raw text in a code block, and its additions. The raw text SHALL be kept exactly as written. The file SHALL end with a line that gives the number of thoughts.

#### Scenario: A thought's section

- **WHEN** a user with the thought `Call the plumber` exports as Markdown
- **THEN** the file has a heading `Call the plumber`, followed by its details, its summary, and its raw text in a code block
- **AND** the file's last line gives the number of thoughts

#### Scenario: A reopened thought

- **WHEN** a thought was marked done and then opened again, and the user exports as Markdown
- **THEN** its section shows the status `open` with the time it was reopened
- **AND** a thought whose status never changed shows the status `open` with no time

#### Scenario: Raw text with a code fence

- **WHEN** a thought's raw text holds a line of three backticks and the user exports as Markdown
- **THEN** the code block holds the whole raw text unchanged, and the next thought's heading is outside it

#### Scenario: Raw text line endings

- **WHEN** a thought's raw text uses `\r\n` line breaks, holds a blank line inside, and holds a lone `\r` inside, and the user exports as Markdown
- **THEN** the code block gives back that raw text exactly, line breaks included

#### Scenario: Repeat and reminders in a section

- **WHEN** a thought dated `2026-11-09` in `Europe/Oslo`, repeating every week on Monday, with reminders 60 and 1,440 minutes before, is exported as Markdown
- **THEN** its section's date line shows the date and that it repeats every week on Monday, and the next line gives the reminders 60 and 1,440 minutes before, before its filed and changed times
