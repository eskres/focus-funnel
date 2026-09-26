## MODIFIED Requirements

### Requirement: A message with several thoughts is split

When a message or discussion holds several separate thoughts, the model SHALL propose each as its own part, in one proposal, and the chat SHALL show one card per part. Each part SHALL be confirmed on its own and SHALL keep the whole raw text of the proposal. Before any part is saved, the user SHALL be able to merge all the parts into one card, with no model call: the first part's title and category, the summaries as paragraphs in order, and the tags of every part without repeats. The merged card SHALL be edited and confirmed like any other card and SHALL store one thought. Merging SHALL NOT be offered when any part of the proposal is an addition to a filed thought.

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

## ADDED Requirements

### Requirement: A proposal can add to a filed thought

A proposal part SHALL be able to add to a thought the conversation has seen: one filed from it, added to from it, or returned by one of its searches or similar-thought checks. The model SHALL name such a thought by a short ref, never by its id. A ref SHALL name the same thought for the whole life of the conversation, and SHALL NOT be given to another thought after that thought is deleted. A ref the conversation has not seen, or one whose thought is gone, SHALL make the part a new thought. Two parts of one proposal SHALL NOT add to the same thought. Confirming an addition SHALL change the thought's summary, tags, and category to the card's values as the user left them, SHALL keep its title, SHALL extend its raw text, and SHALL keep search in step with the new content. The user SHALL be able to file the card as a new thought instead. A confirm SHALL be refused, with the thought's current version, when the thought changed after the addition was proposed. A failed embedding call SHALL NOT fail an addition.

#### Scenario: Follow-up in the same conversation

- **WHEN** a user files `Buy new bike lock` with `/push`, then discusses lock colours and prices, and the model makes a proposal
- **THEN** the proposal adds to `Buy new bike lock` instead of proposing a new thought

#### Scenario: Confirm an addition

- **WHEN** a user confirms an addition with a new summary and the tag `security` added
- **THEN** the thought has the new summary and the tag, and its title is unchanged
- **AND** a search for a word that is only in the new summary finds it

#### Scenario: A thought from another conversation

- **WHEN** a search in a new conversation returns `Podcast about maps`, filed a year ago in another conversation, and the user discusses it further
- **THEN** the proposal can add to `Podcast about maps`

#### Scenario: Ref the conversation has not seen

- **WHEN** the model names a ref that this conversation has not seen
- **THEN** the part is shown as a new thought

#### Scenario: Thought deleted before confirming

- **WHEN** a user deletes the thought and then confirms an addition to it
- **THEN** nothing is changed, the card says the thought no longer exists, and it offers to file the card as a new thought

#### Scenario: Thought changed after the proposal

- **WHEN** a user edits the thought's summary in the detail view and then confirms an addition proposed before the edit
- **THEN** the confirm is refused and the card shows the current summary to review
- **AND** the user's edit is kept

#### Scenario: File as new instead

- **WHEN** a user chooses to file an addition card as a new thought and confirms it
- **THEN** a new thought is stored and the thought the card named is unchanged

### Requirement: An addition extends the raw text

Confirming an addition SHALL append to the thought's raw text a separator with the date of the addition, then the user's messages that the proposal covers and that the thought does not already hold, chosen by the same rules as a proposal's raw text. When there are no such messages, the raw text SHALL NOT change. The raw text SHALL NOT pass 20,000 characters: the text the thought was first filed with SHALL be kept at the start, cut at its end only when it is longer than half the limit, and the most recent additions SHALL be kept whole where they fit. The oldest additions SHALL be left out first, with a mark where text was left out.

#### Scenario: Appended

- **WHEN** a user confirms an addition after two more messages about the thought
- **THEN** the raw text is the earlier raw text, a dated separator, and those two messages

#### Scenario: No repeat

- **WHEN** a user confirms two additions to the same thought whose proposals cover the same messages
- **THEN** each of those messages is in the raw text once

#### Scenario: Over the limit

- **WHEN** a thought has had so many additions that the next one passes 20,000 characters
- **THEN** the raw text starts with the text it was first filed with, ends with the newest addition, and marks that earlier additions were left out

### Requirement: Similar filed thoughts are checked

Before a new thought is proposed, the system SHALL look for similar thoughts among all the user's thoughts, in every conversation and of any age, by meaning and by words. The age of a thought SHALL NOT count against it. When it finds candidates, the model SHALL decide, in the same turn, whether each new part adds to one of them or stays new. When the model keeps a part new but a strong match exists, the card SHALL name the match and offer to add to it instead, except for a part with the category `task`. The check SHALL work with any embedding model, including one the system has no setting for, and SHALL work by words alone when search by meaning cannot run. The check SHALL NOT store or change anything.

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
