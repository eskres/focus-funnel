## MODIFIED Requirements

### Requirement: Notifications are listed in the app

The app SHALL have a Notifications page, reached from a "Notifications" link in the sidebar. It SHALL list the user's notifications, newest first, at most 50, each with its title and text, and whether it was read: a reminder with the thought's title and when it starts, a weekly review with "Weekly review" and what the week holds, and a resurfaced idea with the idea's title and since when it was untouched. Clicking a reminder or a resurfaced idea SHALL open its thought in the side sheet over the page, with the page address naming it. Clicking a weekly review SHALL open its conversation. When a thought is changed or deleted in the side sheet opened over the page, the list SHALL follow once the change is saved or the sheet is closed: a resurfaced idea archived or marked done there SHALL say so with no buttons, and the notification of a thought deleted there SHALL leave the list. Following a change SHALL NOT mark more notifications read. When the list is loaded again more than once, an answer to an older load SHALL NOT replace a newer one. A load that fails SHALL keep the list shown and SHALL say what failed. Keeping an idea SHALL NOT load the list again. With none, the page SHALL say there are no notifications.

#### Scenario: A reminder in the list

- **WHEN** a reminder for `Dinner with Sam`, dated Friday 2 October at 19:00, came due an hour before
- **THEN** the Notifications page lists `Dinner with Sam` with `Fri 2 Oct, 19:00`

#### Scenario: Open the thought

- **WHEN** a user clicks a reminder or a resurfaced idea
- **THEN** the side sheet shows its thought, and the list is still visible behind it

#### Scenario: A weekly review in the list

- **WHEN** a weekly review for 1 to 8 November with 12 thoughts, 3 of them open tasks, was made
- **THEN** the Notifications page lists "Weekly review" with `1–8 Nov · 12 thoughts filed, 3 open tasks`
- **AND** clicking it opens the review conversation

#### Scenario: A resurfaced idea in the list

- **WHEN** the idea `Podcast about maps`, untouched since 3 September, was resurfaced
- **THEN** the Notifications page lists `Podcast about maps` with `Untouched since 3 Sep`, and Keep, Archive, and Delete

#### Scenario: Archived in the sheet over the list

- **WHEN** a user opens a resurfaced idea from its notification, archives it in the side sheet, and closes the sheet
- **THEN** the notification says the idea is archived, and offers no buttons

#### Scenario: Archived in the sheet, older answer last

- **WHEN** a user archives a resurfaced idea in the side sheet and closes the sheet while the change is still saving, and the list loaded on closing answers after the list loaded once the change was saved
- **THEN** the notification still says the idea is archived, and offers no buttons

#### Scenario: Reloading the list fails

- **WHEN** the list is loaded again after the sheet closes, and that load fails
- **THEN** the notifications shown before stay listed, and the page says what failed

#### Scenario: Deleted in the sheet

- **WHEN** a user opens a resurfaced idea from its notification and deletes it in the side sheet
- **THEN** its notification is no longer listed

#### Scenario: Nothing yet

- **WHEN** a user has no notifications
- **THEN** the page says there are no notifications

### Requirement: A notification is pushed to the user's browsers

With push on, each new reminder notification SHALL be pushed at most once to each of the user's subscriptions, within the per-run limits below, with the thought's title and when it starts. A weekly review and a resurfaced idea SHALL NOT be pushed; they SHALL be shown only in the app. A subscription the push service says no longer exists SHALL be deleted. A push that fails otherwise SHALL NOT be tried again, and the in-app notification SHALL stay; the log SHALL NOT hold the subscription's address or keys.

#### Scenario: Pushed

- **WHEN** a user with browser notifications on has a reminder come due while the app is closed
- **THEN** the browser shows a notification with the thought's title and when it starts

#### Scenario: Gone subscription

- **WHEN** a push service answers that a subscription no longer exists
- **THEN** that subscription is deleted, and the next notification is not sent to it

#### Scenario: Push service down

- **WHEN** a push service cannot be reached
- **THEN** the notification is still in the app's list, and the push is not sent again

#### Scenario: A weekly review is not pushed

- **WHEN** a user with browser notifications on gets a weekly review
- **THEN** the Notifications page lists it, and no browser notification is shown for it

#### Scenario: A resurfaced idea is not pushed

- **WHEN** a user with browser notifications on has an idea resurfaced
- **THEN** the Notifications page lists it, and no browser notification is shown for it
