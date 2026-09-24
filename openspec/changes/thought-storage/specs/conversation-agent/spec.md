# Spec Delta

## MODIFIED Requirements

### Requirement: Two tools for the thoughts

The model SHALL be offered two tools: one that searches the user's thoughts, and one that proposes a thought to file, with a title, a summary, and tags. A tool call SHALL NOT store or change anything by itself: a proposal is stored only when the user confirms it. The result of a tool SHALL be passed back to the model so it can finish its answer, for a bounded number of rounds. The search tool SHALL take a query and, optionally, tags and a start date, and SHALL return the user's matching thoughts in the compact form of thought search, or say that none matched. When the search could match only by words, the tool result SHALL say why in plain words and the model SHALL tell the user; the turn SHALL NOT end with an error. Until saving exists, confirming a proposal SHALL report that saving is not available yet and keep the proposal's text.

#### Scenario: Recall question

- **WHEN** a user asks what they filed about milk
- **THEN** the model uses the search tool
- **AND** the chat shows that a search ran

#### Scenario: Clear thing to keep

- **WHEN** a user sends a message that is clearly a to-do or an idea
- **THEN** the model uses the proposal tool
- **AND** the user sees a proposal to review, and nothing is stored yet

#### Scenario: Search finds thoughts

- **WHEN** the search tool runs for a user who has a thought titled `Oat milk` and the query is `milk`
- **THEN** the tool result holds that thought's title, tags, date, and summary
- **AND** the model answers from it

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

#### Scenario: Search before thought storage exists

- **WHEN** the search tool runs for a user who has not stored any thoughts yet
- **THEN** the tool result says no filed thoughts matched, without calling the embedding provider
- **AND** the model tells the user, and nothing is stored

#### Scenario: Confirm before thought storage exists

- **WHEN** a user confirms a proposal before saving exists
- **THEN** the card says saving is not available yet
- **AND** the proposal's text stays available to copy

#### Scenario: Bounded rounds

- **WHEN** the model keeps calling tools without finishing
- **THEN** the system stops after the configured number of rounds
- **AND** the chat shows that the answer could not be completed
