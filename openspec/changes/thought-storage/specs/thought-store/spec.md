# Spec Delta

## Purpose

Keeps each user's filed thoughts durably in the database, which is the source of truth, and keeps each thought's search entry in step with it.

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

Storing a thought SHALL make it findable by search. Updating a thought's title or summary SHALL make search find it by its new wording and not its old. Updating only tags, category, or raw text SHALL NOT need a new embedding. Deleting a thought SHALL remove it from the database and from search. When the embedding call fails, storing and updating SHALL fail with the provider error and leave the thought as it was.

#### Scenario: Stored and found

- **WHEN** a user stores a thought titled `Oat milk` and then searches for `milk`
- **THEN** the search finds that thought

#### Scenario: Reworded

- **WHEN** a user changes a thought's summary from `buy oat milk` to `book the dentist` and then searches for `dentist`
- **THEN** the search finds the thought

#### Scenario: Deleted

- **WHEN** a user deletes a thought and then searches for its title
- **THEN** the search does not return it

#### Scenario: Embedding fails while storing

- **WHEN** the embedding provider is unreachable while a thought is stored
- **THEN** storing fails with `provider_unreachable` and no thought is stored

### Requirement: The database is the source of truth

Search results SHALL be built from the thoughts in the database. A search entry with no matching thought in the database SHALL NOT be returned. The search index SHALL be rebuildable from the database alone.

#### Scenario: Leftover search entry

- **WHEN** the search index holds an entry for a thought that is no longer in the database
- **THEN** a search never returns that entry
