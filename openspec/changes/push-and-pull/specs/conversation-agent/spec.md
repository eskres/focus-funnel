## MODIFIED Requirements

### Requirement: A discussion ends in a proposal to file

The system SHALL steer the model to propose a thought when a discussion reaches a conclusion or a decision, even when there is no to-do or idea in it. The proposal SHALL be a short summary of the key findings, including the model's points the user agreed with, with a title, tags, and a category. The user SHALL be able to expand or trim the summary, and change the title, tags, and category, before confirming. Nothing SHALL be stored without the user's confirmation.

#### Scenario: Decision reached

- **WHEN** a user ends a discussion with `ok I've decided: Rust for the CLI tools, Go for the services`
- **THEN** the chat shows a proposal with a summary of the decision and the category `decision`
- **AND** the user can edit the summary, title, tags, and category

#### Scenario: Model's point agreed with

- **WHEN** the model suggests keeping the services in one repository and the user answers `yes, do that` before deciding
- **THEN** the proposal's summary includes keeping the services in one repository

#### Scenario: Confirm

- **WHEN** a user confirms a proposal
- **THEN** the thought is saved

#### Scenario: Edited before confirming

- **WHEN** a user trims the summary and then confirms
- **THEN** the trimmed text is what is saved

### Requirement: A proposal is held while the conversation carries on

When the user carries on the conversation after a proposal was made, the proposal SHALL be held until every part of it is saved or a later proposal replaces it: the system SHALL NOT propose the same conclusion again on each turn. Only the parts not yet saved SHALL be held. A held proposal SHALL be offered again, with a summary that covers what was added, in three cases: the conversation veers onto a different topic, the user archives the conversation or leaves it, and the user sends `/compact`. Time SHALL NOT bring it back: opening an old conversation SHALL NOT show the proposal again by itself. On a change of topic the system SHALL offer the earlier summary before the new topic continues. A card of a proposal that is no longer held SHALL still be confirmable. When a later proposal replaces a held one, the earlier proposal's unsaved cards SHALL be folded away with a note that a newer proposal replaced them, and the user SHALL be able to show them again.

#### Scenario: User carries on

- **WHEN** a user keeps discussing the same topic after a proposal was shown
- **THEN** the chat does not show the proposal again

#### Scenario: Topic changes

- **WHEN** a user with a held proposal sends a message about an unrelated topic
- **THEN** the chat offers the held summary first
- **AND** the new topic then continues

#### Scenario: Archive with a held proposal

- **WHEN** a user archives a conversation that has a held proposal
- **THEN** the chat offers the proposal before archiving

#### Scenario: Compact with a held proposal

- **WHEN** a user sends `/compact` with a held proposal
- **THEN** the chat offers the proposal before compacting

#### Scenario: Returning to an old conversation

- **WHEN** a user opens a conversation with a held proposal after a long time and carries on
- **THEN** the conversation continues as normal and the proposal is not shown again by itself

#### Scenario: Not suggesting deletion

- **WHEN** a proposal is offered
- **THEN** the offer does not suggest deleting the conversation

#### Scenario: Every part saved

- **WHEN** a user saves both parts of a two-part proposal and then archives the conversation
- **THEN** no proposal is offered before archiving

#### Scenario: One part left

- **WHEN** a user saves one part of a two-part proposal and then sends `/compact`
- **THEN** the chat offers only the part not saved

#### Scenario: Replaced card folded

- **WHEN** the chat offers a held proposal again on a change of topic, as a new proposal
- **THEN** the earlier card is folded away with a note that a newer proposal replaced it
- **AND** the user can show it and confirm it

#### Scenario: Older card confirmed

- **WHEN** a user confirms a card from a proposal that a later proposal replaced
- **THEN** that card's thought is saved

## ADDED Requirements

### Requirement: Tools to file and find thoughts

The model SHALL be offered two tools: one that searches the user's thoughts, and one that proposes thoughts to file. A proposal SHALL hold one or more parts, each with a title, a summary, tags, and a category. A tool call SHALL NOT store or change anything by itself: a part is stored only when the user confirms it. The result of a tool SHALL be passed back to the model so it can finish its answer, for a bounded number of rounds. After a proposal, the model's reply SHALL NOT say that anything was saved. The search tool SHALL take a query and, optionally, tags and a start date, and SHALL return the user's matching thoughts in the compact form of thought search, or say that none matched. The thoughts a search returns SHALL be passed to the chat as the answer's sources, and SHALL NOT be shown to the model by id. When the search could match only by words, the tool result SHALL say why in plain words and the model SHALL tell the user; the turn SHALL NOT end with an error.

#### Scenario: Recall question

- **WHEN** a user asks what they filed about milk
- **THEN** the model uses the search tool
- **AND** the chat shows that a search ran

#### Scenario: Clear thing to keep

- **WHEN** a user sends a message that is clearly a to-do or an idea
- **THEN** the model uses the proposal tool
- **AND** the user sees a proposal to review, and nothing is stored yet
- **AND** the model's reply does not say the thought was saved or noted

#### Scenario: Several things to keep

- **WHEN** a user sends `/push buy oat milk and book the dentist`
- **THEN** the model makes one proposal with two parts

#### Scenario: Search finds thoughts

- **WHEN** the search tool runs for a user who has a thought titled `Oat milk` and the query is `milk`
- **THEN** the tool result holds that thought's title, tags, date, and summary
- **AND** the model answers from it
- **AND** the chat receives that thought as a source

#### Scenario: Search narrowed by the model

- **WHEN** a user asks what work ideas they filed this month
- **THEN** the model can call the search tool with the tag `work` and the first of the month as the start date
- **AND** the result holds only thoughts that fit both

#### Scenario: Search finds nothing

- **WHEN** the search tool runs and no thought matches well enough
- **THEN** the tool result says no filed thoughts matched
- **AND** the model tells the user

#### Scenario: Search by words only

- **WHEN** the search tool runs for a user with no saved key for the embedding provider
- **THEN** the tool result holds the matches by words and says that searching by meaning needs that provider's key in settings
- **AND** the model tells the user, and the turn ends normally

#### Scenario: Search before any thought is stored

- **WHEN** the search tool runs for a user who has not stored any thoughts yet
- **THEN** the tool result says no filed thoughts matched, without calling the embedding provider
- **AND** the model tells the user, and nothing is stored

#### Scenario: Bounded rounds

- **WHEN** the model keeps calling tools without finishing
- **THEN** the system stops after the configured number of rounds
- **AND** the chat shows that the answer could not be completed

## REMOVED Requirements

### Requirement: Two tools for the thoughts

**Reason**: Saving exists now, so the scenarios for confirming and searching before thought storage no longer apply, and a proposal can hold several parts with a category.
**Migration**: Replaced by "Tools to file and find thoughts" in this delta, which keeps every other scenario.
