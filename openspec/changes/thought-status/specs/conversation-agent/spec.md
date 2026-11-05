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

A mark SHALL carry nothing but the ref of the thought to mark done. A call that only marks thoughts done SHALL be accepted without a list of new thoughts. Two marks with the same ref in one call SHALL be read as one. A mark that also carries an addition SHALL be refused as a tool call the model can correct, and nothing SHALL be stored for it.

#### Scenario: A mark that carries an addition

- **WHEN** the model sends a mark for `Call the plumber` that also carries a summary to add to it
- **THEN** no proposal is stored, and the tool result tells the model to send the addition as its own part

#### Scenario: Only a mark, with no new thoughts

- **WHEN** the model calls the proposal tool with only a mark for `Call the plumber` and no list of new thoughts
- **THEN** one card is shown that marks `Call the plumber` done

#### Scenario: Same thought twice

- **WHEN** one proposal call has two marks that name the same ref
- **THEN** one card is shown for that thought

### Requirement: Marks stay out of the similar-thought check

A mark SHALL NOT go through the similar-thought check, and SHALL need no embedding call. A mark that cannot apply SHALL be refused before the similar-thought check runs. When the similar-thought check asks the model about a call's new parts, the tool result SHALL tell the model to send the call's marks again.

#### Scenario: Only new parts are checked

- **WHEN** a proposal marks `Call the plumber` done and proposes a new thought about oat milk
- **THEN** only the oat milk part goes through the similar-thought check, and the plumber task is not offered as a similar thought

#### Scenario: Only a mark

- **WHEN** a proposal only marks `Call the plumber` done
- **THEN** the card is shown with no similar-thought check and no embedding call

#### Scenario: Mark kept through a similar-thought question

- **WHEN** a proposal marks `Call the plumber` done and proposes a new thought about oat milk that has a similar filed thought
- **THEN** no proposal is shown yet, and the tool result asks about the oat milk part and tells the model to send the marks again
- **AND** when the model answers with both, the proposal shown marks `Call the plumber` done

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

A mark whose ref the conversation has not seen, whose thought no longer exists, or whose thought is already done SHALL be refused as a tool call the model can correct in its next round. Nothing SHALL be stored for that call, and a held proposal SHALL stay held, with its note still in front of the model. The tool result SHALL say why and what to do next, and SHALL NOT tell the model to propose again when it should tell the user instead.

#### Scenario: Ref not seen

- **WHEN** the model proposes marking done a ref that this conversation has not seen
- **THEN** no proposal is stored, and the tool result tells the model to search for the thought first

#### Scenario: Already done

- **WHEN** the model proposes marking done a thought that is already done
- **THEN** no proposal is stored, and the tool result says the thought is already done and tells the model to tell the user so

#### Scenario: Thought deleted

- **WHEN** the model proposes marking done a ref whose thought was deleted
- **THEN** no proposal is stored, and the tool result says the thought no longer exists

#### Scenario: Refused mark keeps the held proposal

- **WHEN** a proposal about oat milk is held, and in a later turn the model's proposal is refused for a mark whose ref the conversation has not seen
- **THEN** the oat milk proposal is still held, and the model is still told about it in its next round

### Requirement: The model knows which thoughts are done

The search tool result, the note of thoughts the conversation has seen, and the list of similar thoughts the similar-thought check gives back SHALL say which thoughts are done, and SHALL say nothing for an open one.

#### Scenario: Done in a search result

- **WHEN** a search returns the done task `Buy oat milk` and the open task `Call the plumber`
- **THEN** the tool result marks `Buy oat milk` as done and does not mark `Call the plumber`

#### Scenario: Done in the seen-thoughts note

- **WHEN** a conversation has seen `Buy oat milk`, which is done, and `Call the plumber`, which is open
- **THEN** the note to the model marks `Buy oat milk` as done and does not mark `Call the plumber`

#### Scenario: Done in the similar-thought question

- **WHEN** the similar-thought check finds the done task `Buy oat milk` and the open task `Buy eggs` for a new part about milk
- **THEN** the tool result that asks about them marks `Buy oat milk` as done and does not mark `Buy eggs`

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

## MODIFIED Requirements

### Requirement: A proposal is held while the conversation carries on

When the user carries on the conversation after a proposal was made, the proposal SHALL be held until every part of it is saved or a later proposal replaces it: the system SHALL NOT propose the same conclusion again on each turn. Only the parts not yet saved SHALL be held. A part that marks a thought done SHALL NOT be held: it SHALL NOT keep its proposal held, SHALL NOT be offered again, and SHALL NOT be folded away by a later proposal, and its card SHALL stay confirmable. A proposal whose only parts mark thoughts done SHALL NOT replace a held proposal. A proposal offered before archive or `/compact` SHALL NOT hold a part that marks a thought done; when nothing else is left, nothing SHALL be offered and the action SHALL go ahead. A held proposal SHALL be offered again, with a summary that covers what was added, in three cases: the conversation veers onto a different topic, the user archives the conversation or leaves it, and the user sends `/compact`. Time SHALL NOT bring it back: opening an old conversation SHALL NOT show the proposal again by itself. On a change of topic the system SHALL offer the earlier summary before the new topic continues. A card of a proposal that is no longer held SHALL still be confirmable. When a later proposal replaces a held one, the earlier proposal's unsaved cards SHALL be folded away with a note that a newer proposal replaced them, and the user SHALL be able to show them again.

#### Scenario: User carries on

- **WHEN** a user keeps discussing the same topic after a proposal was shown
- **THEN** the chat does not show the proposal again

#### Scenario: Topic changes

- **WHEN** a user with a held proposal sends a message about an unrelated topic
- **THEN** the chat offers the held summary first
- **AND** the new topic then continues

#### Scenario: Archive with a held proposal

- **WHEN** a user archives a conversation that has a held proposal
- **THEN** the chat offers the proposal before archiving

#### Scenario: Compact with a held proposal

- **WHEN** a user sends `/compact` with a held proposal
- **THEN** the chat offers the proposal before compacting

#### Scenario: Returning to an old conversation

- **WHEN** a user opens a conversation with a held proposal after a long time and carries on
- **THEN** the conversation continues as normal and the proposal is not shown again by itself

#### Scenario: Not suggesting deletion

- **WHEN** a proposal is offered
- **THEN** the offer does not suggest deleting the conversation

#### Scenario: Every part saved

- **WHEN** a user saves both parts of a two-part proposal and then archives the conversation
- **THEN** no proposal is offered before archiving

#### Scenario: One part left

- **WHEN** a user saves one part of a two-part proposal and then sends `/compact`
- **THEN** the chat offers only the part not saved

#### Scenario: Replaced card folded

- **WHEN** the chat offers a held proposal again on a change of topic, as a new proposal
- **THEN** the earlier card is folded away with a note that a newer proposal replaced it
- **AND** the user can show it and confirm it

#### Scenario: Older card confirmed

- **WHEN** a user confirms a card from a proposal that a later proposal replaced
- **THEN** that card's thought is saved

#### Scenario: Unconfirmed mark is not offered again

- **WHEN** the model proposed marking `Call the plumber` done, the user did not confirm the card, and then sends a message about something else and runs `/compact`
- **THEN** the mark is not proposed again on the change of topic, and no proposal with it is offered before compacting

#### Scenario: Mark card not folded away

- **WHEN** a proposal marks `Call the plumber` done and proposes `Buy oat milk`, the user confirms neither, and a later proposal replaces it
- **THEN** the oat milk card is folded away, and the `Call the plumber` card is still shown and can still be confirmed

#### Scenario: Rest of the proposal saved

- **WHEN** a proposal marks `Call the plumber` done and proposes `Buy oat milk`, and the user confirms only the oat milk card
- **THEN** no proposal is held, and the plumber card can still be confirmed

#### Scenario: Offer leaves marks out

- **WHEN** before archive the model's offered proposal marks `Call the plumber` done and proposes a new thought
- **THEN** the offer shows only the new thought

#### Scenario: Offer with only a mark

- **WHEN** before `/compact` the model's offered proposal only marks a task done
- **THEN** nothing is offered, and the conversation is compacted
