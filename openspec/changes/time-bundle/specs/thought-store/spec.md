## ADDED Requirements

### Requirement: A dated thought can repeat

A thought's date SHALL be able to repeat: every given number of days, weeks, months, or years, from 1 to 99, with an optional last day. The start SHALL be the first occurrence. An occurrence on the last day SHALL count. Each occurrence SHALL have the start's time, and the end's time when the date has an end. A repeat SHALL be stored with the date and read back as stored, and a thought with no repeat SHALL be read back with none.

#### Scenario: Every Monday

- **WHEN** a thought is stored with the start `2026-11-09`, a weekly repeat on Monday, and no last day
- **THEN** it is read back with that start and repeat, and its occurrences are 9, 16, 23, and 30 November and on

#### Scenario: No repeat

- **WHEN** a dated thought is stored with no repeat
- **THEN** it is read back with no repeat

### Requirement: Where a repeat falls

A weekly repeat SHALL fall on one or more weekdays, always including the start's weekday, in every given number of weeks counted from the start's week, with weeks starting on Monday. A monthly repeat SHALL fall on the start's day of the month, and SHALL skip a month that has no such day. A yearly repeat SHALL fall on the start's month and day, and SHALL skip a year that has no such day.

#### Scenario: Every other week on two days

- **WHEN** a thought is stored with the start `2026-11-09T18:00`, a repeat every 2 weeks on Monday and Thursday, and the last day `2026-11-30`
- **THEN** its occurrences are 9, 12, 23, and 26 November at 18:00, and none after 30 November

#### Scenario: The 31st of each month

- **WHEN** a thought is stored with the start `2027-01-31` and a monthly repeat
- **THEN** its occurrences are 31 January, 31 March, and 31 May 2027 and on, and none in February, April, or June

### Requirement: Repeat fields are checked

The system SHALL refuse a repeat, naming the field `when`, when it has no date, an unknown unit, a count that is not a whole number or is below 1 or above 99, weekdays on a unit other than weeks, an unknown weekday, a last day not written `YYYY-MM-DD` or before the start day, or an end on a day other than the start day. Nothing SHALL be stored when it is refused.

#### Scenario: Unknown unit

- **WHEN** a thought is stored with the start `2026-11-09` and a repeat every `fortnight`
- **THEN** the system refuses it naming `when`, and nothing is stored

#### Scenario: Last day before the start

- **WHEN** a thought is stored with the start `2026-11-09`, a weekly repeat, and the last day `2026-11-01`
- **THEN** the system refuses it naming `when`, and nothing is stored

#### Scenario: Repeat over several days

- **WHEN** a thought is stored with the start `2026-11-06`, the end `2026-11-08`, and a monthly repeat
- **THEN** the system refuses it naming `when`, and nothing is stored

### Requirement: A dated thought can have reminders

A thought's date SHALL be able to have up to five reminders, each a whole number of minutes before the start. Two reminders with the same number of minutes SHALL count as one, and the limit of five SHALL apply after they are merged. Reminders SHALL be read back in order, fewest minutes first. Clearing a thought's date SHALL clear its reminders and its repeat.

#### Scenario: Two reminders

- **WHEN** a thought dated `2026-10-02T19:00` is stored with the reminders 1,440 and 60
- **THEN** it is read back with the reminders 60 and 1,440

#### Scenario: Same reminder twice

- **WHEN** a thought dated `2026-10-02T19:00` is stored with the reminders 60 and 60
- **THEN** it is read back with the one reminder 60

#### Scenario: Six entries, five distinct

- **WHEN** a thought dated `2026-10-02T19:00` is stored with the reminders 0, 5, 10, 15, 30, and 30
- **THEN** it is stored, and read back with the five reminders 0, 5, 10, 15, and 30

#### Scenario: Date cleared

- **WHEN** a dated thought with a repeat and a reminder has its date cleared
- **THEN** it is read back with no date, no repeat, and no reminders

### Requirement: Reminder fields are checked

The system SHALL refuse more than five reminders, a number of minutes below 0 or above 40,320 (four weeks), a value that is not a whole number (a true or false value, `1.5`, `60.0`, and the text `"60"` are not), or a reminder on a thought with no date, naming the field `when`, and nothing SHALL be stored.

#### Scenario: Too many

- **WHEN** a thought is stored with six different reminders
- **THEN** the system refuses it naming `when`, and nothing is stored

#### Scenario: Five weeks before

- **WHEN** a thought is stored with the reminder 50,400
- **THEN** the system refuses it naming `when`, and nothing is stored

#### Scenario: Not a whole number

- **WHEN** a thought dated `2026-10-02T19:00` is stored with the reminders `[1.5]`, or with the reminders `[true]`
- **THEN** the system refuses it naming `when`, and nothing is stored
