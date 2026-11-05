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

A confirm of a status part whose thought was deleted, or belongs to another user, SHALL change nothing and SHALL say that the thought no longer exists, with the same answer in both cases. A confirm of a status part whose thought is already done SHALL succeed and SHALL change nothing.

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

### Requirement: A status change does not block an addition

A change of status SHALL NOT count as a change to the thought when an addition to it is confirmed or when its last addition is undone. Confirming an addition SHALL keep the thought's status, and undoing an addition SHALL keep the thought's status and the time of its last status change.

#### Scenario: Marked done, then an addition confirmed

- **WHEN** a proposal adds to the task `Call the plumber`, the user then marks the task done in the sheet, and then confirms the addition
- **THEN** the addition is saved
- **AND** the task is still done

#### Scenario: Addition, marked done, then undone

- **WHEN** a user confirms an addition to `Call the plumber`, marks the task done, and then undoes the addition
- **THEN** the undo succeeds and restores the thought as it was before the addition
- **AND** the task is still done

## MODIFIED Requirements

### Requirement: A message with several thoughts is split

When a message or discussion holds several separate thoughts, the model SHALL propose each as its own part, in one proposal, and the chat SHALL show one card per part. Each part SHALL be confirmed on its own and SHALL keep the whole raw text of the proposal. Before any part is saved, the user SHALL be able to merge all the parts into one card, with no model call: the first part's title and category, the summaries as paragraphs in order, and the tags of every part without repeats. The merged card SHALL be edited and confirmed like any other card and SHALL store one thought. Merging SHALL NOT be offered when any part of the proposal is an addition to a filed thought or marks a thought done. The system SHALL refuse a confirm that merges a part that marks a thought done with other parts, and nothing SHALL be stored or changed.

#### Scenario: Three things in one message

- **WHEN** a user sends `/push buy oat milk, book the dentist, and idea: a podcast about maps`
- **THEN** the chat shows three cards, one per thing
- **AND** nothing is stored yet

#### Scenario: Confirm one part

- **WHEN** a user confirms the second of three cards
- **THEN** one thought is stored, and the other two cards still wait

#### Scenario: Merge

- **WHEN** a user merges two cards titled `Oat milk` and `Eggs` with the tags `groceries` and `groceries, breakfast`
- **THEN** one card shows the title `Oat milk`, both summaries, and the tags `groceries` and `breakfast`
- **AND** confirming it stores one thought

#### Scenario: Merge after a part is saved

- **WHEN** one of three cards is already saved
- **THEN** the merge button is not offered

#### Scenario: One thing

- **WHEN** a user sends `/push buy oat milk`
- **THEN** the chat shows one card and no merge button

#### Scenario: A part is an addition

- **WHEN** a proposal has two parts and one of them adds to a filed thought
- **THEN** the merge button is not offered

#### Scenario: Status part and a new thought

- **WHEN** a proposal has a part that marks `Call the plumber` done and a part that proposes `Buy oat milk`
- **THEN** the chat shows two cards and no merge button
- **AND** confirming the second card stores `Buy oat milk` and leaves `Call the plumber` open

#### Scenario: Merge request

- **WHEN** a confirm request names every part of a proposal that has a part that marks a thought done
- **THEN** the system refuses it, and nothing is stored or changed
