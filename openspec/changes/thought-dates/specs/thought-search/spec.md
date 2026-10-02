## MODIFIED Requirements

### Requirement: Filters and order

A search SHALL accept an optional set of tags and SHALL then return only thoughts that carry at least one of them. It SHALL accept an optional start date and end date and SHALL then return only thoughts created within them. It SHALL accept a newest-first option, which SHALL order the results that pass by created time, newest first, instead of by relevance. It SHALL accept an optional first and last day for the thought's own date, and SHALL then return only dated thoughts whose date overlaps those days: a thought from its start day to its end day, or on its start day when it has no end. A thought with no date SHALL NOT pass this filter. The created-time filter and the thought-date filter SHALL be separate and SHALL be usable together. All these days SHALL be the user's local days. When a thought-date filter is given, the query SHALL be optional. A search with a thought-date filter and no query SHALL return every dated thought that passes the filters, up to the configured number of results, ordered by date: by start day, a thought with no time before one with a time, then by start time. It SHALL make no embedding call.

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

#### Scenario: No query and no thought date

- **WHEN** a search has no query and no thought-date filter
- **THEN** the search is refused, naming the query
