## ADDED Requirements

### Requirement: A proposal can mark a thought done

A proposal part SHALL be able to mark done a thought the conversation has seen, instead of filing a new thought. Such a part SHALL change nothing until the user confirms its card. Confirming it SHALL set the thought's status to `done` and SHALL change nothing else about the thought. Confirming the same card again SHALL NOT change the thought again, and SHALL answer as the first confirm did.

#### Scenario: Confirm marks done

- **WHEN** a proposal marks the open task `Call the plumber` done and the user confirms the card
- **THEN** the task's status is `done`
- **AND** its title, summary, tags, and category are unchanged

#### Scenario: Not confirmed

- **WHEN** a proposal marks `Call the plumber` done and the user carries on talking without confirming
- **THEN** the task stays `open`

#### Scenario: Confirmed twice

- **WHEN** a user confirms a card that marks a task done, and the confirm request is sent a second time
- **THEN** the task is done, the time of its status change is that of the first confirm, and both answers say it was marked done

### Requirement: A status change for a missing thought is refused

A confirm of a status part whose thought was deleted, or belongs to another user, SHALL change nothing and SHALL say that the thought no longer exists, with the same answer in both cases. A confirm of a status part whose thought is already done SHALL succeed and SHALL change nothing. A status part whose thought no longer exists SHALL NOT keep its proposal held, and SHALL NOT be offered or listed to the model as waiting for the user.

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

#### Scenario: Deleted thought does not stay held

- **WHEN** a proposal's only unconfirmed part marks a task done, and the user deletes that task and then runs `/compact`
- **THEN** no proposal is offered for it, and the note to the model lists no proposal waiting for the user

### Requirement: A status change does not count as filing

A confirmed part that marked a thought done SHALL NOT count as a saved proposal for the raw text of a later proposal, for the offer before archive and `/compact`, or for the list of thoughts filed from the conversation. Only parts that filed a new thought or added to one SHALL count.

#### Scenario: Discussion before a status card is still offered

- **WHEN** a user discusses an idea for a podcast, then sends `I called the plumber`, confirms only the card that marks `Call the plumber` done, and runs `/compact`
- **THEN** the model is asked for a proposal before compacting, and the podcast discussion can be offered

#### Scenario: Raw text keeps the discussion

- **WHEN** after that status card, the model proposes a thought about the podcast idea and the user confirms it
- **THEN** its raw text starts with the user's first message about the podcast

#### Scenario: Not listed as filed

- **WHEN** a conversation's only confirmed part marked `Call the plumber` done
- **THEN** the model is not told that `Call the plumber` was filed from this conversation

### Requirement: A status part is confirmed on its own

Merging SHALL NOT be offered when any part of a proposal sets a status. The system SHALL refuse a confirm that merges a status part with other parts, and nothing SHALL be stored or changed. Each other part of such a proposal SHALL be confirmed on its own, as a new thought or an addition.

#### Scenario: Status part and a new thought

- **WHEN** a proposal has a part that marks `Call the plumber` done and a part that proposes `Buy oat milk`
- **THEN** the chat shows two cards and no merge button
- **AND** confirming the second card stores `Buy oat milk` and leaves `Call the plumber` open

#### Scenario: Merge request

- **WHEN** a confirm request names every part of a proposal that has a status part
- **THEN** the system refuses it, and nothing is stored or changed
