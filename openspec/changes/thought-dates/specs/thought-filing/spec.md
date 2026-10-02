## ADDED Requirements

### Requirement: A proposal can carry a date

When a thought is about a set date or time, the model SHALL propose it with a date: a start, and an end only when the user names one. A date SHALL have a time only when the user names a time. A thought that is not about a set date SHALL be proposed with no date. The date SHALL NOT depend on the category: any category can have a date, and the category SHALL stay one value. The proposal card SHALL show the date as fields the user can change or clear before confirming, and SHALL show that there is no date when there is none. When a part has two date choices, the card SHALL show both as buttons, with a "No date" button, and SHALL NOT allow confirming until the user picks a choice, picks "No date", or sets the date fields. The system SHALL refuse a confirm of such a part that does not say which date the user picked, naming the date, and nothing SHALL be stored. Confirming SHALL store the date as the card shows it, with the user's current time zone. A date the store refuses SHALL be shown on the card naming the date, keeping the user's input, and nothing SHALL be stored. Merging parts SHALL keep the first part's date, or its two choices.

#### Scenario: A task on a day

- **WHEN** a user sends `/push call the plumber on Monday` on Wednesday 30 September 2026
- **THEN** the card shows the category `task` and the start Monday 5 October 2026, with no time and no end

#### Scenario: An evening event

- **WHEN** a user sends `/push dinner with Sam Friday at 7` on Wednesday 30 September 2026
- **THEN** the card shows the start Friday 2 October 2026 at 19:00, with no end

#### Scenario: A trip over several days

- **WHEN** a user sends `/push trip to Oslo 3-6 Nov`
- **THEN** the card shows the start 3 November and the end 6 November, with no times

#### Scenario: A meeting with an end time

- **WHEN** a user sends `/push meeting 10-11 on Tuesday`
- **THEN** the card shows the start Tuesday at 10:00 and the end Tuesday at 11:00

#### Scenario: No date

- **WHEN** a user sends `/push idea: a podcast about maps`
- **THEN** the card shows no date

#### Scenario: Changed on the card

- **WHEN** a card shows the start Monday, the user changes it to Tuesday at 09:00, and confirms
- **THEN** the stored thought has the start Tuesday at 09:00

#### Scenario: Cleared on the card

- **WHEN** a card shows a date, the user clears it, and confirms
- **THEN** the stored thought has no date

#### Scenario: Ambiguous day shown as two choices

- **WHEN** a user sends `/push dinner with Sam Friday at 7` on Friday 2 October 2026
- **THEN** the card shows two buttons, Friday 2 October at 19:00 and Friday 9 October at 19:00, and a "No date" button
- **AND** the card cannot be confirmed yet

#### Scenario: Pick a choice

- **WHEN** a card shows two date choices, the user picks Friday 9 October at 19:00, and confirms
- **THEN** the stored thought has the start Friday 9 October 2026 at 19:00

#### Scenario: Pick no date

- **WHEN** a card shows two date choices, the user picks "No date", and confirms
- **THEN** the stored thought has no date

#### Scenario: Confirm before picking

- **WHEN** a confirm request for a part with two date choices does not say which date the user picked
- **THEN** the system refuses it naming the date
- **AND** nothing is stored

#### Scenario: Refused date

- **WHEN** a user sets the end before the start on a card and confirms
- **THEN** the card says the date is not valid and keeps the user's input
- **AND** nothing is stored
