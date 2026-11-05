## MODIFIED Requirements

### Requirement: Filters and order

A search SHALL accept an optional set of tags and SHALL then return only thoughts that carry at least one of them. It SHALL accept an optional start date and end date and SHALL then return only thoughts created within them. It SHALL accept a newest-first option, which SHALL order the results that pass by created time, newest first, instead of by relevance. It SHALL accept an optional first and last day for the thought's own date, either or both, and SHALL then return only dated thoughts whose date overlaps those days: a thought that does not repeat from its start day to its end day, or on its start day when it has no end; a repeating thought on each of its occurrences. A repeating thought SHALL pass when one of its occurrences falls within those days, and SHALL be returned once, however many of its occurrences fall within them. A repeating thought whose last day is before those days, or whose first occurrence is after them, SHALL NOT pass. A thought with no date SHALL NOT pass this filter. The created-time filter and the thought-date filter SHALL be separate and SHALL be usable together. All these days SHALL be the user's local days. It SHALL accept an optional status filter, `open`, and SHALL then return only open thoughts; without a status filter, it SHALL return open and done thoughts alike. It SHALL accept an optional category and SHALL then return only thoughts with that category. All these filters SHALL work together and with a query. Each result SHALL carry the thought's status. When a thought-date filter, a status filter, or a category filter is given, the query SHALL be optional. A search with any of these filters and no query SHALL return every one of the user's own thoughts that passes the filters, up to the configured number of results, with the number of the user's thoughts that matched; it SHALL NOT return or count another user's thoughts. With a thought-date filter, it SHALL be ordered by date: by start day, a thought with no time before one with a time, then by start time, where a repeating thought's start is that of its first occurrence within the given days. The configured number of results SHALL be the first ones in that order, repeating thoughts included. Without one, it SHALL be ordered newest filed first. It SHALL make no embedding call.

#### Scenario: Tag filter

- **WHEN** a user searches for `plans` with the tag `work`
- **THEN** every result carries the tag `work`

#### Scenario: Tag nobody uses

- **WHEN** a user searches with a tag none of their thoughts carries
- **THEN** the result is empty and no provider is called

#### Scenario: Since a date

- **WHEN** a user searches for `ideas` from 1 September
- **THEN** every result was created on or after 1 September

#### Scenario: Newest first

- **WHEN** a user searches with the newest-first option
- **THEN** the results are ordered by created time, newest first

#### Scenario: What is on this week

- **WHEN** a user has a dinner dated Friday 2 October, a trip dated 30 September to 3 October, and a dentist visit dated 12 October, and searches with no query for the days 28 September to 4 October
- **THEN** the result holds the trip and then the dinner, and not the dentist visit
- **AND** no provider is called

#### Scenario: Filed date and thought date are separate

- **WHEN** a thought was filed on 1 September and is dated 2 October, and a user searches for the thought's dates 1 to 7 October
- **THEN** the thought is in the result
- **AND** a search for thoughts filed from 1 October does not return it

#### Scenario: Thought date with a query

- **WHEN** a user searches for `dinner` with the thought's dates 1 to 7 October
- **THEN** every result matches `dinner` and is dated within those days

#### Scenario: Open only

- **WHEN** a user has an open task `Call the plumber` and a done task `Pay the plumber`, and searches for `plumber` with the status `open`
- **THEN** the result holds `Call the plumber` and not `Pay the plumber`

#### Scenario: Done thoughts still found

- **WHEN** a user has a done task `Buy oat milk` and searches for `oat milk` with no status
- **THEN** the result holds `Buy oat milk`, marked as done

#### Scenario: Category filter

- **WHEN** a user searches for `plumber` with the category `task`
- **THEN** every result has the category `task`

#### Scenario: Open tasks

- **WHEN** a user has an open task `Call the plumber`, a done task `Buy oat milk`, and an open idea `Podcast about maps`, and searches with no query, the status `open`, and the category `task`
- **THEN** the result holds only `Call the plumber`
- **AND** no provider is called

#### Scenario: Newest filed first

- **WHEN** a user has two open tasks filed on 1 and 3 November and searches with no query and the status `open`
- **THEN** the task filed on 3 November comes first

#### Scenario: More than the limit

- **WHEN** a user with more open tasks than the configured number of results searches with no query, the status `open`, and the category `task`
- **THEN** the result holds the configured number and says that more matched

#### Scenario: Only the user's thoughts

- **WHEN** another user has open tasks, one titled `Call the plumber`, and a user searches with no query, the status `open`, and the category `task`
- **THEN** the result holds only the searching user's thoughts
- **AND** the number that matched counts only theirs

#### Scenario: No query and no filter

- **WHEN** a search has no query and no thought-date, status, or category filter
- **THEN** the search is refused, naming the query

#### Scenario: A weekly thought in a week

- **WHEN** a user has a thought repeating every week on Monday from 2 November 2026 and a dinner dated Saturday 14 November, and searches with no query for the days 9 to 15 November 2026
- **THEN** the result holds the weekly thought and then the dinner, the weekly thought once

#### Scenario: A weekday the thought does not repeat on

- **WHEN** the same user searches with no query for Tuesday 10 November 2026 only
- **THEN** the weekly thought is not in the result

#### Scenario: Ended

- **WHEN** a thought repeated every day from 1 October to 31 October 2026, and a user searches for the days 1 to 7 November 2026
- **THEN** the thought is not in the result

#### Scenario: With a query

- **WHEN** a user with `Take the bins out`, repeating every week on Monday from 2 November 2026, searches for `bins` with the days 9 to 15 November 2026
- **THEN** `Take the bins out` is in the result

#### Scenario: From a day, with no last day

- **WHEN** a user with `Take the bins out`, repeating every week on Monday from 2 November 2026 with no last day, searches with no query from 9 November 2026 and no last day
- **THEN** `Take the bins out` is in the result, at Monday 9 November

#### Scenario: Up to a day, with no first day

- **WHEN** the same user searches with no query up to 31 October 2026 and no first day
- **THEN** `Take the bins out` is not in the result
- **AND** a search up to 2 November 2026 has it, at Monday 2 November

#### Scenario: Repeating thoughts started long ago

- **WHEN** a user has three thoughts repeating every week from months ago and six one-off thoughts in the days asked for, and the configured number of results is five
- **THEN** the result holds the first five of the nine by the occurrence each shows, and says that more matched
