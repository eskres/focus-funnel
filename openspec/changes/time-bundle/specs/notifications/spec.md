## Purpose

Shows a user the notifications the app has for them, such as reminders, in a list in the app with an unread count, and, when the operator turns web push on and the user allows it, as browser notifications.

## ADDED Requirements

### Requirement: Notifications are listed in the app

The app SHALL have a Notifications page, reached from a "Notifications" link in the sidebar. It SHALL list the user's notifications, newest first, at most 50, each with the thought's title and when it starts, and whether it was read. Clicking a notification SHALL open its thought in the side sheet over the page, with the page address naming it. Opening the page SHALL mark the listed notifications read. With none, the page SHALL say there are no notifications.

#### Scenario: A reminder in the list

- **WHEN** a reminder for `Dinner with Sam`, dated Friday 2 October at 19:00, came due an hour before
- **THEN** the Notifications page lists `Dinner with Sam` with `Fri 2 Oct, 19:00`

#### Scenario: Open the thought

- **WHEN** a user clicks a notification
- **THEN** the side sheet shows its thought, and the list is still visible behind it

#### Scenario: Nothing yet

- **WHEN** a user has no notifications
- **THEN** the page says there are no notifications

### Requirement: The sidebar shows the unread count

The "Notifications" link SHALL show how many notifications are unread when there are any, and its accessible name SHALL include that number. The count SHALL update within about a minute of a new notification while the app is open, and when the app's window gets focus. Opening the Notifications page SHALL clear the count.

#### Scenario: New reminder while the app is open

- **WHEN** a user has the app open and a reminder comes due
- **THEN** within about a minute the link shows 1, and a screen reader names it "Notifications, 1 unread"

#### Scenario: Read

- **WHEN** a user with 3 unread notifications opens the Notifications page
- **THEN** the link shows no count

### Requirement: Notifications are the owner's and are kept for 30 days

A user SHALL see and mark read only their own notifications. Marking another user's notification read SHALL change nothing and SHALL answer as for an unknown notification. Notifications older than 30 days SHALL be deleted.

#### Scenario: Two users

- **WHEN** two users each have a notification
- **THEN** each user's list holds only their own

#### Scenario: Another user's id

- **WHEN** a user marks read a notification id that belongs to another user
- **THEN** the other user's notification stays unread, and the answer is the same as for an unknown id

#### Scenario: Old notifications

- **WHEN** a notification was created 31 days ago
- **THEN** it is no longer listed

### Requirement: Web push is off unless the operator turns it on

Web push SHALL be off unless the operator sets both VAPID keys. With one key set and not the other, the backend SHALL refuse to start and SHALL name the missing setting. In demo mode the backend SHALL refuse to start while either key is set. With push off, the settings page SHALL NOT offer browser notifications, and storing a subscription SHALL be refused as not found.

#### Scenario: Not set

- **WHEN** neither VAPID key is set
- **THEN** the settings page offers no browser notifications, and reminders still appear in the app

#### Scenario: One key only

- **WHEN** the operator sets the public key and not the private key
- **THEN** the backend does not start, and its message names the private key setting

#### Scenario: Demo mode

- **WHEN** the backend starts in demo mode with a VAPID key set
- **THEN** it does not start, and its message says to remove the key

### Requirement: A user turns on browser notifications in settings

With push on, the settings page SHALL offer "Browser notifications" for the browser in use, showing whether it is on, off, blocked in the browser's settings, or not supported by the browser. Turning it on SHALL ask the browser for permission and store this browser's push subscription for the user. Turning it off SHALL remove it.

#### Scenario: Turn on

- **WHEN** a user turns on browser notifications and allows them in the browser
- **THEN** the section shows them as on in this browser

#### Scenario: Blocked

- **WHEN** a user has blocked notifications for the app in the browser
- **THEN** the section says they are blocked in the browser's settings, and does not store a subscription

#### Scenario: Turn off

- **WHEN** a user turns browser notifications off
- **THEN** no further notification is pushed to that browser

### Requirement: Push subscriptions are kept private

A user SHALL have at most 10 stored subscriptions; storing an eleventh SHALL replace the oldest. A stored subscription SHALL be kept encrypted and SHALL NOT be returned by any request. The browser SHALL hold no credential for push beyond its own push subscription.

#### Scenario: Eleventh browser

- **WHEN** a user with 10 stored subscriptions turns on browser notifications in another browser
- **THEN** that browser's subscription is stored and the oldest one is removed

#### Scenario: Not readable

- **WHEN** someone reads the stored subscriptions table
- **THEN** it holds no subscription address or key in plain text

### Requirement: A subscription is accepted only for a known push service

The backend SHALL refuse a subscription whose address is not `https` on a known browser push service, naming the endpoint, and SHALL store nothing. It SHALL NOT send any request to such an address.

#### Scenario: Internal address

- **WHEN** a request stores a subscription with the endpoint `http://db:5432/`
- **THEN** it is refused naming the endpoint, and nothing is stored

#### Scenario: Known service

- **WHEN** a browser stores a subscription with an endpoint on `fcm.googleapis.com`
- **THEN** it is stored

### Requirement: A notification is pushed to the user's browsers

With push on, each new notification SHALL also be pushed to each of the user's stored subscriptions, at most once, showing the thought's title and when it starts. Clicking the browser notification SHALL open the app on the Notifications page with the thought open. A subscription the push service says no longer exists SHALL be deleted. A push that fails otherwise SHALL NOT be tried again, and the in-app notification SHALL stay. The log SHALL NOT hold a subscription's address or keys.

#### Scenario: Pushed

- **WHEN** a user with browser notifications on has a reminder come due while the app is closed
- **THEN** the browser shows a notification with the thought's title and when it starts

#### Scenario: Click

- **WHEN** the user clicks that browser notification
- **THEN** the app opens on the Notifications page with the thought open in the side sheet

#### Scenario: Gone subscription

- **WHEN** a push service answers that a subscription no longer exists
- **THEN** that subscription is deleted, and the next notification is not sent to it

#### Scenario: Push service down

- **WHEN** a push service cannot be reached
- **THEN** the notification is still in the app's list, and the push is not sent again
