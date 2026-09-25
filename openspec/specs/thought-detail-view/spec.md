# thought-detail-view Specification

## Purpose

Shows one stored thought in full, in a side sheet over the chat, so a user can check a source or a saved proposal without leaving the conversation.

## Requirements

### Requirement: A thought opens in a side sheet

Opening a thought SHALL show a side sheet over the chat with its title, summary, tags, category, raw text, and the dates it was filed and last changed. The chat SHALL stay in place behind it. The sheet SHALL be read-only. A thought with no raw text SHALL show no raw text section. A raw text that is the same as the summary SHALL NOT be shown twice.

#### Scenario: Open from a saved card

- **WHEN** a user clicks the link on a saved proposal card
- **THEN** a side sheet shows the thought's title, summary, tags, category, raw text, and dates
- **AND** the conversation is still visible behind it

#### Scenario: Close

- **WHEN** the user closes the sheet
- **THEN** the chat is as it was, with the same scroll position and any unsent text in the input

#### Scenario: No changes from the sheet

- **WHEN** a user views a thought in the sheet
- **THEN** the sheet offers no way to edit or delete it

### Requirement: An open thought has its own address

While a thought is open, the page address SHALL name it, so the address can be copied and opened again, and the browser's Back SHALL close the sheet. Opening that address SHALL show the conversation with the thought open.

#### Scenario: Copied address

- **WHEN** a user copies the address while a thought is open and opens it in a new tab
- **THEN** the same conversation shows with the same thought open

#### Scenario: Back

- **WHEN** a user opens a thought and presses Back
- **THEN** the sheet closes and the user stays in the conversation

### Requirement: Only the owner sees a thought

The system SHALL return a thought only to its owner. A thought of another user and a thought that does not exist SHALL get the same answer, HTTP 404 with error code `not_found`, and the sheet SHALL say the thought no longer exists.

#### Scenario: Another user's thought

- **WHEN** a user opens an address that names another user's thought
- **THEN** the sheet says the thought no longer exists
- **AND** nothing of the thought is shown
