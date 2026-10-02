## ADDED Requirements

### Requirement: The sheet shows and edits a thought's date

The sheet SHALL show a dated thought's date apart from the dates it was filed and last changed: the start, and the end when there is one, each with its time when it has one. A thought with no date SHALL show no date. The sheet's Edit SHALL also offer the date as fields, filled with the current date or empty, so the user can set, change, or clear it. A refused date SHALL show an error that names the date and SHALL keep the user's input. A change to the date only SHALL NOT change how search finds the thought by its words or meaning.

#### Scenario: Dated thought

- **WHEN** a user opens a thought dated Friday 2 October 2026 at 19:00
- **THEN** the sheet shows that date and time, apart from the filed and changed dates

#### Scenario: Trip over several days

- **WHEN** a user opens a thought dated 3 to 6 November
- **THEN** the sheet shows the start 3 November and the end 6 November

#### Scenario: No date

- **WHEN** a user opens a thought with no date
- **THEN** the sheet shows no date

#### Scenario: Set a date

- **WHEN** a user opens a thought with no date, chooses Edit, sets the start to Monday, and saves
- **THEN** the sheet shows the start Monday, with no time and no end

#### Scenario: Clear the date

- **WHEN** a user opens a dated thought, chooses Edit, clears the date, and saves
- **THEN** the sheet shows no date

#### Scenario: End before start

- **WHEN** a user sets the end before the start and saves
- **THEN** the sheet shows an error that names the date, keeps the user's input, and the thought is unchanged
