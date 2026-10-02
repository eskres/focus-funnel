## Purpose

Lists a user's dated thoughts from today on, in date order, so the user can see what is coming up without asking the chat.

## ADDED Requirements

### Requirement: The Upcoming page lists dated thoughts from today on

The app SHALL have an Upcoming page, reached from a link in the sidebar. It SHALL list the user's dated thoughts whose end day, or start day when there is no end, is today or later, where today is the browser's local date. A thought that started before today and ends today or later SHALL be listed. A thought dated before today SHALL NOT be listed. A thought with no date SHALL NOT be listed. The list SHALL be in date order: by start day, a thought with no time before one with a time, then by start time, then by when it was filed. It SHALL show at most 200 thoughts and SHALL say when more exist.

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

### Requirement: The Upcoming page groups by day

The page SHALL group the thoughts under a heading per day: "Today", "Tomorrow", then the weekday and date. A thought that started before today SHALL be listed under "Today". Each item SHALL show its time, or its end when it spans days, its title, and its category.

#### Scenario: Day headings

- **WHEN** on Wednesday 30 September a user has thoughts dated 30 September, 1 October, and 5 October
- **THEN** the page shows them under "Today", "Tomorrow", and "Monday 5 October"

#### Scenario: Item fields

- **WHEN** the page lists a dinner dated 2 October at 19:00 with the category `event`
- **THEN** its item shows `19:00`, the title, and `event`

### Requirement: An upcoming item opens the thought

Clicking an item SHALL open the thought in the side sheet over the Upcoming page, with the page address naming it, as in a conversation. After an edit or delete in the sheet, the list SHALL show the change when the sheet closes.

#### Scenario: Open

- **WHEN** a user clicks an item on the Upcoming page
- **THEN** the side sheet shows that thought, and the list is still visible behind it

#### Scenario: Date moved to the past

- **WHEN** a user opens an item, changes its date to last week, saves, and closes the sheet
- **THEN** the item is no longer listed

### Requirement: Only the owner's thoughts are listed

The Upcoming page and the request behind it SHALL list only thoughts the user owns.

#### Scenario: Two users

- **WHEN** two users each have a thought dated tomorrow
- **THEN** each user's page lists only their own thought
