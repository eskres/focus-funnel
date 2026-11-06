## Purpose

Reminds a user of a dated thought a set time before it starts, once per reminder and occurrence, through the in-app notification list and, when the operator turns it on, web push.

## ADDED Requirements

### Requirement: A reminder is due a set time before the thought starts

A reminder SHALL be due its number of minutes before the start of the thought's date, read as the local time in the thought's time zone. A date with no time SHALL count as starting at 09:00 on its day. A repeating thought's reminder SHALL be due before each occurrence. A due reminder SHALL create an in-app notification that names the thought and when it starts, within one minute of being due.

#### Scenario: An hour before

- **WHEN** a thought dated Friday 2 October 2026 at 19:00 in `Europe/Oslo` has a reminder 60 minutes before
- **THEN** a notification for it appears at about 18:00 Oslo time on 2 October

#### Scenario: A day with no time

- **WHEN** a thought dated Monday 9 November 2026 with no time in `Europe/Oslo` has a reminder 0 minutes before
- **THEN** a notification for it appears at about 09:00 Oslo time on 9 November

#### Scenario: Each occurrence

- **WHEN** a thought repeats every week on Monday from 9 November 2026 with no time and has a reminder 1,440 minutes before
- **THEN** a notification for it appears on Sunday 8 November at about 09:00, and again on Sunday 15 November

#### Scenario: Confirmed with a reminder

- **WHEN** a user confirms a proposal dated Friday 6 November 2026 at 09:00 in `Europe/Oslo` with a reminder 60 minutes before
- **THEN** a notification for it appears at about 08:00 Oslo time on 6 November

#### Scenario: Already past when set

- **WHEN** at 18:00 a user sets a reminder 1 day before a dinner dated today at 19:00
- **THEN** no notification is created for that dinner

### Requirement: A reminder is delivered once

Each reminder SHALL create at most one notification per occurrence, however often the backend restarts or stops while it is sending reminders. A reminder that has come due and not yet been sent SHALL still be sent once when the thought's reminders are changed before it is sent, as long as its occurrence is unchanged.

#### Scenario: Restart in the middle of sending

- **WHEN** the backend is killed while it sends the reminders due at 18:00, and starts again at 18:01
- **THEN** each of those reminders has exactly one notification

#### Scenario: Reminder added while one is due

- **WHEN** a reminder came due at 18:00:00, and at 18:00:10, before it was sent, the user adds a second reminder to the same thought
- **THEN** exactly one notification for the 18:00 reminder appears

### Requirement: Deleting while reminders are sent succeeds

Deleting a thought, the user's content, the account, or an expired demo session while its reminders are being sent SHALL succeed, and SHALL leave no notification for what was deleted.

#### Scenario: Deleted while sending

- **WHEN** a user deletes a thought while the backend is sending its due reminder
- **THEN** the delete succeeds, and no notification for that thought is left

#### Scenario: Account deleted while sending

- **WHEN** a user deletes their account while the backend is sending one of their due reminders
- **THEN** the delete succeeds, and no notification or reminder of that user is left

#### Scenario: Demo session expires while sending

- **WHEN** the demo cleanup deletes an expired demo visitor while the backend is sending one of their due reminders
- **THEN** the visitor is deleted, and no notification or reminder of theirs is left

### Requirement: Missed reminders are caught up with a limit

After the backend was down, a reminder that came due while it was down SHALL create one notification, for its latest missed occurrence, when that occurrence came due at most 24 hours ago. A reminder that came due more than 24 hours ago SHALL create no notification. After catching up, each reminder SHALL be due again at its next occurrence.

#### Scenario: Down for two hours

- **WHEN** a reminder came due at 18:00 and the backend was down from 17:30 until 19:30
- **THEN** at 19:30 one notification for it appears

#### Scenario: A repeating reminder down for three days

- **WHEN** a daily thought's reminder came due on each of the last three days while the backend was down
- **THEN** one notification appears, for the latest of the three
- **AND** the reminder is due again at the next day's occurrence

#### Scenario: Down for two days

- **WHEN** a thought dated two days ago had a reminder, and the backend was down from before it came due until now
- **THEN** no notification appears for it

### Requirement: Done and deleted thoughts send no reminders

A thought that is done, has no date, or whose repeat has ended SHALL send no reminders. A thought set back to open SHALL send reminders again from its next occurrence. A deleted thought SHALL send no reminders, and its notifications SHALL be deleted with it. A changed date or reminder SHALL take effect for the next reminder.

#### Scenario: Marked done before the reminder

- **WHEN** a task dated tomorrow at 10:00 has a reminder 60 minutes before, and the user marks it done today
- **THEN** no notification for it appears tomorrow

#### Scenario: Date moved

- **WHEN** a dinner at 19:00 has a reminder 60 minutes before, and the user moves it to 20:00 before 18:00
- **THEN** the notification appears at about 19:00, and not at 18:00

#### Scenario: Series ended

- **WHEN** a thought repeats every day with no time until 31 October 2026 and has a reminder 0 minutes before
- **THEN** a notification for it appears on 31 October, and none on 1 November or later

#### Scenario: Deleted

- **WHEN** a user deletes a thought that has reminders and notifications
- **THEN** no further notification appears for it, and its notifications are gone

### Requirement: Reminders belong to the thought's owner

A reminder's notification SHALL go only to the user who owns the thought.

#### Scenario: Two users

- **WHEN** two users each have a thought with a reminder due at 18:00
- **THEN** each user sees only the notification for their own thought
