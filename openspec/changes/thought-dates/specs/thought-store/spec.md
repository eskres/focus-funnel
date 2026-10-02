## MODIFIED Requirements

### Requirement: A thought belongs to one user

The system SHALL store each thought with its owner, a title, a summary, tags, an optional category, the optional raw text it came from, an optional date, and the times it was created and last updated. A thought's date SHALL be a start and an optional end, each a calendar date with an optional time of day, and the time zone the date was set in. The date SHALL be kept as the user's local date and time, not turned into another zone. Every thought SHALL belong to exactly one user. Another user asking for it SHALL get the same answer as for a thought that does not exist.

#### Scenario: Stored thought

- **WHEN** a thought with a title, a summary, and two tags is stored for a user
- **THEN** it can be read back with the same title, summary, and tags, its owner, and its created and updated times

#### Scenario: Stored with a date

- **WHEN** a thought is stored with the start `2026-10-02 19:00`, no end, and the time zone `Europe/Oslo`
- **THEN** it can be read back with the start `2026-10-02 19:00`, no end, and the time zone `Europe/Oslo`

#### Scenario: Stored with no date

- **WHEN** a thought is stored with no date
- **THEN** it is read back with no date

#### Scenario: Another user's thought

- **WHEN** a user asks for, updates, or deletes a thought another user owns
- **THEN** the system answers as if the thought did not exist
- **AND** the other user's thought is unchanged

### Requirement: Thought fields are checked

The system SHALL refuse a thought with an empty title or summary, a title over 200 characters, a summary over 4,000 characters, raw text over 20,000 characters, more than 20 tags, or a tag over 50 characters, and SHALL name the field. Tags SHALL be trimmed and lowercased, and duplicate or empty tags SHALL be dropped. A date SHALL have a start. The start and the end SHALL each be a valid date, written `YYYY-MM-DD`, or a valid date and time to the minute, written `YYYY-MM-DDTHH:MM`. The start and the end SHALL both have a time or both have none. The end SHALL NOT be before the start. A date SHALL be refused naming the field `when`. A time zone that is missing or not a known IANA zone SHALL be stored as `UTC`.

#### Scenario: Empty summary

- **WHEN** a thought with a summary made only of whitespace is stored
- **THEN** the system refuses it naming the summary, and nothing is stored

#### Scenario: Tags cleaned

- **WHEN** a thought is stored with the tags ` Milk`, `milk`, and an empty tag
- **THEN** the thought has the single tag `milk`

#### Scenario: End before start

- **WHEN** a thought is stored with the start `2026-11-06` and the end `2026-11-03`
- **THEN** the system refuses it naming `when`, and nothing is stored

#### Scenario: Time on one side only

- **WHEN** a thought is stored with the start `2026-10-06T10:00` and the end `2026-10-06`
- **THEN** the system refuses it naming `when`, and nothing is stored

#### Scenario: Not a date

- **WHEN** a thought is stored with the start `next Friday`
- **THEN** the system refuses it naming `when`, and nothing is stored

#### Scenario: Unknown time zone

- **WHEN** a thought is stored with a date and the time zone `Mars/Base`
- **THEN** the thought is stored with the time zone `UTC`
