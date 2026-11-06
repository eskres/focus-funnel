## MODIFIED Requirements

### Requirement: The Upcoming page lists dated thoughts from today on

The app SHALL have an Upcoming page, reached from a link in the sidebar. It SHALL list the user's open dated thoughts that do not repeat and whose end day, or start day when there is no end, is today or later, and the user's open repeating thoughts that have an occurrence on today or later, where today is the browser's local date. It SHALL NOT list a thought that is done. A thought marked done in the sheet SHALL no longer be listed once the sheet closes, and a thought set back to open SHALL be listed again when its date is today or later, or, for a repeating thought, when it has an occurrence on today or later. A thought that started before today and ends today or later SHALL be listed. A thought that does not repeat and is dated before today SHALL NOT be listed. A thought with no date SHALL NOT be listed. A repeating thought SHALL be listed once, at its next occurrence: the first one on today or later. It SHALL show that occurrence's day and time and that the thought repeats, and SHALL NOT be listed when it has no occurrence on today or later. The list SHALL be in date order: by start day, a thought with no time before one with a time, then by start time, then by when it was filed, where a repeating thought's start is that of its next occurrence. It SHALL show at most 200 thoughts and SHALL say when more exist.

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

#### Scenario: Repeating thought started last month

- **WHEN** on Wednesday 4 November 2026 a user has a thought repeating every week on Monday from 5 October 2026, and a dinner dated Saturday 7 November
- **THEN** the page lists the dinner, then the weekly thought once, under Monday 9 November, saying that it repeats

#### Scenario: Repeat ended

- **WHEN** on Wednesday 4 November 2026 a user has a thought that repeated every day until 31 October 2026
- **THEN** the page does not list it

### Requirement: The Upcoming page groups by day

The page SHALL group the thoughts under a heading per day: "Today", "Tomorrow", then the weekday and date. A thought that does not repeat and started before today SHALL be listed under "Today". A repeating thought SHALL be listed under the day of its next occurrence, the one the page shows, even when its first occurrence was before today. Each item SHALL show its time, or its end when it spans days, its title, and its category.

#### Scenario: Day headings

- **WHEN** on Wednesday 30 September a user has thoughts dated 30 September, 1 October, and 5 October
- **THEN** the page shows them under "Today", "Tomorrow", and "Monday 5 October"

#### Scenario: Item fields

- **WHEN** the page lists a dinner dated 2 October at 19:00 with the category `event`
- **THEN** its item shows `19:00`, the title, and `event`

#### Scenario: Repeating thought under its next occurrence

- **WHEN** on Wednesday 4 November 2026 a user has a trip dated 3 to 6 November and a thought repeating every week on Monday from 5 October 2026
- **THEN** the page shows the trip under "Today" and the weekly thought under "Monday 9 November", not under "Today"
