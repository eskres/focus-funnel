## ADDED Requirements

### Requirement: A proposal can carry a repeat and reminders

When a thought repeats, the model SHALL propose its date with the repeat, starting at the first occurrence. When the user asks to be reminded, the model SHALL propose the date with reminders. The proposal card SHALL show the repeat and the reminders with the date, as fields the user can change or clear before confirming, and SHALL show that there are none when there are none. Choosing a repeat on the card SHALL keep the date to one day.

#### Scenario: A weekly chore

- **WHEN** a user sends `/push take the bins out every Monday` on Wednesday 4 November 2026
- **THEN** the card shows the start Monday 9 November 2026, with no time, repeating every week on Monday

#### Scenario: A reminder asked for

- **WHEN** a user sends `/push dentist Friday at 9, remind me an hour before` on Wednesday 4 November 2026
- **THEN** the card shows the start Friday 6 November 2026 at 09:00 and one reminder 1 hour before

#### Scenario: No reminder unless asked

- **WHEN** a user sends `/push dinner with Sam Friday at 7`
- **THEN** the card shows no reminder

### Requirement: Confirming stores the repeat and reminders

Confirming SHALL store the repeat and the reminders as the card shows them. A repeat or reminder the store refuses SHALL be shown on the card naming the date, keeping the user's input, and nothing SHALL be stored. Merging parts SHALL keep the first part's date with its repeat and reminders.

#### Scenario: Changed on the card

- **WHEN** a card shows a weekly repeat on Monday, the user adds Thursday and a reminder 1 day before, and confirms
- **THEN** the stored thought repeats every week on Monday and Thursday, with a reminder 1,440 minutes before

#### Scenario: Repeat cleared on the card

- **WHEN** a card shows a repeat, the user sets it to "Does not repeat", and confirms
- **THEN** the stored thought has the date and no repeat

#### Scenario: Merged

- **WHEN** a user merges two cards, the first repeating every week on Monday with a reminder, and confirms
- **THEN** the stored thought has the first card's date, repeat, and reminder
