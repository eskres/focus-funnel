## Purpose

Lets a user download all their thoughts, with their dates, status, origin, and additions, as one JSON or Markdown file, streamed so that a large store never has to be held in memory at once.

## ADDED Requirements

### Requirement: A user can export all their thoughts

A logged-in user SHALL be able to download every thought they own in one file, as JSON or as Markdown. Each thought SHALL carry its id, title, summary, raw text, tags, category, status and the time of its last status change, date, the times it was filed and last changed, its origin, and its additions. A thought with no origin, date, raw text, or additions SHALL still be exported. Exporting SHALL change nothing.

#### Scenario: Everything a thought has

- **WHEN** a user has a done `task` titled `Call the plumber`, dated `2026-11-09` in `Europe/Oslo`, saved from the conversation `Weekend plans` and added to once from the conversation `Plumber chat`, and exports as JSON
- **THEN** the file holds that thought with its title, summary, raw text, tags, the category `task`, the status `done` with the time it was marked done, the date `2026-11-09` in `Europe/Oslo`, and its filed and changed times
- **AND** its origin names `Weekend plans`, the proposal, and when it was proposed
- **AND** it lists one addition that names `Plumber chat`

#### Scenario: The same thought in Markdown

- **WHEN** the same user exports as Markdown
- **THEN** the thought's section shows the same title, status, category, tags, date, times, origin, summary, raw text, and addition

#### Scenario: A plain thought

- **WHEN** a thought was stored with no origin, no date, no raw text, and no additions, and the user exports
- **THEN** the file holds that thought with its title, summary, and the status `open`, and with no origin, date, raw text, or additions

#### Scenario: No thoughts

- **WHEN** a user with no thoughts exports as JSON or as Markdown
- **THEN** the file is complete and says there are no thoughts

#### Scenario: Nothing changes

- **WHEN** a user exports
- **THEN** every thought's changed time is as before, and no usage record is added

### Requirement: Only the user's own thoughts are exported

The export SHALL hold only the thoughts of the user who asks. An origin or an addition SHALL name only that user's own conversations. A thought whose source conversation was deleted SHALL be exported with no origin. An addition whose conversation was deleted SHALL NOT be listed.

#### Scenario: Another user's thoughts

- **WHEN** two users each have thoughts and one of them exports
- **THEN** the file holds none of the other user's thoughts and names none of the other user's conversations

#### Scenario: Source conversation deleted

- **WHEN** a user deletes the conversation a thought was saved from and then exports
- **THEN** the thought is in the file with all its content and no origin

#### Scenario: Addition's conversation deleted

- **WHEN** a thought has additions from two conversations and the user deletes one of those conversations and then exports
- **THEN** the file lists only the addition from the other conversation
- **AND** the thought keeps its raw text, including what the deleted conversation added

### Requirement: The export holds no search data and makes no model call

The export SHALL NOT contain embeddings or any other search index data. It SHALL make no embedding call and no chat model call, and SHALL work for a user with no provider key and when the provider cannot be reached. It SHALL NOT contain conversations or messages; a thought names its conversations only by id and title.

#### Scenario: No key

- **WHEN** a user with stored thoughts and no provider key exports
- **THEN** the file holds all their thoughts and no provider is called

#### Scenario: No vectors

- **WHEN** a user whose thoughts have embeddings exports
- **THEN** the file holds no vector values and nothing from the search index

#### Scenario: No messages

- **WHEN** a thought was saved from a conversation whose assistant reply and proposal hold a sentence that is not in the thought, and the user exports as JSON and as Markdown
- **THEN** neither file contains that sentence

### Requirement: The JSON export

The JSON file SHALL be one JSON document with the format name `focus-funnel-thoughts`, the version `1`, the time the export started, the list of thoughts, and, last, the number of thoughts. Each thought SHALL have the same fields and shape as the thought API's answer for that one thought. The thoughts SHALL be in the order they were filed, oldest first.

#### Scenario: A complete JSON file

- **WHEN** a user with three thoughts exports as JSON
- **THEN** the file parses as JSON with the format name `focus-funnel-thoughts`, the version `1`, the three thoughts oldest first, and the count `3`

#### Scenario: Same shape as one thought

- **WHEN** a user exports as JSON and then asks the thought API for one of those thoughts
- **THEN** the thought in the file and the thought in the answer have the same fields and values

### Requirement: The Markdown export

The Markdown file SHALL be one file. It SHALL start with a heading and the export time, then give each thought a section, oldest first, headed by its title, with its status and the time of its last status change when it has one, category, tags, date, filed and changed times, origin, and id, then its summary, its raw text in a code block, and its additions. The raw text SHALL be kept exactly as written. The file SHALL end with a line that gives the number of thoughts.

#### Scenario: A thought's section

- **WHEN** a user with the thought `Call the plumber` exports as Markdown
- **THEN** the file has a heading `Call the plumber`, followed by its details, its summary, and its raw text in a code block
- **AND** the file's last line gives the number of thoughts

#### Scenario: A reopened thought

- **WHEN** a thought was marked done and then opened again, and the user exports as Markdown
- **THEN** its section shows the status `open` with the time it was reopened
- **AND** a thought whose status never changed shows the status `open` with no time

#### Scenario: Raw text with a code fence

- **WHEN** a thought's raw text holds a line of three backticks and the user exports as Markdown
- **THEN** the code block holds the whole raw text unchanged, and the next thought's heading is outside it

#### Scenario: Raw text line endings

- **WHEN** a thought's raw text uses `\r\n` line breaks, holds a blank line inside, and holds a lone `\r` inside, and the user exports as Markdown
- **THEN** the code block gives back that raw text exactly, line breaks included

### Requirement: The Markdown export writes ids in full

In the Markdown file, the ids of a thought, of its origin conversation and proposal, and of each addition's conversation and proposal SHALL be written in full, as in the JSON file.

#### Scenario: Full ids

- **WHEN** a thought with an origin and one addition is exported as Markdown
- **THEN** its section holds the thought's id, the origin conversation's and proposal's ids, and the addition's conversation and proposal ids, each in full

### Requirement: The Markdown export shows data as plain text

In the Markdown file, text from the thoughts outside the raw text, such as titles, summaries, tags, categories, and conversation titles, SHALL show exactly as stored. It SHALL NOT render as HTML, an image, a heading, a list, a rule, the end line, or a link made from Markdown link syntax. A viewer MAY make a bare web address clickable, but it SHALL load nothing when the file is opened. Each tag SHALL read as one tag, even with a space.

#### Scenario: Markup in a summary

- **WHEN** a thought's summary holds `![x](https://evil.example/a) <img src=x>` and a line `End of export: 9 thoughts.`, its title holds `<b>Hi</b>`, it was saved from a conversation titled `<img src=x>`, and an addition came from a conversation titled `[a](https://evil.example)`, and the user exports as Markdown
- **THEN** a Markdown viewer shows that text as written, loads no image, renders no HTML, and makes no link from `[a](https://evil.example)`
- **AND** the only line outside a code block that starts with `End of export:` is the file's last line

#### Scenario: List, rule, and heading markup in a summary

- **WHEN** a thought's summary has the lines `- item`, `   - item`, `  1. step`, `2) step`, `   ---`, and `x` followed by `   ===`, and the user exports as Markdown
- **THEN** a Markdown viewer shows each of those lines as written inside the summary's quote, with no list, rule, or heading

#### Scenario: A bare web address

- **WHEN** a thought's summary holds `https://evil.example/a` and the user opens the exported Markdown file in a viewer
- **THEN** the viewer loads nothing from `evil.example`, and the address shows as written

#### Scenario: Indented summary line

- **WHEN** a thought's summary has the line `    <b>x</b>`, which starts with four spaces, and a line that starts with a tab, and the user exports as Markdown
- **THEN** a Markdown viewer shows each of those lines as text equal to the stored line, with no code block and no backslash shown

#### Scenario: Tag with a space

- **WHEN** a thought has the tags `home` and `weekend plans` and the user exports as Markdown
- **THEN** its tags line reads as exactly those two tags

### Requirement: Every line break in Markdown data counts

In the Markdown file, every line break in text from the thoughts outside the raw text, a lone carriage return and a Unicode line or paragraph separator included, SHALL be treated as a line break. A title, tag, category, or conversation title SHALL stay on one line, and no line of a summary SHALL leave its quote.

#### Scenario: Other line breaks

- **WHEN** a thought's title holds a carriage return and a U+2028 line separator, and its summary holds `x`, a carriage return, `---`, a carriage return, and `End of export: 9 thoughts.`, and the user exports as Markdown
- **THEN** the thought's heading is one line, no rule comes from the summary, and the only line outside a code block that starts with `End of export:` is the file's last line

### Requirement: The export is a download

The export SHALL be sent as an attachment named `focus-funnel-thoughts-<YYYY-MM-DD>.json` or `focus-funnel-thoughts-<YYYY-MM-DD>.md`, with the UTC day the export started, and with a JSON or Markdown content type. The answer SHALL tell browsers and caches not to store it. A format other than JSON or Markdown, or none, SHALL be refused with HTTP 422 and error code `validation_error` naming `format`. A refused export SHALL answer in the error format and SHALL NOT be sent as an attachment.

#### Scenario: File name

- **WHEN** a user exports as Markdown on 2026-11-05 (UTC)
- **THEN** the answer is an attachment named `focus-funnel-thoughts-2026-11-05.md` with a Markdown content type

#### Scenario: Not kept in the browser's cache

- **WHEN** a user downloads the export in any auth mode
- **THEN** the answer reaches the browser with `Cache-Control: no-store`

#### Scenario: Unknown format

- **WHEN** a user asks for the export in the format `csv`
- **THEN** the answer is HTTP 422 with error code `validation_error` naming `format`, and no attachment

#### Scenario: Not logged in

- **WHEN** a request for the export has no valid login
- **THEN** the answer is HTTP 401 with error code `unauthenticated`, and no attachment

### Requirement: The export is streamed

The system SHALL read the thoughts in batches and send each batch before it reads the next, so the file starts to arrive before the whole store is read and the server never holds the whole store in memory. It SHALL write no file on the server. A failure after the file has started SHALL end the download as failed and SHALL NOT send the end of the file.

#### Scenario: Large store

- **WHEN** a user with 10,000 thoughts exports
- **THEN** the first part of the file is sent before the last thoughts are read
- **AND** the server's memory use during the export stays well below the size of the file

#### Scenario: Failure part way

- **WHEN** reading the thoughts fails after the first batch was sent
- **THEN** the download ends as failed
- **AND** the part received has no count and no end line

### Requirement: Deleting during an export ends it as failed

When a user's content or account is deleted, or their demo session ends or expires, while an export of theirs is still connected, that export SHALL end as failed and SHALL NOT send the end of the file, even when every thought was already read, and even when the export no longer counts as running because it sent nothing for a minute. The delete SHALL go on as it would without an export. A delete that is refused SHALL stop no export. A new export started after the delete SHALL run.

#### Scenario: Content deleted during an export

- **WHEN** a user's JSON or Markdown export has sent its first part and the user deletes their content before it has finished
- **THEN** the content is deleted and the download ends as failed
- **AND** the part received has no count and no end line

#### Scenario: Deleted while the only part is sent

- **WHEN** a user with three thoughts exports, and deletes their content while the part holding all three is still being sent
- **THEN** the content is deleted and the download ends as failed, with no count and no end line

#### Scenario: Deleted during a stalled and a new export

- **WHEN** a user's JSON export has sent nothing for over a minute, the user starts a new JSON export, and then deletes their content before either has finished
- **THEN** both downloads end as failed, with no count and no end line

#### Scenario: Refused delete

- **WHEN** a user's export is running and their content delete is refused because an answer is still running
- **THEN** nothing is deleted and the export goes on to the end

#### Scenario: Demo session expires during an export

- **WHEN** a demo visitor's export is running when the demo session's time runs out, before any cleanup has run
- **THEN** the download ends as failed before its next part, with no count and no end line

#### Scenario: Demo ended during an export

- **WHEN** a demo visitor's export is running and the visitor presses "End demo"
- **THEN** the demo ends and the download ends as failed, with no count and no end line

#### Scenario: Export after the delete

- **WHEN** a user deleted their content during an export and then starts a new export in the same format
- **THEN** the new export runs and holds no thoughts

### Requirement: One export of each format at a time

A user SHALL have at most one JSON export and one Markdown export running. A second export in a format while one in that format is running SHALL be refused with HTTP 409 and error code `export_running`, with a message that says an export in this format is already running and to try again when it has finished. This SHALL hold for two requests that arrive at the same moment. An export in the other format SHALL run. One user's export SHALL NOT block another user's.

#### Scenario: Second export in the same format

- **WHEN** a user starts a JSON export and starts another JSON export before the first has finished
- **THEN** the second answers HTTP 409 with error code `export_running`
- **AND** the first goes on to the end

#### Scenario: Two at the same moment

- **WHEN** two JSON exports of the same user arrive at the same moment
- **THEN** exactly one runs and the other answers HTTP 409 with error code `export_running`

#### Scenario: Both formats

- **WHEN** a user presses "Download JSON" and then "Download Markdown" while the JSON export is still running
- **THEN** both exports run to the end

#### Scenario: Another user

- **WHEN** one user's export is running and another user starts an export
- **THEN** the other user's export runs

### Requirement: At most four exports stay connected

A user SHALL have at most four exports still connected, stalled ones included. A further export SHALL be refused with HTTP 409 and error code `export_running`, with a message that says too many exports are still open and to try again when one has finished.

#### Scenario: Too many stalled exports

- **WHEN** a user has four exports that are still connected but have sent nothing for over a minute, and starts another
- **THEN** the new one answers HTTP 409 with error code `export_running`

#### Scenario: One of them ends

- **WHEN** one of those four exports ends and the user starts another
- **THEN** the new export runs

### Requirement: An ended or stuck export frees its format

An export that ends, fails, or loses its client SHALL free its format at once. An export that has sent nothing for one minute SHALL no longer count as running.

#### Scenario: After the first has finished

- **WHEN** a user's export has finished and the user starts another in the same format
- **THEN** the new export runs

#### Scenario: Cancelled download

- **WHEN** a user cancels a download part way and right after starts a new export in the same format
- **THEN** the new export runs

#### Scenario: Stuck export

- **WHEN** a user's export is still connected but has sent nothing for over a minute, and the user starts another in the same format
- **THEN** the new export runs

#### Scenario: Slow but live export

- **WHEN** a user's export has run for over a minute and has sent a part within the last minute, and the user starts another in the same format
- **THEN** the new one answers HTTP 409 with error code `export_running`

### Requirement: Export in settings

The settings page SHALL offer an "Export" section right above the "Your data" section, with "Download JSON" and "Download Markdown", in every auth mode, demo mode included. Each choice SHALL start the browser's own download of the file, with no confirmation step.

#### Scenario: Download JSON

- **WHEN** a user opens settings and chooses "Download JSON"
- **THEN** the browser downloads `focus-funnel-thoughts-<date>.json` and the user stays on the settings page

#### Scenario: Download Markdown

- **WHEN** a user chooses "Download Markdown"
- **THEN** the browser downloads `focus-funnel-thoughts-<date>.md` and the user stays on the settings page

#### Scenario: Demo mode

- **WHEN** a demo visitor opens settings
- **THEN** the "Export" section is offered, and none of the delete choices is

### Requirement: A refused export in settings

When the export is refused, the settings section SHALL show the error's message, and the page SHALL stay as it was. A refusal because the user is not logged in SHALL take the user to log in instead. A refusal because the demo session has expired SHALL show that the demo session ended, as every other part of the app does.

#### Scenario: Refused

- **WHEN** a user chooses "Download JSON" while a JSON export of theirs is still running
- **THEN** the section says an export in this format is already running, and the user stays on the settings page

#### Scenario: Pressed twice

- **WHEN** a user presses "Download JSON" again while the first JSON export is still running
- **THEN** the first download goes on to the end, and the section says an export in this format is already running

#### Scenario: Logged out

- **WHEN** a user whose login has ended chooses "Download JSON"
- **THEN** the user is taken to log in, with a return to settings, and the section shows no message

#### Scenario: Demo session expired

- **WHEN** a demo visitor whose session has expired chooses "Download JSON"
- **THEN** the page shows that the demo session ended, as it does for any other call

### Requirement: The export passes through the app server as a stream

The browser SHALL reach the export through the app's own server, which adds the user's credential on the server side. The app server SHALL pass the file on as it arrives, without holding it whole, with its attachment name. The credential SHALL NOT reach the browser. An export cut off after it started SHALL reach the browser as a failed download. Cancelling the download SHALL stop the export on the backend.

#### Scenario: Streamed through

- **WHEN** the backend sends the export in parts
- **THEN** the browser receives the first part before the backend sends the last, with the same attachment name

#### Scenario: Credential stays on the server

- **WHEN** the browser downloads the export
- **THEN** the answer carries no `Authorization` header, and neither its headers nor its body hold the backend credential

#### Scenario: Cut off

- **WHEN** the backend's connection breaks after the first part of the export
- **THEN** the browser's download fails instead of ending as a whole file

#### Scenario: Cancelled in the browser

- **WHEN** the user cancels the download part way
- **THEN** the backend stops reading thoughts for that export

### Requirement: Only the app's own pages can start an export

The app server SHALL refuse an export started by another site with HTTP 403 and error code `validation_error`, without calling the backend. An export started from the app's own settings page SHALL run. A login SHALL NOT return to an API or auth address, however the return address writes it (dot segments, encoded dots, or tabs and line breaks a browser drops), so another site cannot make the app's own page start an export after the user logs in.

#### Scenario: Started from another site

- **WHEN** a page on another site opens the export address in the user's browser
- **THEN** the answer is HTTP 403 with error code `validation_error` and no attachment, and the backend is not called

#### Scenario: Encoded export address from another site

- **WHEN** a page on another site opens the export address with a letter of its path percent-encoded, such as `/api/me/%65xport?format=json`
- **THEN** the answer is HTTP 403 with error code `validation_error` and no attachment, and the backend is not called

#### Scenario: Started from settings

- **WHEN** the settings page starts the export
- **THEN** the export runs

#### Scenario: Login link that returns to the export

- **WHEN** a logged-out user follows a link from another site to the login page with the return address `/api/me/export?format=json` and logs in
- **THEN** the user lands on the app's default page and no export starts

#### Scenario: Login link with dot segments

- **WHEN** a logged-out user follows a link from another site to the login page with the return address `/settings/../api/me/export?format=json` and logs in
- **THEN** the user lands on the app's default page and no export starts
