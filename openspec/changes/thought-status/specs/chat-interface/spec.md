## ADDED Requirements

### Requirement: A status change is reviewed in the chat

A card for a status part SHALL say "Mark done:" with the thought's current title and category, with a way to confirm and no fields to edit. A confirmed card SHALL say "Marked done:" with the thought's current title and a link that opens it. When the thought no longer exists, the card SHALL say so and SHALL have no link and no way to confirm.

#### Scenario: Status card

- **WHEN** the model proposes marking the task `Call the plumber` done
- **THEN** the card says `Mark done: Call the plumber` with the category `task` and a way to confirm
- **AND** it offers no title, summary, tags, or category fields

#### Scenario: Confirmed

- **WHEN** a user confirms that card
- **THEN** the card says `Marked done: Call the plumber`, with a link that opens the thought

#### Scenario: Thought gone

- **WHEN** a user deletes `Call the plumber` and then confirms a card that marks it done
- **THEN** the card says the thought no longer exists and has no link

### Requirement: A failed status confirm can be tried again

A confirm of a status card that fails for any reason other than a missing thought SHALL show the reason and SHALL keep the way to confirm. The card SHALL NOT say that the thought was marked done or that it no longer exists.

#### Scenario: Confirm fails

- **WHEN** a user confirms a status card and the server answers with an error other than "not found", or cannot be reached
- **THEN** the card shows the reason and still has its `Mark done` button
- **AND** it does not say `Marked done:` or that the thought no longer exists

### Requirement: A status card is named for screen readers

A screen reader SHALL name a status card `Mark done:` with the title before confirm, and `Marked done:` with the title after, never as a thought to file or as saved. A proposal whose parts all mark thoughts done SHALL be named as a proposed status change, not as a proposal to file.

#### Scenario: Name of a status card

- **WHEN** a screen reader reads the card that marks `Call the plumber` done, before and after the user confirms it
- **THEN** it names the card `Mark done: Call the plumber` before, and `Marked done: Call the plumber` after
- **AND** never `Thought to file:` or `Saved:`

#### Scenario: Name of a status-only proposal

- **WHEN** a proposal only marks `Call the plumber` done
- **THEN** a screen reader names its group `Proposed status change`

### Requirement: A status card comes back as it was

A status card SHALL come back with its state when the conversation is opened again, beside the other cards of its proposal. A confirmed status card and a confirmed addition to the same thought SHALL come back as two cards, never as one merged card.

#### Scenario: Reopened conversation

- **WHEN** a user confirms a status card, leaves, and opens the conversation again
- **THEN** the card says `Marked done: Call the plumber` with its link
- **AND** a status card not yet confirmed can still be confirmed

#### Scenario: Addition and mark on the same thought, reopened

- **WHEN** one proposal adds to `Call the plumber` and marks it done, the user confirms both cards, leaves, and opens the conversation again
- **THEN** the chat shows two cards, `Added to: Call the plumber` and `Marked done: Call the plumber`, and no merged card

### Requirement: A status card shows that its thought was deleted

When the thought of a confirmed status card is deleted later, the card SHALL say that it was deleted, with the title it was proposed with, and SHALL have no link. It SHALL say so at once in the open chat and when the conversation is opened again.

#### Scenario: Thought deleted after the mark

- **WHEN** a user confirms the card that marks `Call the plumber` done, and later deletes that thought from the sheet
- **THEN** the card says `Call the plumber` was deleted and has no link
- **AND** it says so, with no link, when the conversation is opened again

## MODIFIED Requirements

### Requirement: A proposal can be reviewed in the chat

When the model proposes a thought, the chat SHALL show the title, summary, tags, category, and date in a card the user can edit, with a way to confirm. A proposal with several parts SHALL show one card per part, grouped, with a way to merge them. The user SHALL be able to carry on the conversation without confirming. A confirmed card SHALL show that the thought was saved, with a link that opens it, or the reason it was not saved. A saved card SHALL show the thought's current title. When the saved thought is deleted, the card SHALL say that it was deleted and SHALL have no link. A change to the thought's title or a delete SHALL show on its card at once in the open chat. Cards SHALL come back, with their saved state, when the conversation is opened again. A card for a part that marks a thought done SHALL NOT be edited: it SHALL be reviewed and confirmed as "A status change is reviewed in the chat" says, and a proposal with such a part SHALL offer no way to merge.

#### Scenario: Edit and confirm

- **WHEN** a proposal appears and the user edits the summary and confirms
- **THEN** the card shows that the edited thought was saved, with a link to it

#### Scenario: Dated proposal

- **WHEN** the model proposes a thought dated Friday 2 October 2026 at 19:00
- **THEN** the card shows that date with the title, summary, tags, and category, and the user can change or clear it before confirming

#### Scenario: Carry on instead

- **WHEN** a proposal of a new thought appears and the user sends another message
- **THEN** the conversation continues and the proposal is held

#### Scenario: Split proposal

- **WHEN** the model proposes three new thoughts in one proposal
- **THEN** the chat shows three cards together, with a merge button

#### Scenario: Reopened conversation

- **WHEN** a user saves one card, leaves, and opens the conversation again
- **THEN** that card shows as saved with its link
- **AND** a new-thought card not yet confirmed can still be edited and confirmed

#### Scenario: Title changed after saving

- **WHEN** a user saves a card titled `Trip ideas`, opens the thought, and changes its title to `Lisbon trip`
- **THEN** the saved card shows `Lisbon trip` at once
- **AND** it still shows `Lisbon trip` when the conversation is opened again

#### Scenario: Thought deleted after saving

- **WHEN** a user saves a card and then deletes that thought from the sheet
- **THEN** the card says the thought was deleted and has no link
- **AND** it says so when the conversation is opened again

#### Scenario: Deleted thought stays filed

- **WHEN** a user deletes the only saved thought of a proposal
- **THEN** the proposal is not offered again to file

#### Scenario: Status card beside a new thought

- **WHEN** a proposal marks `Call the plumber` done and proposes `Buy oat milk`
- **THEN** the oat milk card can be edited and confirmed, and the `Call the plumber` card has no fields and only a way to confirm
- **AND** no merge button is shown
