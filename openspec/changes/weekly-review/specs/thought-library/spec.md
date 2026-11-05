## MODIFIED Requirements

### Requirement: The list filters by category, tag, and status

A category filter SHALL list only thoughts with that category. A tag filter SHALL list only thoughts with that tag, matched after trimming, lowercasing, collapsing inner spaces, and dropping a leading `#`. A category or tag that is empty after cleaning SHALL be read as no filter. A status filter SHALL list only thoughts with that status. Its choices SHALL be every status a thought can have. With no status filter, the list SHALL hold thoughts of every status.

#### Scenario: Category

- **WHEN** a user filters by the category `task`
- **THEN** every row has the category `task`

#### Scenario: Tag

- **WHEN** a user filters by the tag ` Home`
- **THEN** every row carries the tag `home`

#### Scenario: Tag written with a hash

- **WHEN** a user filters by the tag `#home`
- **THEN** every row carries the tag `home`

#### Scenario: Blank tag

- **WHEN** a user filters by the tag `   `
- **THEN** the page lists every thought, as with no tag filter

#### Scenario: Open thoughts

- **WHEN** a user has an open task `Call the plumber` and a done task `Buy oat milk`, and filters by the status `open`
- **THEN** the page lists `Call the plumber` and not `Buy oat milk`

#### Scenario: Done thoughts

- **WHEN** the same user filters by the status `done`
- **THEN** the page lists `Buy oat milk` and not `Call the plumber`

#### Scenario: Any status

- **WHEN** the same user sets no status filter
- **THEN** the page lists both tasks

#### Scenario: Archived thoughts

- **WHEN** a user has an open task `Call the plumber` and an archived idea `Podcast about maps`, and filters by the status `archived`
- **THEN** the page lists `Podcast about maps`, showing that it is archived, and not `Call the plumber`
- **AND** with no status filter the page lists both

### Requirement: The list follows changes made in the sheet

When the sheet closes, and when a change made in it (an edit, a delete, Done, Archive, Restore, or an undone addition) is saved, even after it closed, the rows shown SHALL be loaded again with the same filters, as many as were shown, and at least one page of 50. If that fails, the rows SHALL stay, and the page SHALL say what failed and offer to try again. A changed thought SHALL show its change; a deleted one, or one that no longer passes the filters, SHALL no longer be listed.

#### Scenario: Edited in the sheet

- **WHEN** a user opens a row, changes its title, saves, and closes the sheet
- **THEN** the row shows the new title in the same place

#### Scenario: Deleted in the sheet

- **WHEN** a user opens a row, deletes the thought, and the sheet closes
- **THEN** the thought is no longer listed

#### Scenario: Marked done under the open filter

- **WHEN** a user filters by the status `open`, opens a task, turns on Done, and closes the sheet
- **THEN** the task is no longer listed

#### Scenario: Closed while saving

- **WHEN** a user filters by the status `open`, opens a task, turns on Done, and closes the sheet before the change is saved
- **THEN** once the change is saved, the task is no longer listed

#### Scenario: Archived under the open filter

- **WHEN** a user filters by the status `open`, opens an idea, chooses Archive, and closes the sheet before the change is saved
- **THEN** once the change is saved, the idea is no longer listed

#### Scenario: Restored under the archived filter

- **WHEN** a user filters by the status `archived`, opens an idea, chooses Restore, and closes the sheet
- **THEN** the idea is no longer listed

#### Scenario: Undone in the sheet

- **WHEN** a user filters by the tag `home`, opens a thought whose last addition added the tag `home`, undoes that addition, and closes the sheet before the undo is saved
- **THEN** once the undo is saved, the thought is no longer listed

#### Scenario: Deleted elsewhere

- **WHEN** a user opens a row whose thought was deleted since the list was loaded
- **THEN** the sheet says the thought no longer exists
- **AND** after the sheet closes, the thought is no longer listed

#### Scenario: Place kept

- **WHEN** a user has shown 100 rows, opens the 80th, and closes the sheet without a change
- **THEN** the page still lists the same 100 rows

#### Scenario: No more rows than before

- **WHEN** a user with 200 thoughts has shown 50 rows, opens one, and closes the sheet without a change
- **THEN** the page lists the same 50 rows and still offers to show more

#### Scenario: Fewer rows than a page

- **WHEN** a user filters by the category `task`, which 10 thoughts pass, a task is filed elsewhere, and the user opens a row and closes the sheet
- **THEN** the page lists 11 rows, with the new task first

#### Scenario: Reload fails

- **WHEN** a user has shown 120 rows, opens one, closes the sheet, and loading the rows again fails
- **THEN** the page still lists the same 120 rows, says what failed, and offers to try again
