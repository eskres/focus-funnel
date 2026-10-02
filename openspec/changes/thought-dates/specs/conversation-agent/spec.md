## ADDED Requirements

### Requirement: The model knows the user's local date

The browser SHALL send its IANA time zone with each message and with each request for an offered proposal before archive and `/compact`. The model SHALL be told today's date and weekday in that time zone, not in UTC. A missing or unknown time zone SHALL be read as UTC, and the message SHALL NOT be refused for it. The dates the model passes to the search tool SHALL be read as days in that time zone, both for when a thought was filed and for the thought's own date.

#### Scenario: Late evening west of UTC

- **WHEN** a user in `America/Los_Angeles` sends a message at 22:00 local time on Wednesday 30 September, which is Thursday 1 October in UTC
- **THEN** the model is told that today is Wednesday 30 September

#### Scenario: Early morning east of UTC

- **WHEN** a user in `Asia/Tokyo` sends a message at 06:00 local time on Thursday 1 October, which is Wednesday 30 September in UTC
- **THEN** the model is told that today is Thursday 1 October

#### Scenario: No time zone sent

- **WHEN** a message arrives with no time zone, or with `Mars/Base`
- **THEN** the turn runs, and the model is told today's date in UTC

#### Scenario: Filed since today, in local days

- **WHEN** a user in `America/Los_Angeles` filed a thought at 20:00 local time on 30 September, and later that evening asks what they filed today
- **THEN** the search the model runs from 30 September includes that thought

### Requirement: The tools carry dates

Each proposal part SHALL take an optional date: a start, and an optional end, each a date or a date and time. Instead of one date, a part SHALL be able to give two date choices. The proposal tool SHALL tell the model to give a date only when the thought is about a set date or time, to work out a weekday or a relative day such as "tomorrow" from today's date, and to give a time or an end only when the user names one. A weekday SHALL mean the soonest such day after today, with one date. The model SHALL NOT guess an ambiguous day, and SHALL give two choices instead:

- A weekday that is today's weekday: today, and the same weekday one week later.
- "Next" with a weekday: the soonest such day after today, and the same weekday one week after that.

The model SHALL be told that weeks start on Monday, so "this week" runs from Monday to Sunday. A date or a choice the model gives that is not valid SHALL be dropped from the part, and the rest of the part SHALL be kept; when one valid choice is left, it SHALL become the part's date. The search tool SHALL take an optional first and last day for the thought's own date, separate from its start date for when the thought was filed, and the query SHALL be optional when those days are given. The search result SHALL show each dated thought's date. A held proposal's note to the model SHALL include each part's date, or both its choices.

#### Scenario: What is on this week

- **WHEN** a user asks what is on this week on Friday 2 October 2026
- **THEN** the model can call the search tool with no query and the days 28 September to 4 October 2026 as the thought's dates
- **AND** the tool result lists the dated thoughts in those days, each with its date

#### Scenario: Another weekday

- **WHEN** a user sends `/push dinner with Sam Friday at 7` on Wednesday 30 September 2026
- **THEN** the proposal part has the one date `2026-10-02T19:00` and no choices

#### Scenario: Today's weekday

- **WHEN** a user sends `/push dinner with Sam Friday at 7` on Friday 2 October 2026
- **THEN** the proposal part has two choices, `2026-10-02T19:00` and `2026-10-09T19:00`, and no single date

#### Scenario: Next weekday

- **WHEN** a user sends `/push call the plumber next Friday` on Wednesday 30 September 2026
- **THEN** the proposal part has two choices, `2026-10-02` and `2026-10-09`, and no single date

#### Scenario: Relative day

- **WHEN** a user sends `/push dentist tomorrow at 9` on Wednesday 30 September 2026
- **THEN** the proposal part has the start `2026-10-01T09:00` and no end

#### Scenario: Not valid from the model

- **WHEN** the model proposes a part with the start `2026-02-30`
- **THEN** the card shows the part's title, summary, tags, and category, and no date

#### Scenario: Held proposal with a date

- **WHEN** a proposal with a dated part is held and the user sends another message
- **THEN** the note to the model about the held proposal includes the part's date

#### Scenario: One valid choice

- **WHEN** the model gives a part the two choices `2026-10-02` and `2026-02-30`
- **THEN** the part has the one date `2026-10-02` and no choices
