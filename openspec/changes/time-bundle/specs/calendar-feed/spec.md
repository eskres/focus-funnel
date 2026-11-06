## Purpose

Gives each user a private, revocable calendar feed address that a calendar app can subscribe to, listing their open dated thoughts and nothing else.

## ADDED Requirements

### Requirement: A user makes a private feed address in settings

The settings page SHALL have a "Calendar feed" section. A user SHALL be able to make a feed address, which SHALL hold a random token of at least 256 bits and end in `.ics`. The full address SHALL be shown once, right after it is made, with a way to copy it, and SHALL NOT be shown again. The token SHALL be stored only as a hash. A user SHALL have at most one feed address. The section SHALL show whether a feed is on and when it was made.

#### Scenario: Make a feed

- **WHEN** a user with no feed chooses to make a feed address
- **THEN** the section shows an address of the form `https://<app>/api/calendar/<token>.ics` with a copy button, and says it will not be shown again

#### Scenario: Come back later

- **WHEN** the user leaves the settings page and opens it again
- **THEN** the section says the feed is on and when it was made, and does not show the address

#### Scenario: Not stored

- **WHEN** a feed address has been made
- **THEN** the database holds no copy of its token, only a hash

### Requirement: The feed section says what the address shares

The "Calendar feed" section SHALL say, before a feed address is made and beside a made address, that anyone with the address can see the titles, summaries, and categories of the user's open dated thoughts, and that it can be regenerated if it is shared by mistake. The section SHALL offer the address in the scheme the app is served with, and SHALL NOT offer a `webcal://` link.

#### Scenario: Before and after making a feed

- **WHEN** a user with no feed opens the section, and then makes a feed address
- **THEN** both before and after, the section says that anyone with the address can see the titles, summaries, and categories of their open dated thoughts, and that it can be regenerated if shared by mistake

#### Scenario: No webcal link

- **WHEN** a user on an instance served over `https` makes a feed address
- **THEN** the section offers the `https://` address to copy, and no `webcal://` link

### Requirement: A feed address can be replaced or turned off

The user SHALL be able to regenerate the feed address and to turn the feed off, each after a confirmation that says the old address will stop working. Regenerating SHALL make a new address and the old one SHALL stop working at once. Turning the feed off SHALL make the address stop working at once.

#### Scenario: Regenerate

- **WHEN** a user regenerates their feed address
- **THEN** the new address answers with the feed, and the old address answers as an unknown address

#### Scenario: Turn off

- **WHEN** a user turns their feed off
- **THEN** the address answers as an unknown address, and the section offers to make a new one

### Requirement: The feed holds the user's open dated thoughts

A request for a feed address SHALL answer an iCalendar file. It SHALL hold only the address owner's thoughts that are open and dated, at most 2,000: a thought that does not repeat when its date ended no more than 30 days ago, and a repeating thought when it has no last day or its last day was no more than 30 days ago, however long ago it started. A done thought and a thought with no date SHALL NOT be in it.

#### Scenario: Done and undated left out

- **WHEN** a user has an undated idea, a done task dated tomorrow, and an open task dated tomorrow
- **THEN** the feed has only the open task

#### Scenario: Long past

- **WHEN** a user has an open thought dated 60 days ago
- **THEN** the feed does not have it

#### Scenario: Still repeating

- **WHEN** a user has an open thought repeating every week from 60 days ago, with no last day
- **THEN** the feed has it, with its repeat rule

#### Scenario: Repeat ended long ago

- **WHEN** a user has an open thought that repeated every week until 60 days ago
- **THEN** the feed does not have it

### Requirement: A feed event carries the date and nothing private

Each thought in the feed SHALL be one event with the thought's title, summary, and category. A date with no time SHALL be an all-day event over its days. A date with a time SHALL keep its local time in the thought's time zone. A repeating thought SHALL be one event with a repeat rule that gives the same occurrences the app shows. The feed SHALL NOT hold raw text, tags, reminders, the user's id or email, provider keys, or any token.

#### Scenario: An evening event

- **WHEN** a user has an open thought `Dinner with Sam` dated Friday 2 October 2026 at 19:00 in `Europe/Oslo`
- **THEN** the feed has an event `Dinner with Sam` starting at 19:00 Oslo time on 2 October

#### Scenario: A trip over several days

- **WHEN** a user has an open thought dated 3 to 6 November with no times
- **THEN** the feed has an all-day event over 3, 4, 5, and 6 November

#### Scenario: Every Monday

- **WHEN** a user has an open thought that repeats every week on Monday from 9 November 2026
- **THEN** the feed has one event starting 9 November that repeats weekly on Monday

#### Scenario: What is left out of an event

- **WHEN** a user has an open task dated tomorrow with tags, raw text, and a reminder
- **THEN** its event has the title, summary, and category, and no tags, raw text, or alarm

### Requirement: The feed needs no login and is owner-scoped by its token

A feed request SHALL NOT need a login or a session; its token SHALL be its only credential. It SHALL show only the thoughts of the user who made the token. An unknown, revoked, or malformed token SHALL get HTTP 404 with error code `not_found` and the same body as any unknown address.

#### Scenario: From a calendar app

- **WHEN** a calendar app with no cookies fetches a user's feed address
- **THEN** it gets that user's feed

#### Scenario: Unknown token

- **WHEN** a request asks for `/api/calendar/<a token nobody has>.ics`
- **THEN** the answer is 404 with error code `not_found`, the same as for an unknown address

#### Scenario: Two users

- **WHEN** two users each have a feed and a dated thought
- **THEN** each feed holds only its own user's thought

### Requirement: The app's server forwards the feed request without a login

The app's server SHALL forward only the feed request to the backend without a credential, and SHALL NOT send any cookie or login token with it. When the backend cannot be reached, or answers with a redirect, the app's server SHALL answer HTTP 502 with error code `backend_unreachable` and SHALL NOT pass on the redirect.

#### Scenario: Cookies not forwarded

- **WHEN** a browser with a session cookie fetches a feed address
- **THEN** the request the backend gets carries no cookie and no login token

#### Scenario: Backend down

- **WHEN** a calendar app fetches a feed address while the backend cannot be reached
- **THEN** the answer is 502 with error code `backend_unreachable`

### Requirement: The feed follows the email allow-list

When the operator has set an email allow-list, a feed SHALL answer only while the verified email address of the user who made it is on the list. A feed whose owner the list does not let in SHALL answer HTTP 404 with error code `not_found` and the same body as any unknown address. The feed SHALL NOT hold that address.

#### Scenario: Removed from the list

- **WHEN** a user with a feed address is removed from the allow-list and the server is restarted
- **THEN** their feed address answers as an unknown address

#### Scenario: Still on the list

- **WHEN** a user whose address is on the allow-list fetches their feed address
- **THEN** it answers with their feed

### Requirement: Feed requests are limited and stay out of the log

Each feed address SHALL answer at most 60 requests an hour; requests with tokens that are not known SHALL together get at most 120 an hour. Over a limit, a request SHALL get HTTP 429 with error code `rate_limited` and a `Retry-After` header. The token SHALL NOT be written to the backend's access log or to any other log.

#### Scenario: Too many requests

- **WHEN** a feed address is fetched for the 61st time within an hour
- **THEN** the answer is 429 with error code `rate_limited` and a `Retry-After` header

#### Scenario: Access log

- **WHEN** a calendar app fetches a feed address
- **THEN** the backend's access log line names `/api/calendar/[REDACTED].ics` and does not hold the token

### Requirement: Demo mode has no calendar feed

In demo mode the settings page SHALL NOT show the "Calendar feed" section, and every feed request and feed setting request SHALL answer HTTP 404 with error code `not_found`.

#### Scenario: Demo visitor

- **WHEN** a demo visitor opens the settings page
- **THEN** there is no "Calendar feed" section

#### Scenario: Feed request in demo mode

- **WHEN** a request asks for any `/api/calendar/<token>.ics` on a demo instance
- **THEN** the answer is 404 with error code `not_found`
