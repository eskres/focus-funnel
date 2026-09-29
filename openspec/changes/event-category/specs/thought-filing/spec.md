## MODIFIED Requirements

### Requirement: Every thought has a category

The proposal tool SHALL ask the model for a category, chosen from the user's categories. The user's categories SHALL be the six fixed kinds, `task`, `idea`, `decision`, `note`, `reference`, and `event`, and any the user added. The proposal tool SHALL tell the model that an `event` is something planned for a set date or time, such as an appointment, a meeting, a trip, or a dinner; that something to do or arrange is a `task`, even on a set day; and that something that already happened is a `note`. The card SHALL show the category as a choice the user can change, or clear to none. A category the model names that is not one of the user's SHALL be shown as none.

#### Scenario: A to-do

- **WHEN** a user sends `/push call the plumber on Monday`
- **THEN** the card shows the category `task`

#### Scenario: Something planned for a set time

- **WHEN** a user sends `/push dinner with Sam on Friday at 7`
- **THEN** the card shows the category `event`

#### Scenario: Arranging an event

- **WHEN** a user sends `/push book a table for dinner with Sam`
- **THEN** the card shows the category `task`

#### Scenario: An event that already happened

- **WHEN** a user sends `/push had dinner with Sam last night, she is moving to Oslo`
- **THEN** the card shows the category `note`

#### Scenario: Changed on the card

- **WHEN** a user changes a card's category from `idea` to `decision` and confirms
- **THEN** the stored thought has the category `decision`

#### Scenario: Unknown category from the model

- **WHEN** the model proposes a thought with the category `shopping`, which the user does not have
- **THEN** the card shows no category, and the user can pick one

### Requirement: The user can add categories

The settings page SHALL list the user's categories and let the user add a category and remove one they added. The six fixed kinds SHALL NOT be removable. A category name SHALL be trimmed and lowercased, SHALL be 1 to 30 characters, and SHALL NOT repeat an existing one. A user SHALL have at most 20 added categories. Removing a category SHALL NOT change thoughts already stored with it. Categories SHALL belong to one user. A user who added `event` before it became a fixed kind SHALL have one `event`, the fixed one: their added `event` SHALL be removed, and it SHALL no longer count toward their 20. Thoughts already stored with `event` SHALL keep it.

#### Scenario: Add

- **WHEN** a user adds the category ` Recipe`
- **THEN** the list shows `recipe`
- **AND** the next proposal card offers `recipe`

#### Scenario: Duplicate

- **WHEN** a user adds `Idea`
- **THEN** the system refuses it, saying the category exists

#### Scenario: Add a fixed kind again

- **WHEN** a user adds `Event`
- **THEN** the system refuses it, saying the category exists

#### Scenario: Remove

- **WHEN** a user removes `recipe` while a stored thought has that category
- **THEN** `recipe` is no longer offered on new cards
- **AND** the stored thought keeps the category `recipe`

#### Scenario: Fixed kinds

- **WHEN** a user views their categories
- **THEN** `task`, `idea`, `decision`, `note`, `reference`, and `event` have no remove button

#### Scenario: A user who had added event

- **WHEN** a user added `event` and `recipe` before `event` became a fixed kind, and has a stored thought with the category `event`
- **THEN** their categories list `event` once, as a fixed kind with no remove button, and `recipe` as an added one
- **AND** they can add 19 more categories
- **AND** the stored thought keeps the category `event`

#### Scenario: Another user's categories

- **WHEN** one user adds a category
- **THEN** another user's cards do not offer it
