## MODIFIED Requirements

### Requirement: Filters and order

A search SHALL accept an optional set of tags and SHALL then return only thoughts that carry at least one of them. It SHALL accept an optional start date and end date and SHALL then return only thoughts created within them. It SHALL accept a newest-first option, which SHALL order the results that pass by created time, newest first, instead of by relevance. It SHALL accept an optional first and last day for the thought's own date, and SHALL then return only dated thoughts whose date overlaps those days: a thought from its start day to its end day, or on its start day when it has no end. A thought with no date SHALL NOT pass this filter. The created-time filter and the thought-date filter SHALL be separate and SHALL be usable together. All these days SHALL be the user's local days. It SHALL accept an optional status filter, `open`, and SHALL then return only open thoughts; without a status filter, it SHALL return open and done thoughts alike. It SHALL accept an optional category and SHALL then return only thoughts with that category. All these filters SHALL work together and with a query. Each result SHALL carry the thought's status. When a thought-date filter, a status filter, or a category filter is given, the query SHALL be optional. A search with any of these filters and no query SHALL return every one of the user's own thoughts that passes the filters, up to the configured number of results, with the number of the user's thoughts that matched; it SHALL NOT return or count another user's thoughts. With a thought-date filter, it SHALL be ordered by date: by start day, a thought with no time before one with a time, then by start time. Without one, it SHALL be ordered newest filed first. It SHALL make no embedding call.

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
