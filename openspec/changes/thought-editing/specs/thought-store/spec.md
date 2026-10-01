## MODIFIED Requirements

### Requirement: Store, update, and delete keep search in step

A thought and its search entries SHALL be written and deleted together, so search never returns a thought that is not stored and never misses one by its words. Storing a thought SHALL make it findable by its words at once and by its meaning once its embeddings exist. Updating a thought's title, summary, or raw text SHALL make search find it by its new content and not its old. Updating only tags SHALL embed only the thought's first entry again. Updating only the category SHALL NOT need a new embedding. Deleting a thought SHALL remove it and all its search entries.

#### Scenario: Stored and found

- **WHEN** a user stores a thought titled `Oat milk` and then searches for `milk`
- **THEN** the search finds that thought

#### Scenario: Reworded

- **WHEN** a user changes a thought's summary from `buy oat milk` to `book the dentist` and then searches for `dentist`
- **THEN** the search finds the thought, and a search for `oat milk` no longer finds it by that summary

#### Scenario: Deleted

- **WHEN** a user deletes a thought and then searches for its title
- **THEN** the search does not return it

#### Scenario: Tags or category only

- **WHEN** a user changes only a thought's tags
- **THEN** one embedding call is made, for the thought's first entry only
- **AND** when the user then changes only its category, no embedding call is made
