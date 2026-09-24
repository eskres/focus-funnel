# Spec Delta

## Purpose

Keeps each user's filed thoughts durably in the database, which is the source of truth, and keeps each thought's search entries in step with it.

## ADDED Requirements

### Requirement: A thought belongs to one user

The system SHALL store each thought with its owner, a title, a summary, tags, an optional category, the optional raw text it came from, and the times it was created and last updated. Every thought SHALL belong to exactly one user. Another user asking for it SHALL get the same answer as for a thought that does not exist.

#### Scenario: Stored thought

- **WHEN** a thought with a title, a summary, and two tags is stored for a user
- **THEN** it can be read back with the same title, summary, and tags, its owner, and its created and updated times

#### Scenario: Another user's thought

- **WHEN** a user asks for, updates, or deletes a thought another user owns
- **THEN** the system answers as if the thought did not exist
- **AND** the other user's thought is unchanged

### Requirement: Thought fields are checked

The system SHALL refuse a thought with an empty title or summary, a title over 200 characters, a summary over 4,000 characters, raw text over 20,000 characters, more than 20 tags, or a tag over 50 characters, and SHALL name the field. Tags SHALL be trimmed and lowercased, and duplicate or empty tags SHALL be dropped.

#### Scenario: Empty summary

- **WHEN** a thought with a summary made only of whitespace is stored
- **THEN** the system refuses it naming the summary, and nothing is stored

#### Scenario: Tags cleaned

- **WHEN** a thought is stored with the tags ` Milk`, `milk`, and an empty tag
- **THEN** the thought has the single tag `milk`

### Requirement: Store, update, and delete keep search in step

A thought and its search entries SHALL be written and deleted together, so search never returns a thought that is not stored and never misses one by its words. Storing a thought SHALL make it findable by its words at once and by its meaning once its embeddings exist. Updating a thought's title, summary, or raw text SHALL make search find it by its new content and not its old. Updating only tags or category SHALL NOT need a new embedding. Deleting a thought SHALL remove it and all its search entries.

#### Scenario: Stored and found

- **WHEN** a user stores a thought titled `Oat milk` and then searches for `milk`
- **THEN** the search finds that thought

#### Scenario: Reworded

- **WHEN** a user changes a thought's summary from `buy oat milk` to `book the dentist` and then searches for `dentist`
- **THEN** the search finds the thought, and a search for `oat milk` no longer finds it by that summary

#### Scenario: Deleted

- **WHEN** a user deletes a thought and then searches for its title
- **THEN** the search does not return it

### Requirement: A provider failure never loses a thought

Storing or updating a valid thought SHALL succeed even when its embedding call fails. The thought SHALL then be findable by its words at once. Its missing embeddings SHALL be created on the user's next store or search that can reach the provider, or by the rebuild job, without the user doing anything.

#### Scenario: Provider down while storing

- **WHEN** a user stores a thought while the embedding provider is unreachable
- **THEN** the thought is stored and a search for a word in its title finds it

#### Scenario: Filled in later

- **WHEN** the provider is reachable again and the user searches
- **THEN** the stored thought gets its embeddings and is found by meaning from then on

#### Scenario: No key

- **WHEN** a user without a key for the embedding provider stores a thought
- **THEN** the thought is stored and is findable by its words
