## ADDED Requirements

### Requirement: A status change is reviewed in the chat

A card for a status part SHALL say "Mark done:" with the thought's current title and category, with a way to confirm and no fields to edit. A confirmed card SHALL say "Marked done:" with the thought's current title and a link that opens it. When the thought no longer exists, the card SHALL say so and SHALL have no link and no way to confirm. The card SHALL come back with its state when the conversation is opened again.

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

#### Scenario: Reopened conversation

- **WHEN** a user confirms a status card, leaves, and opens the conversation again
- **THEN** the card says `Marked done: Call the plumber` with its link
- **AND** a status card not yet confirmed can still be confirmed
