## MODIFIED Requirements

### Requirement: Tools to file and find thoughts

The model SHALL be offered two tools: one that searches the user's thoughts, and one that proposes thoughts to file. A proposal SHALL hold one or more parts, each with a title, a summary, tags, and a category. A part SHALL be able to name, by a short ref, a thought the conversation has seen, to add to it instead of filing a new thought. A tool call SHALL NOT store or change anything by itself: a part is stored only when the user confirms it. The result of a tool SHALL be passed back to the model so it can finish its answer, for a bounded number of rounds. After a proposal, the model's reply SHALL NOT say that anything was saved. The search tool SHALL take a query and, optionally, tags and a start date, and SHALL return the user's matching thoughts in the compact form of thought search, or say that none matched. The thoughts a search returns SHALL be passed to the chat as the answer's sources, and SHALL NOT be shown to the model by id; the model SHALL see them by ref. When the search could match only by words, the tool result SHALL say why in plain words and the model SHALL tell the user; the turn SHALL NOT end with an error. Each turn SHALL tell the model which thoughts the conversation has seen, up to a configured number, most recently seen first, each with its ref, title, tags, category, and summary. When the similar-thought check finds candidates for a proposal's new parts, the tool result SHALL list them by ref and ask the model to propose again, marking each new part as an addition or as new; a second proposal in the same turn SHALL be shown without another check.

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

#### Scenario: Thoughts seen by ref

- **WHEN** a conversation has filed one thought and a search in it returned two others
- **THEN** the next turn tells the model those three thoughts, each with a ref and no id

#### Scenario: Candidates found

- **WHEN** the model proposes a new idea and the similar-thought check finds a filed idea on the same subject
- **THEN** no card is shown yet, and the tool result lists the filed idea by ref
- **AND** the model's second proposal in that turn is shown as its card

### Requirement: The offer before an action may propose nothing

Before archive or `/compact`, when no proposal with an unsaved part is held, the system SHALL ask the model for a proposal only if the user sent a message after the latest proposal with a saved part. The model SHALL be told which thoughts this conversation has seen, each by its ref, including those it already filed, SHALL be free to propose nothing, and SHALL be steered to leave out greetings, thanks, and small talk. When the discussion since the latest saved proposal continues one of those thoughts, the offer SHALL propose it as an addition to that thought, not as a new thought. A new part in the offer SHALL go through the similar-thought check. When the model proposes nothing, the action SHALL go ahead with no offer.

#### Scenario: Nothing said since the last saved card

- **WHEN** a user confirms every card of a proposal and then sends `/compact` without another message
- **THEN** no proposal is offered and the model is not asked for one

#### Scenario: Only thanks since

- **WHEN** a user confirms a card, sends `thanks`, and then sends `/compact`
- **THEN** no proposal is offered

#### Scenario: New facts on the same topic

- **WHEN** a user files `Buy a bike lock`, asks about lock colours, strength, and prices, and then sends `/compact`
- **THEN** the offer does not repeat `Buy a bike lock` as a new thought
- **AND** it offers the new facts as an addition to `Buy a bike lock`

#### Scenario: Offer finds an older thought

- **WHEN** a user discusses a podcast about cartography, never files it, and archives the conversation, and they filed `Podcast about maps` a year ago in another conversation
- **THEN** the offer adds to `Podcast about maps`, or its card offers to add to it
