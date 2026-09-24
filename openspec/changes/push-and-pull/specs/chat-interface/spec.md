## MODIFIED Requirements

### Requirement: A proposal can be reviewed in the chat

When the model proposes a thought, the chat SHALL show the title, summary, tags, and category in a card the user can edit, with a way to confirm. A proposal with several parts SHALL show one card per part, grouped, with a way to merge them. The user SHALL be able to carry on the conversation without confirming. A confirmed card SHALL show that the thought was saved, with a link that opens it, or the reason it was not saved. Cards SHALL come back, with their saved state, when the conversation is opened again.

#### Scenario: Edit and confirm

- **WHEN** a proposal appears and the user edits the summary and confirms
- **THEN** the card shows that the edited thought was saved, with a link to it

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
