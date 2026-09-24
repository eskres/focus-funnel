# Spec Delta

## Purpose

Finds a user's own thoughts by meaning rather than exact words, with an optional tag filter and a newest-first order, and refuses to answer from an index built with a different embedding model.

## ADDED Requirements

### Requirement: Search by meaning

The system SHALL search a user's thoughts by the meaning of a query, matched against each thought's title and summary, and SHALL return at most a configured number of results, most relevant first. Each result SHALL carry the thought's id, title, summary, tags, and created time. A user with no thoughts SHALL get an empty result without any embedding call.

#### Scenario: Match by meaning

- **WHEN** a user has a thought titled `Oat milk` with the summary `buy oat milk on the way home` and searches for `groceries`
- **THEN** the thought is among the results

#### Scenario: No thoughts yet

- **WHEN** a user who has never stored a thought searches
- **THEN** the result is empty and no provider is called

#### Scenario: Result limit

- **WHEN** a user with 50 thoughts searches
- **THEN** at most the configured number of results is returned

### Requirement: Tag filter and newest-first order

A search SHALL accept an optional set of tags and SHALL then return only thoughts that carry at least one of them. A search SHALL accept a newest-first option, which SHALL order the matching results by created time, newest first, instead of by relevance.

#### Scenario: Tag filter

- **WHEN** a user searches for `plans` with the tag `work`
- **THEN** every result carries the tag `work`

#### Scenario: Tag nobody uses

- **WHEN** a user searches with a tag none of their thoughts carries
- **THEN** the result is empty

#### Scenario: Newest first

- **WHEN** a user searches with the newest-first option
- **THEN** the results are ordered by created time, newest first

### Requirement: Search sees only the user's own thoughts

A search SHALL only ever return thoughts the searching user owns, whatever the query and filters.

#### Scenario: Two users with similar thoughts

- **WHEN** two users each store a thought about milk and one of them searches for `milk`
- **THEN** the results hold only that user's thought

### Requirement: Search uses the user's key for the embedding provider

A search SHALL embed the query through the embedding provider with the searching user's own key for that provider. Without a usable key, the search SHALL fail with `provider_key_missing` naming the provider. A provider failure SHALL fail the search with the same provider error codes as a chat call.

#### Scenario: No key for the embedding provider

- **WHEN** a user with thoughts but no saved key for the embedding provider searches
- **THEN** the search fails with `provider_key_missing` naming that provider

#### Scenario: Rate limited

- **WHEN** the embedding provider refuses the call as too many requests
- **THEN** the search fails with `provider_rate_limited`

### Requirement: No search across embedding models

Before comparing vectors, the system SHALL check that the query was embedded with the same model and to the same dimension as the user's search index. On a mismatch it SHALL fail with `embedding_mismatch` and a message that the search index must be rebuilt, and SHALL NOT return results.

#### Scenario: Dimension changed

- **WHEN** the provider returns a query vector whose dimension differs from the one recorded for the user's index
- **THEN** the search fails with `embedding_mismatch` and returns no results

#### Scenario: Index built with another model

- **WHEN** the index records a different embedding model from the one the query was embedded with
- **THEN** the search fails with `embedding_mismatch`
