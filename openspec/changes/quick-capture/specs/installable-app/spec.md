## Purpose

Makes the app installable on a phone and a share target in the phone's share sheet, so shared text lands in the quick capture box, without keeping any of the user's data in a browser cache.

## ADDED Requirements

### Requirement: The app has a web app manifest

The app SHALL serve a web app manifest that every page links to. It SHALL name the app "Focus Funnel", open `/app` when the installed app starts, cover the whole site, show as a standalone app, and list PNG icons of 192 and 512 pixels, one of them maskable. It SHALL offer a shortcut "Quick capture" that opens the Capture page.

#### Scenario: Manifest

- **WHEN** a browser reads the manifest a page links to
- **THEN** it names `Focus Funnel`, starts at `/app`, has the scope `/`, shows `standalone`, and lists a 192 and a 512 pixel PNG icon
- **AND** each listed icon loads as a PNG of the stated size

#### Scenario: Shortcut

- **WHEN** a user long-presses the installed app's icon and picks "Quick capture"
- **THEN** the Capture page opens

### Requirement: The app is a share target

The manifest SHALL declare a share target that opens `/share` with a `GET` request, passing the shared title, text, and link as the `title`, `text`, and `url` parameters. Opening `/share` SHALL store no capture, conversation, message, or thought on the server and call no model; in `demo` mode it may start a demo session, as any page does.

#### Scenario: Share target in the manifest

- **WHEN** a browser reads the manifest
- **THEN** its share target has the action `/share`, the method `GET`, and the parameters `title`, `text`, and `url`

#### Scenario: Sharing calls nothing

- **WHEN** a logged-in user opens `/share?text=buy%20oat%20milk`
- **THEN** no model is called, and no capture, conversation, message, or thought is stored


### Requirement: Shared text reaches the server only in the share request

Before the user presses "Make cards", the shared values SHALL reach the server only in the `/share` request itself. Every answer to that request SHALL be marked `Cache-Control: no-store` and `Referrer-Policy: no-referrer` in every auth mode, including a refusal for too many requests and the page shown when a demo session cannot start. The page SHALL remove the values from its address before anything else, and no later request SHALL carry them in its address or its `Referer`.

#### Scenario: No later request carries the text

- **WHEN** a user opens `/share?text=worth%20a%20read`
- **THEN** the `/share` answer is marked `no-store` and `no-referrer`
- **AND** no request that follows holds `worth` in its address or its `Referer`

#### Scenario: Demo session cannot start

- **WHEN** a browser with no demo session opens `/share?text=worth%20a%20read` in `demo` mode, and the session limit is reached or the session cannot start
- **THEN** the answer is marked `no-store` and `no-referrer`

### Requirement: Shared text opens in the capture box

Opening `/share` SHALL open the Capture page with the shared values in the box: title, text, and link, each on its own line, in that order, leaving out an empty value and a repeated one. A shared text of up to 10,000 characters, in any script, SHALL reach the box whole. The page SHALL make no cards until the user presses "Make cards". The shared text SHALL be used once: a reload of the Capture page after that SHALL show an empty box.

#### Scenario: Text and link

- **WHEN** a user shares a page titled `Sea charts` with the text `worth a read` and the link `https://example.com/charts`
- **THEN** the Capture page's box holds `Sea charts`, `worth a read`, and `https://example.com/charts` on three lines
- **AND** no cards are made until the user presses "Make cards"

#### Scenario: Long text in another script

- **WHEN** a logged-in user shares a text of 10,000 characters that mixes `é`, spaces, and new lines
- **THEN** the Capture page's box holds the whole text

#### Scenario: Used once

- **WHEN** a user opens a share, then reloads the Capture page
- **THEN** the box is empty

#### Scenario: Nothing shared

- **WHEN** `/share` is opened with no values, or only empty or whitespace ones
- **THEN** the Capture page opens with an empty box, and text kept earlier for the box is left as it was

### Requirement: A shared value is not repeated in the box

Going through the title, the text, and the link in that order, a shared value SHALL be left out of the box when it equals a value already kept, or when another shared value contains it and is longer. Of two equal values, the first SHALL be kept.

#### Scenario: Link already in the text

- **WHEN** a user shares the text `worth a read https://example.com/charts` with the link `https://example.com/charts`
- **THEN** the box holds `worth a read https://example.com/charts` once, with no second copy of the link

#### Scenario: Same title and text

- **WHEN** an app shares `buy oat milk` as both the title and the text
- **THEN** the box holds `buy oat milk` once

#### Scenario: Same text and link

- **WHEN** an app shares `https://a.b` as both the text and the link, with no title
- **THEN** the box holds `https://a.b` once

### Requirement: A share opened while logged out comes back after login

When `/share` is opened by a user who is not logged in, the system SHALL keep the shared text in that browser and send the user to log in. After the login, the user SHALL land on the Capture page with the shared text in the box. The shared text SHALL NOT be sent to the server before the user presses "Make cards", and SHALL NOT be put in the login address.

#### Scenario: Logged out share

- **WHEN** a logged-out user shares the text `buy oat milk` to the app and logs in
- **THEN** the Capture page opens with `buy oat milk` in the box

#### Scenario: Long shared text

- **WHEN** a logged-out user shares a text of 10,000 characters, with non-ASCII letters, spaces, and new lines, and logs in
- **THEN** the Capture page opens with the whole text in the box

#### Scenario: Not in the login address

- **WHEN** a logged-out user shares `buy oat milk`
- **THEN** the address the login starts from holds no part of `buy oat milk`

### Requirement: Text kept for the box stays with its user

Text the browser keeps for the capture box SHALL only fill the box of the user it was kept for. Text kept when a user's session ended SHALL NOT fill the box of a different user who logs in on that browser. Logging out, by any way the app offers, including the logout after deleting the account, or ending a demo session, SHALL remove the kept text. Text kept from a share while logged out SHALL go to the user who logs in next, within 30 minutes.

#### Scenario: Another user logs in

- **WHEN** user A's session ends while the box holds text, and user B logs in on that browser and opens the Capture page
- **THEN** user B's box is empty

#### Scenario: Log out

- **WHEN** a user logs out while text is kept for the box, and logs in again
- **THEN** the box is empty

#### Scenario: Account deleted

- **WHEN** a user deletes their account while text is kept for the box
- **THEN** the kept text is removed before the app logs out

### Requirement: Another site cannot make cards for the user

Opening `/share` or the Capture page from a link on another site SHALL NOT make cards, call a model, or store anything. A capture request sent from another site SHALL be refused and SHALL store nothing.

#### Scenario: Link from another site

- **WHEN** a logged-in user follows a link on another site to `/share?text=spend%20my%20key`
- **THEN** the Capture page shows the text in the box, and no model is called until the user presses "Make cards"

#### Scenario: Form from another site

- **WHEN** a page on another site submits a form that posts to the capture endpoint while the user is logged in
- **THEN** the request is refused, no model is called, and nothing is stored

### Requirement: The service worker caches nothing

The app SHALL register one service worker for the whole site. It SHALL NOT store any response, page, or API answer in a browser cache, and SHALL NOT answer any request itself: every request SHALL reach the server as it would without it. Using the app offline is not offered.

#### Scenario: Registered for the whole site

- **WHEN** a logged-in user opens the app
- **THEN** one service worker is registered, with the scope `/`

#### Scenario: Nothing cached

- **WHEN** a user opens a conversation, a thought, and the Capture page, and the browser's cache storage for the app is then read
- **THEN** it holds no entry

#### Scenario: Logged out after a visit

- **WHEN** a user logs out and opens `/app` again
- **THEN** the login is asked for, and no page of the earlier session is shown

### Requirement: The install files need no login

The manifest, the service worker script, and the icons SHALL load for a user who is not logged in, in every auth mode. `/share` SHALL open for a user who is logged in or not. In `demo` mode these files SHALL be marked `Cache-Control: no-store` and SHALL NOT start a demo session.

#### Scenario: Logged out in oidc mode

- **WHEN** a logged-out browser asks for the manifest, the service worker script, and an icon in `oidc` mode
- **THEN** each loads, with no redirect to the login

#### Scenario: Logged in share

- **WHEN** a logged-in user opens `/share?text=buy%20oat%20milk`
- **THEN** the Capture page opens with the text, and the user is not sent to `/app`

#### Scenario: Demo mode

- **WHEN** a browser with no demo session asks for the manifest in `demo` mode
- **THEN** the manifest loads with `Cache-Control: no-store`, and no demo session cookie is set
