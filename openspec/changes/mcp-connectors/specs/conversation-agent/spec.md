# Spec Delta

## MODIFIED Requirements

### Requirement: Tools to file and find thoughts

The model SHALL be offered two built-in tools: one that searches the user's thoughts, and one that proposes thoughts to file. It SHALL also be offered the switched-on tools of the connectors that are on in the conversation, as the connector capability describes. A proposal SHALL hold one or more parts, each with a title, a summary, tags, and a category. A built-in tool call SHALL NOT store or change anything by itself: a part is stored only when the user confirms it. The result of every tool, built-in or from a connector, SHALL be passed back to the model so it can finish its answer, within one bounded number of rounds per turn. After a proposal, the model's reply SHALL NOT say that anything was saved. The search tool SHALL take a query and, optionally, tags and a start date, and SHALL return the user's matching thoughts in the compact form of thought search, or say that none matched. The thoughts a search returns SHALL be passed to the chat as the answer's sources, and SHALL NOT be shown to the model by id. When the search could match only by words, the tool result SHALL say why in plain words and the model SHALL tell the user; the turn SHALL NOT end with an error.

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

#### Scenario: Built-in and connector tools together

- **WHEN** a conversation has the calendar connector on and the user asks what they filed about the trip and what is on their calendar that week
- **THEN** the model can call `search_thoughts` and `calendar__list_events` in the same turn
- **AND** both results go back to the model before it finishes its answer
- **AND** the rounds of both count against the same limit
