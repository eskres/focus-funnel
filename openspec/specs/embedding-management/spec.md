# embedding-management Specification

## Purpose

Chooses which embedding model builds each user's search index, records it with the index, fills in missing embeddings, and lets an operator rebuild indexes with another model without stopping search.

## Requirements

### Requirement: The operator sets the embedding model

The operator SHALL set one embedding provider and model for the instance. The provider SHALL be one of the presets; the custom provider SHALL NOT be allowed, since its address differs per user. The server SHALL refuse to start with an unknown provider, the custom provider, or an empty model, naming the setting.

#### Scenario: Custom provider refused

- **WHEN** the server starts with the embedding provider set to `custom`
- **THEN** it refuses to start and names the embedding provider setting

#### Scenario: Unknown provider refused

- **WHEN** the server starts with an embedding provider that is not a preset
- **THEN** it refuses to start and names the embedding provider setting

### Requirement: Each index records how it was built

Each user SHALL have their own search index, never shared with another user. Each index SHALL record its version, its embedding provider and model, its vector dimension, and its status: building, active, or retired. A user SHALL have at most one active index. A new index SHALL take the configured provider and model when it is created; after that, storing and searching SHALL use the provider and model recorded with the index, not the current setting.

#### Scenario: First thought

- **WHEN** a user's first thought is embedded
- **THEN** an active index is created for them, recording the configured provider and model and the vector dimension

#### Scenario: Setting changed later

- **WHEN** the operator changes the embedding model and a user with an existing index searches
- **THEN** the query is embedded with the model recorded for that user's index, and the search works

#### Scenario: Per-user indexes

- **WHEN** two users have stored thoughts
- **THEN** each has their own index, and neither index holds the other's entries

### Requirement: One place chooses the embedding model

Choosing the provider and model for a new index SHALL go through one decision point, which today returns the instance setting for every user. A later per-user choice SHALL be possible by changing only that decision point, and indexes with different models and dimensions SHALL be able to exist side by side.

#### Scenario: Same model for every user

- **WHEN** two users store their first thought
- **THEN** both indexes record the instance's embedding provider and model

### Requirement: Missing embeddings are filled in

When a user stores a thought or searches and their index lacks embeddings for some of their thoughts, the system SHALL create a bounded number of the missing ones in the same request, oldest first, without delaying the result by more than one embedding call. A failure SHALL leave them missing for the next try and SHALL NOT fail the request.

#### Scenario: Backlog cleared over requests

- **WHEN** a user has 3 thoughts without embeddings and the provider is reachable again
- **THEN** their next search creates the missing embeddings and finds those thoughts by meaning

### Requirement: Operator rebuilds indexes

The operator SHALL be able to run a command-line job, not reachable over the API, that rebuilds the index of one user or of all users with the configured embedding model, from the thoughts in the database. The job SHALL build a new index version beside the active one and, in one transaction, check that every thought has its entries in it, make it active, and retire the old one, whose entries SHALL then be deleted. Search SHALL keep working from the old index during the build. A thought stored, updated, or deleted during the build SHALL be reflected in the new index. A user whose key is missing or refused SHALL keep their old index, and the job SHALL report them and end with a failure status. Demo users SHALL be skipped.

#### Scenario: Rebuild one user

- **WHEN** the operator rebuilds a user with 12 thoughts after changing the embedding model
- **THEN** the user's new index records the new model and covers all 12 thoughts
- **AND** the old index is retired, its entries are deleted, and searches use the new one

#### Scenario: Search during a rebuild

- **WHEN** the user searches while their rebuild is running
- **THEN** the search answers from the old index

#### Scenario: Thought stored during a rebuild

- **WHEN** the user stores a thought while their rebuild is running
- **THEN** after the rebuild the thought is found by meaning

#### Scenario: User without a key

- **WHEN** a rebuild of all users meets a user with no saved key for the embedding provider
- **THEN** that user keeps their old active index
- **AND** the job reports the user and ends with a failure status after rebuilding the others
