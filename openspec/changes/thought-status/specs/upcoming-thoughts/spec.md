## ADDED Requirements

### Requirement: Done thoughts are left off the Upcoming page

The Upcoming page and the request behind it SHALL NOT list a thought that is done. A thought marked done in the sheet SHALL no longer be listed once the sheet closes. A thought set back to open SHALL be listed again when its date is today or later.

#### Scenario: Done task left out

- **WHEN** on Wednesday 30 September a user has an open task dated 2 October and a done task dated 1 October
- **THEN** the page lists the open task and not the done one

#### Scenario: Marked done from the page

- **WHEN** a user opens an item on the Upcoming page, turns on Done, and closes the sheet
- **THEN** the item is no longer listed

#### Scenario: Reopened

- **WHEN** a user reopens a done task dated tomorrow
- **THEN** the Upcoming page lists it again
