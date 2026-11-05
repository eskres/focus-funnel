## MODIFIED Requirements

### Requirement: The Upcoming page lists dated thoughts from today on

The app SHALL have an Upcoming page, reached from a link in the sidebar. It SHALL list the user's open dated thoughts whose end day, or start day when there is no end, is today or later, where today is the browser's local date. It SHALL NOT list a thought that is done. A thought marked done in the sheet SHALL no longer be listed once the sheet closes, and a thought set back to open SHALL be listed again when its date is today or later. A thought that started before today and ends today or later SHALL be listed. A thought dated before today SHALL NOT be listed. A thought with no date SHALL NOT be listed. The list SHALL be in date order: by start day, a thought with no time before one with a time, then by start time, then by when it was filed. It SHALL show at most 200 thoughts and SHALL say when more exist.

#### Scenario: Mixed dates

- **WHEN** on Wednesday 30 September a user has a thought dated 28 September, a trip dated 29 September to 2 October, a dinner dated 2 October at 19:00, a plumber call dated 2 October with no time, and an idea with no date
- **THEN** the page lists the trip, then the plumber call, then the dinner
- **AND** it does not list the thought dated 28 September or the idea

#### Scenario: Nothing coming up

- **WHEN** a user has no thought dated today or later
- **THEN** the page says that nothing is coming up

#### Scenario: More than the page shows

- **WHEN** a user has 250 dated thoughts from today on
- **THEN** the page lists the first 200 and says that more exist

#### Scenario: Done task left out

- **WHEN** on Wednesday 30 September a user has an open task dated 2 October and a done task dated 1 October
- **THEN** the page lists the open task and not the done one

#### Scenario: Marked done from the page

- **WHEN** a user opens an item on the Upcoming page, turns on Done, and closes the sheet
- **THEN** the item is no longer listed

#### Scenario: Reopened

- **WHEN** a user reopens a done task dated tomorrow
- **THEN** the Upcoming page lists it again
