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

When a message or discussion holds several separate thoughts, the model SHALL propose each as its own part, in one proposal, and the chat SHALL show one card per part. Each part SHALL be confirmed on its own, and each part that files a thought or adds to one SHALL keep the whole raw text of the proposal. Before any part is saved, the user SHALL be able to merge all the parts into one card, with no model call: the first part's title and category, the summaries as paragraphs in order, and the tags of every part without repeats. The merged card SHALL be edited and confirmed like any other card and SHALL store one thought. Merging SHALL NOT be offered when any part of the proposal is an addition to a filed thought or marks a thought done. The system SHALL refuse a confirm that merges a part that marks a thought done with other parts, and nothing SHALL be stored or changed.

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
- **AND** confirming the `Buy oat milk` card stores `Buy oat milk` and leaves `Call the plumber` open

#### Scenario: Merge request

- **WHEN** a confirm request names every part of a proposal that has a part that marks a thought done
- **THEN** the system refuses it, and nothing is stored or changed

### Requirement: Confirming a proposal saves it

When the user confirms a proposal card, the system SHALL store a thought with the card's title, summary, tags, and category as the user left them, and the raw text of the proposal. The card SHALL then show that the thought was saved, with a link that opens it. Confirming the same card again SHALL NOT store a second thought. A card the store refuses SHALL name the field and keep the user's text, and nothing SHALL be stored. A failed embedding call SHALL NOT fail the save. A card for a part that marks a thought done SHALL store no thought: confirming it SHALL change the thought's status as "A proposal can mark a thought done" says, and the card SHALL then show that the thought was marked done, with a link that opens it.

#### Scenario: Confirm

- **WHEN** a user confirms a proposal titled `Oat milk` with the tag `groceries`
- **THEN** a thought titled `Oat milk` with the tag `groceries` is stored for that user
- **AND** the card shows that it was saved, with a link to the thought

#### Scenario: Edited before confirming

- **WHEN** a user changes the title, removes a tag, and picks another category, then confirms
- **THEN** the stored thought has the changed title, tags, and category

#### Scenario: Confirmed twice

- **WHEN** a user confirms a card, and the confirm request is sent a second time
- **THEN** only one thought is stored
- **AND** the second answer links to the same thought

#### Scenario: Refused field

- **WHEN** a user confirms a card with a title over 200 characters
- **THEN** the card says the title is too long and keeps the text
- **AND** nothing is stored

#### Scenario: Embedding provider down

- **WHEN** a user confirms a card while the embedding provider cannot be reached
- **THEN** the thought is saved and the card shows it as saved

#### Scenario: Another user's proposal

- **WHEN** a user confirms a proposal from a conversation another user owns
- **THEN** the system answers as if the conversation did not exist, and nothing is stored

#### Scenario: Status card stores no thought

- **WHEN** a user confirms a card that marks `Call the plumber` done
- **THEN** no thought is stored, and `Call the plumber` is done
- **AND** the card shows that it was marked done, with a link to the thought

### Requirement: Similar filed thoughts are checked

Before a new thought is proposed, the system SHALL look for similar thoughts among all the user's thoughts, in every conversation and of any age, by meaning and by words. The age of a thought SHALL NOT count against it. When it finds candidates, the model SHALL decide, in the same turn, whether each new part adds to one of them, stays new, or, when the user says they finished that candidate, is dropped and the candidate is marked done. When the model keeps a part new but a strong match exists, the card SHALL name the match and offer to add to it instead, except for a part with the category `task`. The check SHALL work with any embedding model, including one the system has no setting for, and SHALL work by words alone when search by meaning cannot run. The check SHALL NOT store or change anything.

#### Scenario: Revisited after a year

- **WHEN** a user filed `Podcast about maps` a year ago and now, in a new conversation, discusses making a podcast on cartography until the model proposes a thought
- **THEN** the proposal adds to `Podcast about maps`, or its card offers to add to it

#### Scenario: Same topic, different thing

- **WHEN** a user has a thought about buying a bike lock and now decides which bike to buy
- **THEN** the model keeps the new thought separate

#### Scenario: Repeated task

- **WHEN** a user has a task `Buy oat milk` from last month and sends `/push buy oat milk`
- **THEN** the card is a new task, with no offer to add to the old one

#### Scenario: No key for the embedding provider

- **WHEN** a user with no key for the embedding provider proposes a thought whose title shares its words with a filed thought
- **THEN** the check still finds the filed thought by its words

#### Scenario: Finished candidate marked done

- **WHEN** the model proposes a new note `Called the plumber`, the check lists the open task `Call the plumber`, and the user's message says they called the plumber
- **THEN** the model drops the note and proposes marking `Call the plumber` done, as the `conversation-agent` scenario "Finished task listed as a similar thought" says
