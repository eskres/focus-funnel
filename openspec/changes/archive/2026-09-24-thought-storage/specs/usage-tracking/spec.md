# Spec Delta

## MODIFIED Requirements

### Requirement: Every model call is recorded

The system SHALL record, for every model call it makes for a user, the provider, the model, the prompt tokens, the completion tokens, the time, and the conversation, when there is one. Embedding calls, for storing, updating, and searching thoughts and for rebuilding a search index, SHALL be recorded as well, with no completion tokens. It SHALL record an estimated cost calculated from the per-token prices the provider lists for that model at the time of the call. When the provider reports no price, the cost SHALL be recorded as unknown. A record SHALL NOT hold any message or thought text. A call that fails without a reported token count SHALL NOT be recorded.

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
