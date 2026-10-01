## Purpose

Links a thought saved from a conversation back to that conversation and to the proposal it came from, so the user can open the discussion that led to it.

## ADDED Requirements

### Requirement: A saved thought keeps its origin

A thought saved by confirming a proposal SHALL keep a link to the conversation and to the proposal it came from. Every thought saved from one proposal SHALL link to that proposal, including a thought saved from merged parts. A thought stored any other way SHALL have no origin. The origin SHALL belong to the thought's owner only.

#### Scenario: Saved from a discussion

- **WHEN** a user discusses a trip, confirms the proposal card, and opens the saved thought
- **THEN** the thought shows the conversation it came from

#### Scenario: Saved with /push

- **WHEN** a user saves a thought with `/push` and opens it
- **THEN** the thought shows the conversation it came from

#### Scenario: Split parts

- **WHEN** a user confirms two parts of one proposal as two thoughts
- **THEN** both thoughts show the same conversation and the same proposal

### Requirement: The detail view shows the origin

The thought detail view SHALL show the title of the conversation a thought came from, as the conversation has it now, and the date of the proposal. It SHALL show whether that conversation is archived. A thought with no origin SHALL show no origin section.

#### Scenario: Renamed conversation

- **WHEN** a user renames the source conversation to `Summer trip` and opens the thought
- **THEN** the detail view shows `Summer trip` as its origin

#### Scenario: Archived conversation

- **WHEN** the source conversation is archived and the user opens the thought
- **THEN** the detail view shows the origin and says the conversation is archived

#### Scenario: No origin

- **WHEN** a user opens a thought that has no origin
- **THEN** the detail view shows no origin section

### Requirement: The origin opens the conversation at the proposal

Opening the origin SHALL close the detail view, open the source conversation, and show it scrolled to the proposal card the thought was saved from, with the card marked for a moment. This SHALL work for an archived conversation and for a card among messages that `/compact` replaced. Opening an archived conversation this way SHALL NOT restore it. The address SHALL name the conversation and the proposal, so it can be copied and opened again.

#### Scenario: Open the origin

- **WHEN** a user opens a thought from a source under an answer and clicks its origin
- **THEN** the source conversation shows with the saved proposal card in view and marked

#### Scenario: Origin in the open conversation

- **WHEN** the thought came from the conversation that is already open and the user clicks its origin
- **THEN** the detail view closes and the chat scrolls to the proposal card

#### Scenario: Compacted

- **WHEN** the proposal card is among messages replaced by `/compact` and the user opens the origin
- **THEN** the card is in view, shown as compacted

#### Scenario: Archived stays archived

- **WHEN** a user opens the origin of a thought from an archived conversation
- **THEN** the conversation shows at the proposal card
- **AND** it stays under "Archived" in the sidebar

#### Scenario: Copied address

- **WHEN** a user copies the address after opening an origin and opens it in a new tab
- **THEN** the same conversation shows with the same proposal card in view

### Requirement: Deleting the conversation keeps the thought

Deleting the source conversation SHALL remove only the thought's origin. The thought's title, summary, tags, category, and raw text SHALL stay, and search SHALL still find it. An origin address that names a deleted conversation SHALL get the chat's usual answer for a conversation that does not exist. An origin address that names a proposal that is not in the conversation SHALL show the conversation as it opens normally, with no card marked.

#### Scenario: Conversation deleted

- **WHEN** a user deletes the source conversation with `/delete` and opens the thought
- **THEN** the thought shows all its content and no origin section
- **AND** a search for its title still finds it

#### Scenario: Old address

- **WHEN** a user opens a copied origin address after deleting that conversation
- **THEN** the chat says the conversation does not exist

#### Scenario: Unknown proposal

- **WHEN** a user opens an origin address whose conversation exists but whose proposal is not in it
- **THEN** the conversation shows as it opens normally, with no card marked

#### Scenario: Another user's origin

- **WHEN** a user opens an origin address that names another user's conversation
- **THEN** the chat says the conversation does not exist
- **AND** nothing of it is shown
