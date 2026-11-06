## Purpose

Brings back, now and then, ideas a user has left untouched for a long time, and lets them keep, archive, or delete each one, so old ideas are either picked up again or put away by the user's own choice.

## ADDED Requirements

### Requirement: An untouched idea

An idea SHALL count as untouched when it is an open thought with the category `idea` and, for 30 days, it was not filed, changed, added to, given a status, opened in the side sheet, kept, or resurfaced. A thought of another category, or one that is done or archived, SHALL NOT be resurfaced.

#### Scenario: Old idea

- **WHEN** a user filed the open idea `Podcast about maps` 40 days ago and has not touched it since
- **THEN** it is untouched

#### Scenario: Added to last week

- **WHEN** the same idea had an addition confirmed 7 days ago
- **THEN** it is not untouched

#### Scenario: Opened last week

- **WHEN** the user opened the same idea in the side sheet 7 days ago
- **THEN** it is not untouched

#### Scenario: Other categories and statuses

- **WHEN** a user has a task, an archived idea, and a done idea, each untouched for 40 days
- **THEN** none of them is resurfaced

### Requirement: Untouched ideas come back once a week, three at most

Once a week, at the user's weekly review weekday and hour, the system SHALL resurface up to 3 of the user's untouched ideas, the longest untouched first, each as an in-app notification. Changing the setting SHALL NOT bring resurfacing sooner than 6 days after the last weekly time, and saving it while a weekly time is due and not yet handled SHALL NOT skip that week's resurfacing. It SHALL NOT be sent as a browser notification and SHALL make no model or embedding call.

#### Scenario: Five untouched ideas

- **WHEN** a user has five untouched ideas at their weekly time
- **THEN** three notifications appear, for the three untouched longest

#### Scenario: Not again next week

- **WHEN** an idea was resurfaced and the user did nothing with it
- **THEN** it is not resurfaced again for 30 days

#### Scenario: Changed after this week's resurfacing

- **WHEN** three ideas were resurfaced at a user's Sunday 18:00, and at 19:00 that Sunday the user changes the hour to 20:00
- **THEN** no more ideas are resurfaced that day, and the next ones come the following Sunday at 20:00

### Requirement: Resurfacing uses only the user's own ideas

The system SHALL resurface only the user's own ideas, and only to that user, also when several users' weekly times are handled at the same time. A user with no resurfacing setting SHALL get no resurfaced notification, whatever other users have on.

#### Scenario: Two users due together

- **WHEN** two users with the review and resurfacing on are due at the same time, and each filed thoughts that week and has an untouched idea
- **THEN** each user's resurfaced notifications name only their own ideas
- **AND** each user's review lists and counts only their own thoughts

#### Scenario: Only one user has the setting

- **WHEN** one user has resurfacing on and is due, and another user with no setting has an idea untouched for 40 days
- **THEN** no notification names the second user's idea, and the second user gets none

### Requirement: Resurfacing is a setting, off by default

Resurfacing SHALL be off by default and SHALL be turned on in the weekly review settings, with its own switch beside the review's, and SHALL work with the review on or off.

#### Scenario: Off by default

- **WHEN** a user who never saved the weekly review setting has an untouched idea
- **THEN** no idea is resurfaced for them

#### Scenario: Turned off

- **WHEN** a user turns resurfacing off
- **THEN** no idea is resurfaced for them

#### Scenario: Review off, resurfacing on

- **WHEN** a user turns resurfacing on and leaves the weekly review off, for Sunday at 18:00, and has an untouched idea
- **THEN** the idea is resurfaced on Sunday at about 18:00, and no review conversation is made

### Requirement: A resurfaced idea is only proposed

Resurfacing SHALL NOT change, archive, or delete any thought, and SHALL store nothing on it. A resurfaced idea's notification SHALL show the idea's current title and since when it was untouched, with the year when that day is not in the year it was resurfaced, and SHALL offer Keep, Archive, and Delete while the idea is open; for a done or archived idea it SHALL say which, with no buttons. Only the user's click SHALL change the idea.

#### Scenario: Shown

- **WHEN** the idea `Podcast about maps`, untouched since 3 September, is resurfaced
- **THEN** the Notifications page lists it with "Untouched since 3 Sep" and Keep, Archive, and Delete
- **AND** the idea is still open and unchanged

#### Scenario: Untouched since last year

- **WHEN** the idea `Podcast about maps`, last touched on 3 September 2025, is resurfaced in November 2026
- **THEN** the Notifications page lists it with `Untouched since 3 Sep 2025`

#### Scenario: Already archived

- **WHEN** a resurfaced idea was archived in the side sheet before the user opened the Notifications page
- **THEN** its notification says it is archived, and offers no buttons

#### Scenario: Already done

- **WHEN** a resurfaced idea was marked done in the side sheet before the user opened the Notifications page
- **THEN** its notification says it is done, and offers no buttons

#### Scenario: Renamed after it was resurfaced

- **WHEN** a user renames a resurfaced idea in the side sheet
- **THEN** the Notifications page lists it under its new title

### Requirement: Keep resets the clock

Keep SHALL count as touching the idea, so it is not untouched again for 30 days. It SHALL change nothing else of the thought, including its "changed" date, and SHALL make no embedding call.

#### Scenario: Kept

- **WHEN** a user clicks Keep on a resurfaced idea
- **THEN** the notification says it is kept, and still says so once the request has finished, with no reload of the list
- **AND** the idea is still open with the same "changed" date, and it is not resurfaced for 30 days

### Requirement: Archive and Delete from a resurfaced idea

Archive SHALL set the idea's status to `archived`. Delete SHALL first ask for confirmation naming the idea, and SHALL then delete it as the side sheet's Delete does. A failed action SHALL show the reason and keep the buttons, except when the idea no longer exists: the notification SHALL then leave the list, with no error shown.

#### Scenario: Archived

- **WHEN** a user clicks Archive on a resurfaced idea
- **THEN** the idea is archived, and the notification says so

#### Scenario: Delete confirmed

- **WHEN** a user clicks Delete on a resurfaced idea and confirms
- **THEN** the idea is deleted, its notification is gone, and search no longer finds it
- **AND** an earlier review conversation that listed the idea may still name it, as a chat keeps what it showed, until that conversation is deleted

#### Scenario: Deleted elsewhere

- **WHEN** a resurfaced idea was deleted in another tab after the Notifications page loaded, and the user clicks Keep, Archive, or Delete on it
- **THEN** its notification leaves the list, no error is shown, and no buttons are left for it

#### Scenario: Delete cancelled

- **WHEN** a user clicks Delete on a resurfaced idea and cancels
- **THEN** the idea and its notification are as before

### Requirement: Keep is owner-scoped

Keeping another user's thought, or one that does not exist, SHALL answer 404 `not_found` with the same body, and SHALL change nothing.

#### Scenario: Another user's idea

- **WHEN** a user sends Keep for another user's idea
- **THEN** the answer is 404 `not_found`, with the body an unknown id gets, and the other user's idea is unchanged

### Requirement: Demo mode has no resurfacing

In demo mode, no idea SHALL be resurfaced.

#### Scenario: Demo visitor

- **WHEN** a demo visitor has an idea untouched for 30 days
- **THEN** it is not resurfaced
