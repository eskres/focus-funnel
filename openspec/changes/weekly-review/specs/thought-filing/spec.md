## MODIFIED Requirements

### Requirement: A status change for a missing thought is refused

A confirm of a status part whose thought was deleted, or belongs to another user, SHALL change nothing and SHALL say that the thought no longer exists, with the same answer in both cases. A confirm of a status part whose thought is already done SHALL succeed and SHALL change nothing. A confirm of a status part whose thought is archived, for example archived after the card was shown, SHALL be refused, SHALL change nothing, SHALL say that the thought is archived and must be restored first, and SHALL leave the card confirmable.

#### Scenario: Deleted before confirming

- **WHEN** a user deletes a task and then confirms a card that marks it done
- **THEN** nothing is changed, and the card says the thought no longer exists

#### Scenario: Another user's thought

- **WHEN** a confirm names a status part whose thought belongs to another user
- **THEN** the answer is the same as for a deleted thought
- **AND** the other user's thought is still open

#### Scenario: Already done in the sheet

- **WHEN** a user marks a task done in the sheet and then confirms a card that marks it done
- **THEN** the card shows that it was marked done, and the task is unchanged by the confirm

#### Scenario: Archived before the mark is confirmed

- **WHEN** the model proposes marking the open idea `Podcast about maps` done, the user archives it from its resurfaced notification, and then confirms the card
- **THEN** the idea is still archived, with the time of its archiving, and the card says `This thought is archived. Restore it first.` and still has its `Mark done` button

#### Scenario: Restored, then confirmed

- **WHEN** the user then restores the idea and confirms the same card
- **THEN** the idea is done, and the card says it was marked done
