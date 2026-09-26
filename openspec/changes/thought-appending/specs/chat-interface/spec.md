## ADDED Requirements

### Requirement: An addition is reviewed in the chat

A card for an addition SHALL say "Add to:" with the thought's current title. It SHALL show the thought's current summary beside the proposed summary, with the changes marked, and the proposed tags and category, which the user can edit. It SHALL NOT offer a way to change the title. It SHALL offer to add, and to file the card as a new thought instead. A saved addition SHALL say "Added to:" with the thought's current title and a link that opens it. A card for a new thought that has a strong match among the user's filed thoughts SHALL name the match with its filing date and offer to add to it instead; choosing that SHALL turn the card into an addition card.

#### Scenario: Addition card

- **WHEN** the model proposes an addition to `Buy new bike lock`
- **THEN** the card says `Add to: Buy new bike lock` and shows the current and the proposed summary with the changes marked

#### Scenario: Added

- **WHEN** a user confirms an addition card
- **THEN** the card says `Added to: Buy new bike lock`, with a link that opens the thought

#### Scenario: Similar hint

- **WHEN** the model proposes a new idea and the user filed a strongly similar idea last year
- **THEN** the card names that idea and its filing date and offers to add to it instead

#### Scenario: Taking the hint

- **WHEN** a user chooses to add to the named match
- **THEN** the card becomes an addition card for that thought
