# thought-search Specification

## Purpose

Finds a user's own thoughts quickly and accurately by combining search by meaning with search by words, and returns only what the reader needs, so the chat model spends few tokens on recall.

## Requirements

### Requirement: Search by meaning and by words

The system SHALL search a user's thoughts by the meaning of a query and by the words in it, over each thought's title, summary, tags, and raw text, and SHALL merge the two into one ranking, most relevant first. Search by meaning SHALL compare the query with every one of the user's entries, not an approximation. A thought that matches in both ways SHALL rank above one that matches in only one, other things being equal.

#### Scenario: Match by meaning

- **WHEN** a user has a thought with the summary `buy oat milk on the way home` and searches for `groceries`
- **THEN** the thought is among the results

#### Scenario: Match by an exact word

- **WHEN** a user has a thought mentioning `ACME-4471` and searches for `ACME-4471`
- **THEN** that thought is the first result

#### Scenario: Detail only in the raw text

- **WHEN** a thought's raw text mentions `Lisbon` but its title and summary do not, and the user searches for `Lisbon`
- **THEN** the thought is among the results

### Requirement: Weak matches are left out

The system SHALL return at most a configured number of results and SHALL leave out a thought whose similarity in meaning is below a configured threshold and that does not match by words. A search where nothing passes SHALL return an empty result, not the nearest thoughts.

#### Scenario: Nothing relevant

- **WHEN** a user whose thoughts are all about groceries searches for `quantum physics`
- **THEN** the result is empty

#### Scenario: Result limit

- **WHEN** a user with 50 matching thoughts searches
- **THEN** at most the configured number of results is returned

### Requirement: Filters and order

A search SHALL accept an optional set of tags and SHALL then return only thoughts that carry at least one of them. It SHALL accept an optional start date and end date and SHALL then return only thoughts created within them. It SHALL accept a newest-first option, which SHALL order the results that pass by created time, newest first, instead of by relevance.

#### Scenario: Tag filter

- **WHEN** a user searches for `plans` with the tag `work`
- **THEN** every result carries the tag `work`

#### Scenario: Tag nobody uses

- **WHEN** a user searches with a tag none of their thoughts carries
- **THEN** the result is empty and no provider is called

#### Scenario: Since a date

- **WHEN** a user searches for `ideas` from 1 September
- **THEN** every result was created on or after 1 September

#### Scenario: Newest first

- **WHEN** a user searches with the newest-first option
- **THEN** the results are ordered by created time, newest first

### Requirement: Search sees only the user's own thoughts

A search SHALL only ever return thoughts the searching user owns, whatever the query and filters.

#### Scenario: Two users with similar thoughts

- **WHEN** two users each store a thought about milk and one of them searches for `milk`
- **THEN** the results hold only that user's thought

### Requirement: Search keeps working without the embedding provider

A search SHALL embed the query through the embedding model recorded with the user's index, with the searching user's own key for that provider. When the query cannot be embedded, for a missing or refused key, an unreachable provider, or a rate limit, the search SHALL return the matches by words alone and SHALL say that it did so and why, naming the provider. A user with no thoughts SHALL get an empty result without any provider call.

#### Scenario: No key for the embedding provider

- **WHEN** a user with thoughts but no saved key for the embedding provider searches for a word in one of their titles
- **THEN** the result holds that thought
- **AND** says it matched by words only because a key for that provider is missing

#### Scenario: No thoughts yet

- **WHEN** a user who has never stored a thought searches
- **THEN** the result is empty and no provider is called

### Requirement: No search across embedding models

Before comparing vectors, the system SHALL check that the query was embedded with the model and to the dimension recorded for the user's index. On a mismatch it SHALL NOT compare vectors: it SHALL return the matches by words alone, say that the search index must be rebuilt, and log the mismatch for the operator.

#### Scenario: Dimension changed

- **WHEN** the provider returns a query vector whose dimension differs from the one recorded for the user's index
- **THEN** no vectors are compared, the result holds only matches by words, and it says the index must be rebuilt

### Requirement: Compact results

Each result SHALL carry the thought's id, title, tags, created date, and summary, and, when the best match came from the raw text, a short excerpt around it instead of the raw text. The whole result SHALL fit within a configured size budget: results SHALL be added best first until the next one would pass it, and a summary longer than a configured length SHALL be shortened with a mark that it was cut.

#### Scenario: Budget reached

- **WHEN** a search matches ten thoughts with long summaries and the budget fits four
- **THEN** the result holds the four best, and says that more matched

#### Scenario: Excerpt from raw text

- **WHEN** a thought is found through a detail in its raw text
- **THEN** its result holds a short excerpt around that detail, and not the whole raw text

### Requirement: Search is fast

For a user with 5,000 thoughts, the database part of a search, from the query vector to the ranked results, SHALL take under 50 milliseconds at the 95th percentile on the reference compose setup. The embedding call for the query SHALL be the only network call a search makes.

#### Scenario: Large collection

- **WHEN** a user with 5,000 thoughts searches 100 times on the reference setup
- **THEN** 95 of the searches spend under 50 milliseconds in the database
