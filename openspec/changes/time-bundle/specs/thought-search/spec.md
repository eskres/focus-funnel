## ADDED Requirements

### Requirement: Repeating thoughts in the thought-date filter

For the thought-date filter, a repeating thought's date SHALL be each of its occurrences. A repeating thought SHALL pass the filter when one of its occurrences falls within the given days, and SHALL be returned once, however many of its occurrences fall within them. In date order, a repeating thought SHALL be placed by its first occurrence within the given days. A repeating thought whose last day is before the given days, or whose first occurrence is after them, SHALL NOT pass.

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
