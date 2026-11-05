## Purpose

Shows a user the notifications the app has for them, such as reminders, in a list in the app with an unread count, and, when the operator turns web push on and the user allows it, as browser notifications.

## ADDED Requirements

### Requirement: Notifications are listed in the app

The app SHALL have a Notifications page, reached from a "Notifications" link in the sidebar. It SHALL list the user's notifications, newest first, at most 50, each with the thought's title and when it starts, and whether it was read. Clicking a notification SHALL open its thought in the side sheet over the page, with the page address naming it. With none, the page SHALL say there are no notifications.

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

The "Notifications" link SHALL show how many notifications are unread when there are any, and its accessible name SHALL include that number. Outside demo mode, the count SHALL update within about a minute of a new notification while the app is open. It SHALL update when the app's window gets focus. Opening the Notifications page SHALL mark read the listed notifications and every older one, including those beyond the first 50, and SHALL so clear the count.

#### Scenario: New reminder while the app is open

- **WHEN** a user has the app open and a reminder comes due
- **THEN** within about a minute the link shows 1, and a screen reader names it "Notifications, 1 unread"

#### Scenario: Read

- **WHEN** a user with 3 unread notifications opens the Notifications page
- **THEN** the link shows no count

#### Scenario: More than the page shows

- **WHEN** a user with 60 unread notifications opens the Notifications page, which lists 50
- **THEN** the link shows no count, and none of the 60 is unread

### Requirement: The unread count survives a failed load and spares the demo limit

When the count cannot be loaded, the link SHALL keep the last count, SHALL show no error, and SHALL try again later. In demo mode, the count SHALL NOT be loaded on a timer; it SHALL be loaded when the app's window gets focus and on each move to another page of the app.

#### Scenario: Count not loaded

- **WHEN** loading the count fails because the server is busy or cannot be reached, and the link shows 2
- **THEN** the link still shows 2 with no error, and the next load updates it

#### Scenario: Demo visitor with the app open

- **WHEN** a demo visitor leaves the app open and idle
- **THEN** the app does not ask for the count on a timer, and asks again when the visitor returns to the window or moves to another page

### Requirement: Notifications are the owner's and are kept for 30 days

A user SHALL see and mark read only their own notifications. Marking notifications read SHALL change nothing of another user's. Notifications older than 30 days SHALL be deleted.

#### Scenario: Two users

- **WHEN** two users each have a notification
- **THEN** each user's list holds only their own

#### Scenario: Another user's notifications

- **WHEN** two users each have an unread notification, and one of them opens the Notifications page
- **THEN** the other user's notification stays unread

#### Scenario: Old notifications

- **WHEN** a notification was created 31 days ago
- **THEN** it is no longer listed

### Requirement: Web push is off unless the operator turns it on

Web push SHALL be off unless the operator sets both VAPID keys. With one key set and not the other, the backend SHALL refuse to start and SHALL name the missing setting. In demo mode the backend SHALL refuse to start while either key is set. No message, log line, or check output SHALL hold any part of the private key. With push off, the settings page SHALL NOT offer browser notifications, and storing a subscription SHALL be refused as not found.

#### Scenario: Not set

- **WHEN** neither VAPID key is set
- **THEN** the settings page offers no browser notifications, and reminders still appear in the app

#### Scenario: One key only

- **WHEN** the operator sets the public key and not the private key
- **THEN** the backend does not start, and its message names the private key setting

#### Scenario: Private key only

- **WHEN** the operator sets the private key and not the public key
- **THEN** the backend does not start, its message names the public key setting, and it holds no part of the private key

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

A user SHALL have at most 10 stored subscriptions; storing an eleventh SHALL replace the oldest. A stored subscription SHALL NOT be returned by any request, and its address and keys SHALL NOT be written to the log. The browser SHALL hold no credential for push beyond its own push subscription.

#### Scenario: Eleventh browser

- **WHEN** a user with 10 stored subscriptions turns on browser notifications in another browser
- **THEN** that browser's subscription is stored and the oldest one is removed

#### Scenario: Never answered

- **WHEN** a user with browser notifications on asks for the push settings
- **THEN** the answer says whether push is on and gives the public key, and holds no subscription address or key

### Requirement: A browser's subscription belongs to one user

A browser's subscription SHALL belong to at most one user, the last one who turned browser notifications on in it, and no answer SHALL show whether another user held it. A user SHALL be able to remove only their own subscriptions. Signing out SHALL remove the browser's subscription.

#### Scenario: Same browser, another user

- **WHEN** user A turned on browser notifications in a browser, A's session there ended without signing out, and user B signs in and turns them on in the same browser
- **THEN** the subscription is B's, and A's next reminder is not pushed to that browser
- **AND** the answer to B is the same as for a new browser

#### Scenario: Another user's subscription removed

- **WHEN** user B asks to remove a subscription that only user A holds
- **THEN** A's subscription stays, and the answer is the same as for an unknown one

#### Scenario: Signed out

- **WHEN** a user with browser notifications on signs out in that browser
- **THEN** no further notification of theirs is pushed to it

### Requirement: Only turning notifications on moves a subscription

Only turning browser notifications on SHALL move a subscription from one user to another; loading a page, the settings page included, SHALL NOT. The settings page SHALL show browser notifications as on only for the user who turned them on in that browser.

#### Scenario: A's subscription stays A's when B opens Settings

- **WHEN** user A turned on browser notifications in a browser, A's session there ended without signing out, and user B signs in on that browser and opens the settings page without turning them on
- **THEN** the subscription is still A's, and A's next reminder is pushed to that browser
- **AND** the settings page shows browser notifications as off for B

### Requirement: A renewed subscription is restored when the app loads

When the browser holds a subscription that the signed-in user turned on, made with the instance's current push key, and the server no longer has it, because the browser renewed it or the server removed it, the app SHALL store it again for that user the next time the app loads, without the user opening the settings page. This SHALL NOT move a subscription another user holds.

#### Scenario: Renewed by the browser

- **WHEN** a user with browser notifications on has a browser that replaced its subscription with a new one, and the user opens the app
- **THEN** the new subscription is stored for that user, and their next reminder is pushed to it

### Requirement: Subscriptions follow the instance's push key

Each stored subscription SHALL be tied to the push key it was made with. When the operator changes the push keys, no push SHALL be sent to a subscription made with the old key, and it SHALL be removed. The settings page SHALL show browser notifications as off in a browser whose subscription was made with another key, and SHALL NOT store that subscription again; turning them on SHALL make a new subscription with the current key.

#### Scenario: Push keys changed

- **WHEN** a user turned on browser notifications, the operator then sets new push keys and restarts, and one of the user's reminders comes due
- **THEN** no push is sent to that browser's old subscription, and it is removed
- **AND** the settings page in that browser shows browser notifications as off, until the user turns them on again

### Requirement: A subscription is accepted only for a known push service

The backend SHALL refuse a subscription whose address is not `https` on a known browser push service, or is longer than 2,048 characters, naming the endpoint, and SHALL store nothing. An address with user info, a port other than 443, or an IP address as its host, or whose host only starts with or contains a known service's name, SHALL be refused. It SHALL NOT send any request to such an address, and SHALL NOT follow a redirect from a push service.

#### Scenario: Internal address

- **WHEN** a request stores a subscription with the endpoint `http://db:5432/`
- **THEN** it is refused naming the endpoint, and nothing is stored

#### Scenario: Look-alike address

- **WHEN** a request stores a subscription with the endpoint `https://fcm.googleapis.com.evil.example/x`, `https://fcm.googleapis.com@10.0.0.5/x`, `https://fcm.googleapis.com:8443/x`, or `https://[::1]/x`
- **THEN** it is refused naming the endpoint, and nothing is stored

#### Scenario: Address too long

- **WHEN** a request stores a subscription whose endpoint is 10,000 characters long
- **THEN** it is refused naming the endpoint, and nothing is stored

#### Scenario: Known service

- **WHEN** a browser stores a subscription with an endpoint on `fcm.googleapis.com`
- **THEN** it is stored

### Requirement: A subscription's keys are checked

The backend SHALL refuse a subscription whose keys are missing or cannot be browser push keys, naming the key, and SHALL store nothing. It SHALL store only the subscription's address and keys.

#### Scenario: Keys not valid

- **WHEN** a request stores a subscription on `fcm.googleapis.com` with no keys, with an empty `auth` key, or with a `p256dh` key of the wrong length
- **THEN** it is refused naming the key, and nothing is stored

### Requirement: A notification is pushed to the user's browsers

With push on, each new notification SHALL be pushed at most once to each of the user's subscriptions, within the per-run limits below, with the thought's title and when it starts. A subscription the push service says no longer exists SHALL be deleted. A push that fails otherwise SHALL NOT be tried again, and the in-app notification SHALL stay; the log SHALL NOT hold the subscription's address or keys.

#### Scenario: Pushed

- **WHEN** a user with browser notifications on has a reminder come due while the app is closed
- **THEN** the browser shows a notification with the thought's title and when it starts

#### Scenario: Gone subscription

- **WHEN** a push service answers that a subscription no longer exists
- **THEN** that subscription is deleted, and the next notification is not sent to it

#### Scenario: Push service down

- **WHEN** a push service cannot be reached
- **THEN** the notification is still in the app's list, and the push is not sent again

### Requirement: Clicking a browser notification opens its thought

Clicking a browser notification SHALL open the Notifications page with the thought open in the side sheet, in an open tab of the app when there is one, including the tab where browser notifications were turned on, else in a new one. When the open tab cannot be moved to that page, a new one SHALL be opened. A click SHALL open only a page of the app under `/app/`; an address in a push that is on another site or outside `/app/` SHALL open the Notifications page instead.

#### Scenario: Click

- **WHEN** the user clicks that browser notification while no tab of the app is open
- **THEN** the app opens on the Notifications page with the thought open in the side sheet

#### Scenario: Click with the app open

- **WHEN** the user clicks that browser notification while a tab of the app shows another page
- **THEN** that tab comes to the front on the Notifications page with the thought open in the side sheet

#### Scenario: Click in the tab where notifications were turned on

- **WHEN** the user turned on browser notifications in a tab, moved in that tab to the Upcoming page without reloading it, and clicks a browser notification
- **THEN** a tab of the app shows the Notifications page with the thought open in the side sheet

#### Scenario: Address from elsewhere

- **WHEN** a push names the address `https://evil.example/` and the user clicks its notification
- **THEN** the app's Notifications page opens, and nothing from `evil.example` is loaded

### Requirement: Pushes are shared fairly

In one run of the reminder job, at most 5 of a user's new notifications SHALL be pushed, each to every one of the user's subscriptions, so a user with several browsers gets the same pushes on each. When the user has more, each subscription SHALL get one more push that says how many more reminders there are, and every notification SHALL still be in the app's list. Every user's first notification SHALL be sent before any user's second.

#### Scenario: Many reminders at once

- **WHEN** one user has 300 reminders due at 18:00 and another user has one
- **THEN** the second user gets their push, the first user gets at most 5 pushes and one saying how many more, and both lists hold every reminder

#### Scenario: Several browsers

- **WHEN** a user with browser notifications on in 10 browsers has 8 reminders due at 18:00
- **THEN** each of the 10 browsers gets the same 5 pushes and one saying there are 3 more reminders

### Requirement: Pushes follow the allow-list

When the operator has set an email allow-list, nothing SHALL be pushed to a user the list does not let in.

#### Scenario: Removed from the allow-list

- **WHEN** a user with browser notifications on is removed from the allow-list and the server is restarted, and one of their reminders comes due
- **THEN** nothing is pushed to their browsers

### Requirement: Pushes not sent in time are dropped

Each run of the reminder job SHALL have a time budget for its pushes. Pushes not sent within it SHALL be dropped and SHALL NOT be tried again, and their notifications SHALL stay in the app's list.

#### Scenario: Push services too slow for the run

- **WHEN** the push services answer so slowly that the run's time budget for pushes is spent before every push is sent
- **THEN** the pushes not sent are dropped and are not sent on a later run, and every notification is still in the app's list
