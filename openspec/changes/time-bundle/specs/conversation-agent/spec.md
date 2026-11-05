## ADDED Requirements

### Requirement: The model proposes a repeat only when the thing repeats

A proposal part's date SHALL take an optional repeat, and so SHALL each of its two date choices. The proposal tool SHALL tell the model to give a repeat only when the user says the thing repeats, with the start at the first occurrence on or after today, where today counts, and never to give two choices for a repeating date.

#### Scenario: Every Friday said on a Friday

- **WHEN** a user sends `/push yoga every Friday at 7am` on Friday 6 November 2026
- **THEN** the proposal part has the one date `2026-11-06T07:00`, repeating every week on Friday, and no choices

#### Scenario: One-off

- **WHEN** a user sends `/push dinner with Sam Friday at 7` on Wednesday 4 November 2026
- **THEN** the proposal part has no repeat

### Requirement: The model proposes reminders only when asked

A proposal part's date SHALL take optional reminders, and so SHALL each of its two date choices. The proposal tool SHALL tell the model to give reminders only when the user asks to be reminded, in minutes before the start, with 0 when the user names no time before.

#### Scenario: Remind me with no time

- **WHEN** a user sends `/push call mum Sunday, remind me` on Wednesday 4 November 2026
- **THEN** the proposal part has the start `2026-11-08` and the reminder 0

#### Scenario: The day before

- **WHEN** a user sends `/push passport renewal on 20 November, remind me the day before`
- **THEN** the proposal part has the start `2026-11-20` and the reminder 1,440

### Requirement: Repeats and reminders from the model are checked and noted

A repeat or reminders the model gives that are not valid SHALL be dropped from the part, and the rest of the part, its date included, SHALL be kept. A held proposal's note to the model SHALL include each part's repeat and reminders.

#### Scenario: Not valid from the model

- **WHEN** the model proposes a part dated `2026-11-09` with a repeat every `fortnight`
- **THEN** the card shows the part with the date `2026-11-09` and no repeat

#### Scenario: Held proposal with a repeat

- **WHEN** a proposal with a part repeating every week on Monday is held and the user sends another message
- **THEN** the note to the model about the held proposal says that the part repeats every week on Monday

### Requirement: A repeating thought is not marked done for one occurrence

The model SHALL be told that marking a repeating thought done ends all its occurrences. It SHALL NOT propose marking a repeating thought done because one occurrence happened, and SHALL propose it only when the user says the repeating thing has ended or they stopped it.

#### Scenario: One week's bins

- **WHEN** a user has an open thought `Take the bins out` repeating every week, and says "I took the bins out"
- **THEN** the model does not propose marking it done

#### Scenario: Stopped for good

- **WHEN** the same user says "we don't do the bins any more, the council collects them"
- **THEN** the model proposes marking `Take the bins out` done

### Requirement: The search result shows a repeat

The search result SHALL show a repeating thought once, with the occurrence that matched, or its first occurrence when no thought-date filter was given, and with its repeat.

#### Scenario: What is on this week

- **WHEN** a user with `Take the bins out`, repeating every week on Monday from 2 November 2026, asks what is on this week on Wednesday 11 November 2026
- **THEN** the search result lists `Take the bins out` once, on Monday 9 November, and says it repeats every week on Monday
