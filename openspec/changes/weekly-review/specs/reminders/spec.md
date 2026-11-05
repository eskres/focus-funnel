## MODIFIED Requirements

### Requirement: Done and deleted thoughts send no reminders

A thought that is done or archived, has no date, or whose repeat has ended SHALL send no reminders. A thought set back to open, from done or from archived, SHALL send reminders again from its next occurrence. A deleted thought SHALL send no reminders, and its notifications SHALL be deleted with it. A changed date or reminder SHALL take effect for the next reminder.

#### Scenario: Marked done before the reminder

- **WHEN** a task dated tomorrow at 10:00 has a reminder 60 minutes before, and the user marks it done today
- **THEN** no notification for it appears tomorrow

#### Scenario: Archived before the reminder

- **WHEN** a thought dated tomorrow at 10:00 has a reminder 60 minutes before, and the user archives it today
- **THEN** no notification for it appears tomorrow

#### Scenario: Restored

- **WHEN** a thought repeating every Monday at 10:00 with a reminder 60 minutes before was archived, and the user restores it on a Sunday
- **THEN** a notification for it appears at about 09:00 the next day

#### Scenario: Date moved

- **WHEN** a dinner at 19:00 has a reminder 60 minutes before, and the user moves it to 20:00 before 18:00
- **THEN** the notification appears at about 19:00, and not at 18:00

#### Scenario: Series ended

- **WHEN** a thought repeats every day with no time until 31 October 2026 and has a reminder 0 minutes before
- **THEN** a notification for it appears on 31 October, and none on 1 November or later

#### Scenario: Deleted

- **WHEN** a user deletes a thought that has reminders and notifications
- **THEN** no further notification appears for it, and its notifications are gone
