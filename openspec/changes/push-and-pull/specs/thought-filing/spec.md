## Purpose

Turns a proposal the user confirms into a stored thought: with its raw text, a category, and tags that reuse the user's own, and with one card per part when a message holds several thoughts.

## ADDED Requirements

### Requirement: Confirming a proposal saves it

When the user confirms a proposal card, the system SHALL store a thought with the card's title, summary, tags, and category as the user left them, and the raw text of the proposal. The card SHALL then show that the thought was saved, with a link that opens it. Confirming the same card again SHALL NOT store a second thought. A card the store refuses SHALL name the field and keep the user's text, and nothing SHALL be stored. A failed embedding call SHALL NOT fail the save.

#### Scenario: Confirm

- **WHEN** a user confirms a proposal titled `Oat milk` with the tag `groceries`
- **THEN** a thought titled `Oat milk` with the tag `groceries` is stored for that user
- **AND** the card shows that it was saved, with a link to the thought

#### Scenario: Edited before confirming

- **WHEN** a user changes the title, removes a tag, and picks another category, then confirms
- **THEN** the stored thought has the changed title, tags, and category

#### Scenario: Confirmed twice

- **WHEN** a user confirms a card, and the confirm request is sent a second time
- **THEN** only one thought is stored
- **AND** the second answer links to the same thought

#### Scenario: Refused field

- **WHEN** a user confirms a card with a title over 200 characters
- **THEN** the card says the title is too long and keeps the text
- **AND** nothing is stored

#### Scenario: Embedding provider down

- **WHEN** a user confirms a card while the embedding provider cannot be reached
- **THEN** the thought is saved and the card shows it as saved

#### Scenario: Another user's proposal

- **WHEN** a user confirms a proposal from a conversation another user owns
- **THEN** the system answers as if the conversation did not exist, and nothing is stored

### Requirement: The raw text is kept with the thought

Every thought filed from the chat SHALL keep a raw text chosen by the system, not sent by the browser. For `/push`, the raw text SHALL be the message without its command. For any other proposal, the raw text SHALL be the user's own messages in the discussion, in order, separated by a blank line: from the first message after the last saved proposal in the conversation, or from the start of the conversation, up to the message the proposal was made for. Model messages SHALL NOT be part of the raw text; the summary carries what the user agreed with. Compacted messages SHALL still count. When the messages pass 20,000 characters, the raw text SHALL keep the most recent whole messages that fit, and a single message longer than that SHALL be cut at its end.

#### Scenario: Push

- **WHEN** a user sends `/push buy oat milk` and confirms the proposal
- **THEN** the thought's raw text is `buy oat milk`

#### Scenario: A discussion

- **WHEN** a user sends three messages, the model answers each, and the model then proposes a decision that the user confirms
- **THEN** the thought's raw text is the user's three messages, in order
- **AND** it holds none of the model's answers

#### Scenario: A second discussion in the same conversation

- **WHEN** a user saves one proposal, discusses a new topic in two more messages, and confirms a second proposal
- **THEN** the second thought's raw text is only those two messages

#### Scenario: Too long

- **WHEN** a discussion's user messages add up to more than 20,000 characters
- **THEN** the raw text holds the most recent messages that fit, and the thought is saved

### Requirement: Every thought has a category

The proposal tool SHALL ask the model for a category, chosen from the user's categories. The user's categories SHALL be the five fixed kinds, `task`, `idea`, `decision`, `note`, and `reference`, and any the user added. The card SHALL show the category as a choice the user can change, or clear to none. A category the model names that is not one of the user's SHALL be shown as none.

#### Scenario: A to-do

- **WHEN** a user sends `/push call the plumber on Monday`
- **THEN** the card shows the category `task`

#### Scenario: Changed on the card

- **WHEN** a user changes a card's category from `idea` to `decision` and confirms
- **THEN** the stored thought has the category `decision`

#### Scenario: Unknown category from the model

- **WHEN** the model proposes a thought with the category `shopping`, which the user does not have
- **THEN** the card shows no category, and the user can pick one

### Requirement: The user can add categories

The settings page SHALL list the user's categories and let the user add a category and remove one they added. The five fixed kinds SHALL NOT be removable. A category name SHALL be trimmed and lowercased, SHALL be 1 to 30 characters, and SHALL NOT repeat an existing one. A user SHALL have at most 20 added categories. Removing a category SHALL NOT change thoughts already stored with it. Categories SHALL belong to one user.

#### Scenario: Add

- **WHEN** a user adds the category ` Recipe`
- **THEN** the list shows `recipe`
- **AND** the next proposal card offers `recipe`

#### Scenario: Duplicate

- **WHEN** a user adds `Idea`
- **THEN** the system refuses it, saying the category exists

#### Scenario: Remove

- **WHEN** a user removes `recipe` while a stored thought has that category
- **THEN** `recipe` is no longer offered on new cards
- **AND** the stored thought keeps the category `recipe`

#### Scenario: Fixed kinds

- **WHEN** a user views their categories
- **THEN** `task`, `idea`, `decision`, `note`, and `reference` have no remove button

#### Scenario: Another user's categories

- **WHEN** one user adds a category
- **THEN** another user's cards do not offer it

### Requirement: The model reuses the user's tags

Each turn SHALL give the model the tags the user already uses, most used first, up to a limit set in configuration, so a proposal reuses an existing tag where one fits instead of a new spelling of it.

#### Scenario: Existing tag

- **WHEN** a user who has thoughts tagged `groceries` sends `/push buy eggs`
- **THEN** the proposal's tags include `groceries`, not a new tag such as `grocery` or `shopping-list`

#### Scenario: No tags yet

- **WHEN** a user with no stored thoughts sends `/push buy eggs`
- **THEN** the model makes its own tags

### Requirement: A message with several thoughts is split

When a message or discussion holds several separate thoughts, the model SHALL propose each as its own part, in one proposal, and the chat SHALL show one card per part. Each part SHALL be confirmed on its own and SHALL keep the whole raw text of the proposal. Before any part is saved, the user SHALL be able to merge all the parts into one card, with no model call: the first part's title and category, the summaries as paragraphs in order, and the tags of every part without repeats. The merged card SHALL be edited and confirmed like any other card and SHALL store one thought.

#### Scenario: Three things in one message

- **WHEN** a user sends `/push buy oat milk, book the dentist, and idea: a podcast about maps`
- **THEN** the chat shows three cards, one per thing
- **AND** nothing is stored yet

#### Scenario: Confirm one part

- **WHEN** a user confirms the second of three cards
- **THEN** one thought is stored, and the other two cards still wait

#### Scenario: Merge

- **WHEN** a user merges two cards titled `Oat milk` and `Eggs` with the tags `groceries` and `groceries, breakfast`
- **THEN** one card shows the title `Oat milk`, both summaries, and the tags `groceries` and `breakfast`
- **AND** confirming it stores one thought

#### Scenario: Merge after a part is saved

- **WHEN** one of three cards is already saved
- **THEN** the merge button is not offered

#### Scenario: One thing

- **WHEN** a user sends `/push buy oat milk`
- **THEN** the chat shows one card and no merge button
