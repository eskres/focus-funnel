## ADDED Requirements

### Requirement: A monthly spend cap

The user SHALL be able to set a monthly spend cap in the usage settings, in estimated dollars or in tokens, or set none. The cap SHALL be separate from the warning threshold. The usage settings SHALL show the cap, whether this month's usage has reached it, that it resets at the start of the next month in UTC, and, outside demo mode, that deleting the usage history makes it count from zero again for this month. One user SHALL NOT see or change another user's cap.

#### Scenario: Cap in dollars

- **WHEN** a user sets a cap of 5 estimated dollars
- **THEN** the usage settings show the cap of $5.00 and whether this month reached it

#### Scenario: First cap before any model settings

- **WHEN** a user who has never saved their model settings sets a cap of 5 estimated dollars
- **THEN** the cap is saved and the usage settings show it

#### Scenario: Cap in tokens

- **WHEN** a user sets a cap of 2,000,000 tokens
- **THEN** the month's tokens, not the estimated cost, are compared with it

#### Scenario: Reset date in December

- **WHEN** a user with a cap looks at the usage settings on 31 December in UTC
- **THEN** the reset date shown is 1 January of the next year

#### Scenario: Cap removed

- **WHEN** a user removes their cap
- **THEN** no turn is refused for spend

#### Scenario: Amount not valid

- **WHEN** a user saves a cap of zero, a negative amount, or an unknown unit
- **THEN** the system responds with HTTP 422 and error code `validation_error`
- **AND** the saved cap does not change

#### Scenario: Usage history deleted

- **WHEN** a user whose month reached their cap deletes their usage history
- **THEN** the cap counts from zero again for this month and the next message is answered

#### Scenario: Cap and warning together

- **WHEN** a user has a warning threshold of $3 and a cap of $5, and the month reaches $3
- **THEN** the chat shows the warning notice once and keeps answering

#### Scenario: Demo visitor

- **WHEN** a demo visitor sets a cap
- **THEN** the cap works as for any user
- **AND** the usage settings do not mention deleting the usage history, which demo mode does not offer
- **AND** it is deleted with the visitor's other data when the session ends

### Requirement: What counts toward the cap

Every usage record of the user in the current calendar month, in UTC, SHALL count toward the cap: chat answers, `/compact`, offers, model tests, and embedding calls. A dollar cap SHALL compare the sum of estimated costs, where a call with unknown cost adds nothing. A token cap SHALL compare the sum of tokens, where unknown tokens add nothing. The cap SHALL be reached when the sum is equal to or above it.

#### Scenario: Embeddings count

- **WHEN** a user's searches and saved thoughts made embedding calls this month
- **THEN** their cost counts toward a dollar cap and their tokens toward a token cap

#### Scenario: Unknown price under a dollar cap

- **WHEN** a user with a dollar cap chats with a model that has no listed price
- **THEN** those calls add nothing to the sum compared with the cap
- **AND** the usage settings say that calls with unknown cost are not counted in dollars

#### Scenario: Unknown price under a token cap

- **WHEN** a user with a token cap chats with a model that has no listed price
- **THEN** the tokens of those calls count toward the cap

#### Scenario: New month

- **WHEN** a user reached their cap in one month and the next month starts in UTC
- **THEN** the next message is answered

#### Scenario: Deleted conversation

- **WHEN** a user deletes a conversation whose answers spent part of the cap
- **THEN** that spend still counts toward the month's cap

### Requirement: The cap refuses new turns

When the month's usage has reached the user's cap, the system SHALL refuse a chat message, whatever its command or model, and `/compact`, with HTTP 409 and error code `spend_cap_reached`, before any model call. The message SHALL name the cap and say to raise or remove it in Settings. A chat message SHALL be kept; `/compact` changes nothing in the conversation. After the cap is raised above the month's usage or removed, the next message SHALL be answered.

#### Scenario: Message at the cap

- **WHEN** a user whose month has reached their cap sends a message
- **THEN** the system responds with error code `spend_cap_reached`
- **AND** no model is called and no usage is recorded
- **AND** the user's message is stored in the conversation

#### Scenario: Compact at the cap

- **WHEN** a user whose month has reached their cap sends `/compact`
- **THEN** the system responds with error code `spend_cap_reached` and no summary is written
- **AND** no model is called and nothing in the conversation changes

#### Scenario: A model with no listed price

- **WHEN** a user's dollar cap is reached and their conversation uses a model with no listed price
- **THEN** the message is still refused with `spend_cap_reached`

#### Scenario: Cap raised

- **WHEN** a refused user raises the cap above the month's usage and sends the message again
- **THEN** the message is answered

### Requirement: A running turn ends at the cap

When the usage of a running turn reaches the user's cap, the model call in flight SHALL finish, and the turn SHALL start no further model call. What the turn produced SHALL be kept: stored rounds, tool results, sources, and a proposal card shown. The turn SHALL end with error code `spend_cap_reached`, and the conversation SHALL be free.

#### Scenario: Cap crossed in a tool round

- **WHEN** a turn's first round calls the search tool and its usage reaches the cap
- **THEN** the search runs and its sources are kept
- **AND** no second model call is made
- **AND** the answer ends with error code `spend_cap_reached`

#### Scenario: Cap crossed by a proposal round

- **WHEN** a turn's first round proposes a thought and its usage reaches the cap
- **THEN** the proposal card is shown and kept, and can be confirmed
- **AND** no second model call is made
- **AND** the answer ends with error code `spend_cap_reached`

#### Scenario: Cap crossed by the final round

- **WHEN** the round that writes the final answer reaches the cap
- **THEN** the answer is stored as complete
- **AND** the next message is refused with `spend_cap_reached`

### Requirement: What the cap does not refuse

At the cap, the system SHALL NOT refuse embedding calls: searching, saving a confirmed thought, editing or adding to a thought, filling in missing entries, and rebuilding an index. It SHALL NOT refuse the model test in the settings, confirming a proposal, or reading conversations and thoughts. Before archive, it SHALL ask no model for an offer, and a held proposal with an unsaved part SHALL still be offered.

#### Scenario: Confirm at the cap

- **WHEN** a user whose month reached the cap confirms a proposal card
- **THEN** the thought is saved and embedded for search

#### Scenario: Archive at the cap

- **WHEN** a user whose month reached the cap archives a conversation with a new message since its last saved card and no held proposal
- **THEN** no model is asked for an offer and the conversation is archived

#### Scenario: Held proposal at the cap

- **WHEN** a user whose month reached the cap archives a conversation that holds a proposal with an unsaved part
- **THEN** that proposal is offered as before archive

#### Scenario: Test at the cap

- **WHEN** a user whose month reached the cap tests a model in the settings
- **THEN** the test runs and its calls are recorded

### Requirement: Connector actions at the cap

At the cap, the system SHALL NOT refuse approving or declining a connector action card. A message refused at the cap SHALL NOT expire the conversation's action cards.

#### Scenario: Action approved at the cap

- **WHEN** a user whose month reached the cap has a pending connector action card, sends a message that is refused at the cap, and then approves the card
- **THEN** the card was still pending after the refused message
- **AND** the action runs once and the card shows its outcome

## MODIFIED Requirements

### Requirement: Every model call is recorded

The system SHALL record, for every model call it makes for a user, the provider, the model, the prompt tokens, the completion tokens, the time, and the conversation, when there is one. Embedding calls, for storing, updating, and searching thoughts and for rebuilding a search index, SHALL be recorded as well, with no completion tokens. It SHALL record an estimated cost calculated from the per-token prices the provider lists for that model at the time of the call. When the provider reports no price, the cost SHALL be recorded as unknown. A record SHALL NOT hold any message or thought text. A call that fails without a reported token count SHALL NOT be recorded. A model call the user stopped SHALL be recorded: with the tokens the provider reported before the stop, where it reported any, and otherwise with tokens estimated from the text sent and the text received, and the cost estimated from those. When the provider never reports tokens, they stay unknown. A call that answered before the user stopped the turn SHALL keep its record.

#### Scenario: A chat answer

- **WHEN** a model answers a message
- **THEN** a record holds the model, the reported tokens, and the estimated cost
- **AND** the record holds no message text

#### Scenario: Compaction and tests

- **WHEN** a `/compact` summary or a model test calls the model
- **THEN** those calls are recorded too

#### Scenario: Two models in one conversation

- **WHEN** a user switches model in the middle of a conversation
- **THEN** each call is recorded against the model that made it

#### Scenario: Price unknown

- **WHEN** the provider lists no price for the model
- **THEN** the record's cost is unknown and its tokens are still recorded

#### Scenario: Embedding calls

- **WHEN** a search in a conversation embeds its query
- **THEN** a record holds the embedding model, the reported prompt tokens, and the conversation
- **AND** the record holds no query text

#### Scenario: Rebuild

- **WHEN** the operator rebuilds a user's search index
- **THEN** the embedding calls for that user are recorded against that user

#### Scenario: Stopped answer

- **WHEN** a user stops an answer while the model is still writing it, on a provider that reports tokens only at the end of a call
- **THEN** a record holds the model, estimated prompt and completion tokens, and a cost estimated from them
- **AND** every earlier call of that turn keeps its reported tokens

#### Scenario: Stopped answer with running counts

- **WHEN** a user stops an answer from a provider that reports its tokens on every chunk
- **THEN** the record holds the prompt tokens last reported, and completion tokens no lower than those last reported

#### Scenario: Search paid before a stop

- **WHEN** a user stops an answer while its search waits after the query was embedded
- **THEN** the embedding call's record is kept and counts toward the cap
