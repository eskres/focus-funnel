## MODIFIED Requirements

### Requirement: A proposal can be reviewed in the chat

When the model proposes a thought, the chat SHALL show the title, summary, tags, category, and date in a card the user can edit, with a way to confirm. A proposal with several parts SHALL show one card per part, grouped, with a way to merge them. The user SHALL be able to carry on the conversation without confirming. A confirmed card SHALL show that the thought was saved, with a link that opens it, or the reason it was not saved. A saved card SHALL show the thought's current title. When the saved thought is deleted, the card SHALL say that it was deleted and SHALL have no link. A change to the thought's title or a delete SHALL show on its card at once in the open chat. Cards SHALL come back, with their saved state, when the conversation is opened again.

#### Scenario: Edit and confirm

- **WHEN** a proposal appears and the user edits the summary and confirms
- **THEN** the card shows that the edited thought was saved, with a link to it

#### Scenario: Dated proposal

- **WHEN** the model proposes a thought dated Friday 2 October 2026 at 19:00
- **THEN** the card shows that date with the title, summary, tags, and category, and the user can change or clear it before confirming

#### Scenario: Carry on instead

- **WHEN** a proposal appears and the user sends another message
- **THEN** the conversation continues and the proposal is held

#### Scenario: Split proposal

- **WHEN** the model proposes three parts in one proposal
- **THEN** the chat shows three cards together, with a merge button

#### Scenario: Reopened conversation

- **WHEN** a user saves one card, leaves, and opens the conversation again
- **THEN** that card shows as saved with its link
- **AND** a card not yet confirmed can still be edited and confirmed

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
