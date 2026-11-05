## ADDED Requirements

### Requirement: The model proposes marking thoughts done

The proposal tool SHALL let the model name, by its ref, a thought the conversation has seen, to mark it done, beside or instead of new thoughts and additions, in the same proposal. The system SHALL steer the model to propose such a mark when the user says they finished a thing the conversation has seen.

#### Scenario: I called the plumber

- **WHEN** a conversation filed the task `Call the plumber`, and the user then sends `I called the plumber`
- **THEN** the model makes a proposal with one part that marks `Call the plumber` done
- **AND** the task is still open

#### Scenario: Done and something new

- **WHEN** a conversation has seen the task `Call the plumber`, and the user sends `I called the plumber, and I need to buy oat milk`
- **THEN** the model makes one proposal with two parts: one that marks `Call the plumber` done, and one new thought about oat milk

### Requirement: A mark carries only a ref

A mark SHALL carry nothing but the ref of the thought to mark done. A mark that also carries an addition SHALL be refused as a tool call the model can correct, and nothing SHALL be stored for it. A mark SHALL NOT go through the similar-thought check, and SHALL need no embedding call.

#### Scenario: A mark that carries an addition

- **WHEN** the model sends a mark for `Call the plumber` that also carries a summary to add to it
- **THEN** no proposal is stored, and the tool result tells the model to send the addition as its own part

#### Scenario: Only new parts are checked

- **WHEN** a proposal marks `Call the plumber` done and proposes a new thought about oat milk
- **THEN** only the oat milk part goes through the similar-thought check, and the plumber task is not offered as a similar thought

#### Scenario: Only a mark

- **WHEN** a proposal only marks `Call the plumber` done
- **THEN** the card is shown with no similar-thought check and no embedding call

### Requirement: The reply does not claim a mark was made

After a proposal with a mark, the tool result SHALL tell the model that nothing changes until the user confirms. The model's reply SHALL NOT say that the thought was marked done, closed, or finished.

#### Scenario: Reply before confirm

- **WHEN** the model proposes marking `Call the plumber` done
- **THEN** its reply says the change is ready to confirm, and does not say the task was marked done

### Requirement: The model finds a finished task it has not seen

When the user says they finished a thing the conversation has not seen, the system SHALL steer the model to search the user's open thoughts for it first, and then to propose the mark by the ref the search gave. When that search finds no open thought for it, the model SHALL NOT propose a mark. A turn SHALL have enough rounds for a refused proposal, a search, a second proposal, and the reply.

#### Scenario: Task filed in another conversation

- **WHEN** a user filed `Call the plumber` in another conversation, and sends `I called the plumber` in a new one
- **THEN** the model searches with the status `open`, and then proposes marking `Call the plumber` done

#### Scenario: Nothing open matches

- **WHEN** a user has no open thought about a plumber and sends `I called the plumber`
- **THEN** no card marks any thought done

#### Scenario: Guessed ref, then search

- **WHEN** the model first proposes a mark on a ref the conversation has not seen, and the user filed `Call the plumber` elsewhere
- **THEN** the model can still search, propose marking `Call the plumber` done, and reply in the same turn

### Requirement: A mark the system cannot apply goes back to the model

A mark whose ref the conversation has not seen, whose thought no longer exists, or whose thought is already done, and two marks that name the same thought, SHALL be refused as a tool call the model can correct in its next round. Nothing SHALL be stored for that call. The tool result SHALL say why and what to do next, and SHALL NOT tell the model to propose again when it should tell the user instead.

#### Scenario: Ref not seen

- **WHEN** the model proposes marking done a ref that this conversation has not seen
- **THEN** no proposal is stored, and the tool result tells the model to search for the thought first

#### Scenario: Already done

- **WHEN** the model proposes marking done a thought that is already done
- **THEN** no proposal is stored, and the tool result says the thought is already done and tells the model to tell the user so

#### Scenario: Thought deleted

- **WHEN** the model proposes marking done a ref whose thought was deleted
- **THEN** no proposal is stored, and the tool result says the thought no longer exists

#### Scenario: Same thought twice

- **WHEN** one proposal call has two marks that name the same ref
- **THEN** no proposal is stored, and the tool result says the thought was named twice

### Requirement: A mark that cannot apply is left out of the offer

In the offer before archive or `/compact`, a mark that cannot apply SHALL be left out and the rest of the proposal offered. When nothing is left, nothing SHALL be offered and the action SHALL go ahead. Such a mark SHALL NOT make the action fail.

#### Scenario: Offer with a task already done

- **WHEN** before `/compact` the model's offered proposal marks done a task that is already done, and proposes nothing else
- **THEN** nothing is offered, and the conversation is compacted

#### Scenario: Offer with a bad mark and a new thought

- **WHEN** before archive the model's offered proposal marks done a ref the conversation has not seen and proposes a new thought
- **THEN** the offer shows only the new thought

### Requirement: The model knows which thoughts are done

The search tool result and the note of thoughts the conversation has seen SHALL say which thoughts are done, and SHALL say nothing for an open one. The note about a held proposal SHALL list each unconfirmed mark with the thought's ref and title.

#### Scenario: Done in a search result

- **WHEN** a search returns the done task `Buy oat milk` and the open task `Call the plumber`
- **THEN** the tool result marks `Buy oat milk` as done and does not mark `Call the plumber`

#### Scenario: Held mark

- **WHEN** a proposal that marks `Call the plumber` done is held and the user sends another message
- **THEN** the note to the model about the held proposal lists that mark with its ref and its title

### Requirement: The search tool filters by status and category

The search tool SHALL take an optional status, `open` or `done`, and an optional category, and the query SHALL be optional when either is given. The system SHALL steer the model to pass the status `open` when the user asks what is open, left, or still to do, with the category `task` when they ask about tasks, and to pass no status when the user asks about a thing whatever its status.

#### Scenario: What tasks are still open

- **WHEN** a user with the open task `Call the plumber` and the done task `Buy oat milk` asks `what tasks are still open?`
- **THEN** the model calls the search tool with the status `open` and the category `task`
- **AND** the tool result holds `Call the plumber` and not `Buy oat milk`

#### Scenario: Did I do it

- **WHEN** a user with the done task `Buy oat milk` asks `did I buy the oat milk?`
- **THEN** the model calls the search tool with no status
- **AND** the tool result holds `Buy oat milk`, marked as done
