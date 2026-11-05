## Purpose

Lists a user's filed thoughts on a page of their own, newest first, with filters, so the user can browse what is filed and open any thought without asking the chat.

## ADDED Requirements

### Requirement: The Library page lists the user's thoughts, newest filed first

The app SHALL have a Library page, reached from a link in the sidebar. It SHALL list the user's thoughts, newest filed first. Two thoughts filed at the same time SHALL each be listed once, in a fixed order. Changing a thought SHALL NOT move it in the list: its place comes from the time it was filed. When the user has no thoughts, the page SHALL say so.

#### Scenario: Newest first

- **WHEN** a user filed `Buy oat milk` on 1 November, `Podcast about maps` on 3 November, and `Call the plumber` on 2 November
- **THEN** the page lists `Podcast about maps`, then `Call the plumber`, then `Buy oat milk`

#### Scenario: Edited thought keeps its place

- **WHEN** a user changes the title of the oldest thought on the page
- **THEN** the thought is still listed last, with its new title

#### Scenario: No thoughts yet

- **WHEN** a user with no thoughts opens the page
- **THEN** the page says no thoughts are filed yet

### Requirement: The list is shown 50 thoughts at a time

The page SHALL show the 50 newest thoughts first, and SHALL offer a way to show the next 50 while more exist. When no more exist, it SHALL NOT offer more.

#### Scenario: More than a page

- **WHEN** a user with 120 thoughts opens the page
- **THEN** the page lists the 50 newest and offers to show more
- **AND** showing more twice lists all 120, and then no more is offered

### Requirement: A row shows the thought at a glance

Each row SHALL show the thought's title, category, tags, the day it was filed, its own date when it has one, and its status when the status is not `open`. A thought with no category or no tags SHALL show no empty badge in their place.

#### Scenario: Row fields

- **WHEN** a user has a done task `Call the plumber`, filed on 2 November, dated 4 November, tagged `home`
- **THEN** its row shows `Call the plumber`, `task`, `home`, the filed day 2 November, the date 4 November, and that it is done

#### Scenario: Open thought

- **WHEN** a user has an open idea `Podcast about maps`
- **THEN** its row shows no status

#### Scenario: Uncategorised row

- **WHEN** a user has an open thought `Loose note` with no category and no tags
- **THEN** its row shows `Loose note` and its filed day, and no category badge, tag, or status

### Requirement: Paging stays stable while thoughts change

Showing more SHALL list the thoughts filed before the last one shown, in the same order, with no thought listed twice and none left out, even when thoughts were filed, changed, marked done, or deleted since the previous page was shown, including the last one shown. A thought filed after the first page was shown SHALL NOT appear in a later page; it SHALL appear when the list is loaded again from the newest.

#### Scenario: Thought filed while browsing

- **WHEN** a user with 120 thoughts sees the first 50, files a new thought from another tab, and shows more
- **THEN** the next rows are the 51st to the 100th of the 120, with none repeated
- **AND** the new thought is listed first once the page is loaded again

#### Scenario: Last shown thought deleted

- **WHEN** a user sees the first 50 thoughts, the 50th is deleted, and the user shows more
- **THEN** the next rows are the 51st to the 100th, with none left out

#### Scenario: Thought changed while browsing

- **WHEN** a user sees the first 50 thoughts, the 60th is edited and marked done, and the user shows more
- **THEN** the 60th is listed in its place among the next 50, once

#### Scenario: Same filed time

- **WHEN** three of a user's thoughts have the same filed time and the page boundary falls between them
- **THEN** each of the three is listed once across the two pages

### Requirement: The list can be filtered

The page SHALL offer four filters: a category, a tag, a status, and a range of filed days. Each SHALL be optional, and they SHALL work together. A filter SHALL keep the newest-first order and the paging of the list: showing more SHALL list only thoughts that pass the filters. Changing a filter SHALL list again from the newest. Leaving a filter as it was SHALL NOT list again, and the rows shown SHALL stay. When no thought passes the filters, the page SHALL say that no thoughts match the filters.

#### Scenario: Filters together

- **WHEN** a user filters by the category `task`, the tag `home`, the status `open`, and the filed days 1 to 30 November
- **THEN** every row is an open task tagged `home` and filed in November, newest first

#### Scenario: Show more keeps the filters

- **WHEN** a user with 120 thoughts tagged `home` and 60 that are not filters by the tag `home` and shows more twice
- **THEN** every new row also carries `home`
- **AND** all 120 tagged thoughts are listed once, newest first

#### Scenario: Tag field left unchanged

- **WHEN** a user has shown 100 rows filtered by the tag `home`, then moves into the Tag field and out of it without typing
- **THEN** the page still lists the same 100 rows

#### Scenario: Filter changed after showing more

- **WHEN** a user shows more, then changes the category filter
- **THEN** the page lists the 50 newest thoughts that pass the new filters

#### Scenario: Nothing matches

- **WHEN** a user filters by a tag none of their thoughts carries
- **THEN** the page says no thoughts match these filters

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

### Requirement: The list filters by filed days

A filed-day range SHALL list only thoughts filed on or after its first day and on or before its last day. The days SHALL be the user's local days. Either end of the range MAY be left open. The range SHALL apply to the day a thought was filed, not to the thought's own date.

#### Scenario: Filed days in local time

- **WHEN** a user in `America/Los_Angeles` filed a thought at 20:00 local time on 1 November, which is 2 November in UTC, and filters by the filed days 1 November to 1 November
- **THEN** the page lists that thought

#### Scenario: From a day only

- **WHEN** a user filed `Buy oat milk` on 1 November, `Call the plumber` on 2 November, and `Podcast about maps` on 3 November, and filters by the filed days from 2 November with no last day
- **THEN** the page lists `Podcast about maps`, then `Call the plumber`, and not `Buy oat milk`

#### Scenario: To a day only

- **WHEN** the same user filters by the filed days up to 2 November with no first day
- **THEN** the page lists `Call the plumber`, then `Buy oat milk`, and not `Podcast about maps`

#### Scenario: Filed date, not the thought's date

- **WHEN** a thought was filed on 1 October and is dated 5 November, and a user filters by the filed days 1 to 30 November
- **THEN** the page does not list that thought

### Requirement: A list request is checked

A list request SHALL be refused with HTTP 422 and the error code `validation_error`, with a message naming the field, when its page size is not a whole number from 1 to 100, its status is not a status a thought can have, its cursor cannot be read as a place in the list, or a filed day is not a date from 1900-01-01 to 9998-12-31. A parameter sent with an empty value SHALL be read as if it were absent, and SHALL NOT be refused.

#### Scenario: Not a status

- **WHEN** a list request has the status `pending`, which is not a status a thought can have
- **THEN** it is refused with 422 `validation_error` naming `status`

#### Scenario: Made-up cursor

- **WHEN** a list request has the cursor `abc`
- **THEN** it is refused with 422 `validation_error` naming `cursor`

#### Scenario: Cursor time out of range

- **WHEN** a list request has a cursor whose time is `0001-01-01T00:00:00+05:00`, which cannot be written in UTC
- **THEN** it is refused with 422 `validation_error` naming `cursor`

#### Scenario: Filed day that is not a date

- **WHEN** a list request has the first filed day `2026-02-30`
- **THEN** it is refused with 422 `validation_error` naming `filed_from`

#### Scenario: Filed day out of range

- **WHEN** a list request has the last filed day `9999-12-31`
- **THEN** it is refused with 422 `validation_error` naming `filed_to`

#### Scenario: Page size

- **WHEN** a list request asks for 500 thoughts
- **THEN** it is refused with 422 `validation_error` naming `limit`

#### Scenario: Empty parameter

- **WHEN** a list request has an empty status and an empty first filed day (`status=&filed_from=`)
- **THEN** it lists every thought, as the request without them does, and is not refused

### Requirement: An unknown filter value is not refused

A missing time zone, or one that is not a zone name the server knows, SHALL be read as `UTC`. A category or tag that no thought has, whatever its length or characters, SHALL list nothing and SHALL NOT be refused.

#### Scenario: No time zone

- **WHEN** a list request has filed days and no time zone
- **THEN** the days are read in `UTC`

#### Scenario: Unknown time zone

- **WHEN** a list request has filed days and the time zone `Mars/Base`
- **THEN** the days are read in `UTC`

#### Scenario: Time zone that is not a zone name

- **WHEN** a list request has filed days and the time zone `/etc/localtime`
- **THEN** the days are read in `UTC`

#### Scenario: Very long time zone

- **WHEN** a list request has filed days and a time zone of 256 letters, or one of 300 nested `a/` parts
- **THEN** the days are read in `UTC`, and the request is not refused and does not fail

#### Scenario: Long tag

- **WHEN** a list request has a tag of 60 characters
- **THEN** it lists nothing and is not refused

#### Scenario: Tag with a NUL character

- **WHEN** a list request has the tag `x` preceded by the character U+0000
- **THEN** it lists nothing and is not refused

### Requirement: A library row opens the thought

Clicking a row SHALL open the thought in the side sheet over the Library page, with the page address naming it, as in a conversation. Opening that address SHALL show the Library page with the thought open, and Back SHALL close the sheet.

#### Scenario: Open

- **WHEN** a user clicks a row on the Library page
- **THEN** the side sheet shows that thought, and the list is still visible behind it

#### Scenario: Copied address

- **WHEN** a user copies the address while a thought is open and opens it in a new tab
- **THEN** the Library page shows with the same thought open

#### Scenario: Back

- **WHEN** a user opens a row and presses Back
- **THEN** the sheet closes and the user stays on the Library page

### Requirement: The list follows changes made in the sheet

When the sheet closes, and when a change made in it is saved, even after it closed, the rows shown SHALL be loaded again with the same filters, as many as were shown before and no more, or one page when none were shown. If that fails, the rows SHALL stay, and the page SHALL say what failed and offer to try again. A changed thought SHALL show its change; a deleted thought, or one that no longer passes the filters, SHALL no longer be listed.

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

#### Scenario: Reload fails

- **WHEN** a user has shown 120 rows, opens one, closes the sheet, and loading the rows again fails
- **THEN** the page still lists the same 120 rows, says what failed, and offers to try again

### Requirement: Only the owner's thoughts are listed

The Library page and the request behind it SHALL list only thoughts the user owns, whatever the filters and the cursor. A cursor SHALL name only a place in the list, so a cursor taken from another user's list SHALL list only the requesting user's own thoughts.

#### Scenario: Two users

- **WHEN** two users each have thoughts tagged `home` and one of them filters by the tag `home`
- **THEN** the page lists only that user's thoughts

#### Scenario: Another user's cursor

- **WHEN** a user sends a list request with a cursor from another user's list
- **THEN** the answer holds only the requesting user's thoughts

### Requirement: Filter values stay out of the access log

The backend's access log SHALL NOT hold the query string of a list request, so a tag or category the user filtered by is not written there.

#### Scenario: Tag filter

- **WHEN** a user filters by the tag `therapy`
- **THEN** the backend's access log line for that request names the path `/api/thoughts` and does not hold `therapy`

### Requirement: Listing needs no provider and stays fast

Listing thoughts SHALL make no embedding call and no model call, so it SHALL work for a user with no provider key. For a user with 5,000 thoughts, the database part of one list request SHALL take under 50 milliseconds at the 95th percentile on the reference compose setup, for the first page and the last, and with any one filter.

#### Scenario: No provider key

- **WHEN** a user with thoughts and no provider key opens the Library page
- **THEN** the page lists their thoughts
- **AND** no provider is called

#### Scenario: Large collection

- **WHEN** a user with 5,000 thoughts requests pages of the list 100 times on the reference setup, from the first page to the last, and with each filter
- **THEN** 95 of the requests of each kind spend under 50 milliseconds in the database
