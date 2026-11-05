## ADDED Requirements

### Requirement: The model proposes marking thoughts done

The proposal tool SHALL let the model name, by its ref, a thought the conversation has seen, to mark it done, beside or instead of new thoughts and additions, in the same proposal. The system SHALL steer the model to propose such a mark when the user says they finished a thing the conversation has seen. Before archive and `/compact`, the system SHALL steer the model not to propose a new thought for a finished task that the conversation already proposed to mark done.

#### Scenario: I called the plumber

- **WHEN** a conversation filed the task `Call the plumber`, and the user then sends `I called the plumber`
- **THEN** the model makes a proposal with one part that marks `Call the plumber` done
- **AND** the task is still open

#### Scenario: Done and something new

- **WHEN** a conversation has seen the task `Call the plumber`, and the user sends `I called the plumber, and I need to buy oat milk`
- **THEN** the model makes one proposal with two parts: one that marks `Call the plumber` done, and one new thought about oat milk

#### Scenario: Only a finished task at /compact

- **WHEN** a conversation's only exchange is `I called the plumber` and a confirmed card that marked `Call the plumber` done, and the user sends `/compact`
- **THEN** the model is asked for a proposal, and proposes no new thought about calling the plumber

### Requirement: A mark carries only a ref

A mark SHALL carry nothing but the ref of the thought to mark done. A call that only marks thoughts done SHALL be accepted without a list of new thoughts. Two marks with the same ref in one call SHALL be read as one. A mark that also carries an addition, a summary, or a date SHALL be refused as a tool call the model can correct, and nothing SHALL be stored for it.

#### Scenario: A mark that carries an addition

- **WHEN** the model sends a mark for `Call the plumber` that also carries a summary to add to it
- **THEN** no proposal is stored, and the tool result tells the model to send the addition as its own part

#### Scenario: A mark that carries a date

- **WHEN** the user sends `I called the plumber, he comes Tuesday`, and the model sends a mark for `Call the plumber` that also carries a date, or two dates to choose from
- **THEN** no proposal is stored, and the tool result tells the model to send the date in its own part

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

When the user says they finished a thing the conversation has not seen, the system SHALL steer the model to search the user's open thoughts for it before any proposal in that turn, and then to make one proposal with the mark, by the ref the search gave, and anything else to propose. When the search finds no open thought for it, the model SHALL NOT propose a mark. A turn SHALL have room for a refused proposal, a search, a second proposal, and the reply.

#### Scenario: Task filed in another conversation

- **WHEN** a user filed `Call the plumber` in another conversation, and sends `I called the plumber` in a new one
- **THEN** the model searches with the status `open`, and then proposes marking `Call the plumber` done

#### Scenario: Nothing open matches

- **WHEN** a user has no open thought about a plumber and sends `I called the plumber`
- **THEN** no card marks any thought done

#### Scenario: Unseen finished task and something new

- **WHEN** a user filed `Call the plumber` in another conversation, and sends `I called the plumber, and I need to buy oat milk` in a new one
- **THEN** the model searches with the status `open` before it proposes anything
- **AND** it then makes one proposal that marks `Call the plumber` done and proposes a new thought about oat milk

#### Scenario: Guessed ref, then search

- **WHEN** the model first proposes a mark on a ref the conversation has not seen, and the user filed `Call the plumber` elsewhere
- **THEN** the model can still search, propose marking `Call the plumber` done, and reply in the same turn

### Requirement: A finished task among similar thoughts is marked done

The system SHALL steer the model to send a mark only with a ref the conversation has seen. When the similar-thought check lists an open thought that the user's message says they finished, the system SHALL steer the model to propose marking that thought done, by the ref the check gave, instead of proposing the finished thing as a new thought or as an addition. This SHALL also hold when `/push` forces the turn's first call to be a proposal, so that the search cannot come first.

#### Scenario: Push a finished task the conversation has not seen

- **WHEN** a user filed the open task `Call the plumber` in another conversation, and sends `/push I called the plumber` in a new one
- **THEN** the turn ends with one proposal, and it marks `Call the plumber` done
- **AND** it proposes no new thought about calling the plumber and no addition to `Call the plumber`

#### Scenario: Finished task listed as a similar thought

- **WHEN** the model proposes a new note `Called the plumber`, and the similar-thought check lists the open task `Call the plumber` by its ref
- **THEN** the model's next proposal marks `Call the plumber` done by that ref, and holds no part about calling the plumber

### Requirement: Several open matches mark the newest

When a search for a finished thing finds several open thoughts for it, the system SHALL steer the model to propose marking only the most recently filed one done, and to name the older ones in its reply, so the user can close them from the sheet.

#### Scenario: Several open matches

- **WHEN** a user filed the task `Buy oat milk` in October and again in November, both are open, and the user sends `I bought the oat milk` in a new conversation
- **THEN** the model searches with the status `open`, and then proposes one mark, on the `Buy oat milk` filed in November
- **AND** its reply names the older `Buy oat milk`, so the user can close it from the sheet

### Requirement: The repeated-task line leaves room for a finished task

When the similar-thought check asks about a new part with the category `task`, its line that a repeated task is usually a new task SHALL say that this does not hold when the user says they finished it.

#### Scenario: Finished task question for a task part

- **WHEN** the model's new note about calling the plumber has the category `task`, and the similar-thought check lists the open task `Call the plumber`
- **THEN** the tool result says a repeated task is usually a new task unless the user says they finished it
- **AND** the model's next proposal marks `Call the plumber` done by that ref, and holds no part about calling the plumber

### Requirement: A held part the user finished is not filed

When the user says they finished a thing that is a part of the held proposal that was never confirmed, there is no thought to mark. The system SHALL steer the model to leave that part out of its next proposal, to propose no mark for it, and to tell the user that the card was never filed and can be passed over.

#### Scenario: Finished before it was filed

- **WHEN** a proposal from `/push call the plumber` is held and not confirmed, the user has no filed thought about a plumber, and the user sends `I called the plumber`
- **THEN** no card files `Call the plumber` and no card marks it done
- **AND** the reply says the plumber card was never filed and can be passed over

### Requirement: A finished task with a held proposal

When a proposal is held and the user's message says they finished a thing that is not a part of the held proposal, the system SHALL steer the model to make one proposal that holds the held proposal's parts and the mark. When the thing is not among the thoughts the conversation has seen, the model SHALL first search the user's open thoughts for it, before it proposes the held proposal again.

#### Scenario: Held proposal and an unseen finished task

- **WHEN** a proposal about oat milk is held, and the user sends `I called the plumber` about a task filed in another conversation
- **THEN** the model searches with the status `open` first
- **AND** it then makes one proposal that holds the oat milk part and marks `Call the plumber` done

#### Scenario: Held proposal and a seen finished task

- **WHEN** the conversation filed the task `Call the plumber`, a later proposal about oat milk is held, and the user sends `I called the plumber`
- **THEN** the model makes one proposal that holds the oat milk part and marks `Call the plumber` done
- **AND** it does not first propose the oat milk part alone

### Requirement: A mark the system cannot apply goes back to the model

A mark whose ref the conversation has not seen, whose thought no longer exists, or whose thought is already done SHALL be refused as a tool call the model can correct in its next round. Nothing SHALL be stored for that call, and a held proposal SHALL stay held, with its note still in front of the model. The tool result SHALL say why and what to do next, and SHALL NOT tell the model to propose that mark again when it should tell the user instead.

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

### Requirement: A refused call keeps its other parts

When a proposal call is refused for its marks, the tool result SHALL name every mark of the call that cannot apply, each with its reason, so one more round is enough. When the refused call had other parts, the tool result SHALL tell the model to send them again in one call without the refused marks.

#### Scenario: Refused mark beside a new thought

- **WHEN** the user sends `I called the plumber, and I need to buy oat milk`, the plumber task is already done, and the model proposes the mark and the oat milk part in one call
- **THEN** the call is refused, and the tool result says the plumber task is already done and tells the model to send the oat milk part again without the mark
- **AND** the oat milk part is proposed in the same turn

#### Scenario: Two marks refused

- **WHEN** one proposal call has two marks, one on a deleted thought and one on a thought that is already done
- **THEN** the tool result names both marks, each with its reason

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

The search tool SHALL take an optional status filter, `open`, and an optional category, and the query SHALL be optional when either is given. It SHALL refuse any other status, naming `status`. The system SHALL steer the model to pass the status `open` when the user asks what is open, left, or still to do, with the category `task` when they ask about tasks, and to pass no status when the user asks about a thing whatever its status.

#### Scenario: What tasks are still open

- **WHEN** a user with the open task `Call the plumber` and the done task `Buy oat milk` asks `what tasks are still open?`
- **THEN** the model calls the search tool with the status `open` and the category `task`
- **AND** the tool result holds `Call the plumber` and not `Buy oat milk`

#### Scenario: Did I do it

- **WHEN** a user with the done task `Buy oat milk` asks `did I buy the oat milk?`
- **THEN** the model calls the search tool with no status
- **AND** the tool result holds `Buy oat milk`, marked as done

#### Scenario: Done is not a filter

- **WHEN** the model calls the search tool with the status `done`
- **THEN** the call is refused naming `status`, and the model can call it again

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

#### Scenario: Offer leaves marks out after a similar-thought question

- **WHEN** before archive the offer's similar-thought check lists a filed thought for the model's new part, and the model's second proposal marks `Call the plumber` done and proposes a new thought
- **THEN** the offer shows only the new thought

#### Scenario: Offer with only a mark

- **WHEN** before `/compact` the model's offered proposal only marks a task done
- **THEN** nothing is offered, and the conversation is compacted

### Requirement: Tools to file and find thoughts

The model SHALL be offered two tools: one that searches the user's thoughts, and one that proposes thoughts to file. A proposal SHALL hold one or more parts, each with a title, a summary, tags, and a category. A part SHALL be able to name, by a short ref, a thought the conversation has seen, to add to it instead of filing a new thought. A tool call SHALL NOT store or change anything by itself: a part is stored only when the user confirms it. The result of a tool SHALL be passed back to the model so it can finish its answer, for a bounded number of rounds. After a proposal, the model's reply SHALL NOT say that anything was saved. The search tool SHALL take a query and, optionally, tags and a start date, and SHALL return the user's matching thoughts in the compact form of thought search, or say that none matched. The thoughts a search returns SHALL be passed to the chat as the answer's sources, and SHALL NOT be shown to the model by id; the model SHALL see them by ref. When the search could match only by words, the tool result SHALL say why in plain words and the model SHALL tell the user; the turn SHALL NOT end with an error. Each turn SHALL tell the model which thoughts the conversation has seen, up to a configured number, most recently seen first, each with its ref, title, tags, category, and summary. When the similar-thought check finds candidates for a proposal's new parts, the tool result SHALL list them by ref and ask the model to propose again, marking each new part as an addition or as new; a proposal made after a candidate round in the same turn SHALL be shown without another check; a call that was refused, for a mark or for its arguments, does not count as that proposal.

#### Scenario: Recall question

- **WHEN** a user asks what they filed about milk
- **THEN** the model uses the search tool
- **AND** the chat shows that a search ran

#### Scenario: Clear thing to keep

- **WHEN** a user sends a message that is clearly a to-do or an idea
- **THEN** the model uses the proposal tool
- **AND** the user sees a proposal to review, and nothing is stored yet
- **AND** the model's reply does not say the thought was saved or noted

#### Scenario: Several things to keep

- **WHEN** a user sends `/push buy oat milk and book the dentist`
- **THEN** the model makes one proposal with two parts

#### Scenario: Search finds thoughts

- **WHEN** the search tool runs for a user who has a thought titled `Oat milk` and the query is `milk`
- **THEN** the tool result holds that thought's title, tags, date, and summary
- **AND** the model answers from it
- **AND** the chat receives that thought as a source

#### Scenario: Search narrowed by the model

- **WHEN** a user asks what work ideas they filed this month
- **THEN** the model can call the search tool with the tag `work` and the first of the month as the start date
- **AND** the result holds only thoughts that fit both

#### Scenario: Search finds nothing

- **WHEN** the search tool runs and no thought matches well enough
- **THEN** the tool result says no filed thoughts matched
- **AND** the model tells the user

#### Scenario: Search by words only

- **WHEN** the search tool runs for a user with no saved key for the embedding provider
- **THEN** the tool result holds the matches by words and says that searching by meaning needs that provider's key in settings
- **AND** the model tells the user, and the turn ends normally

#### Scenario: Search before any thought is stored

- **WHEN** the search tool runs for a user who has not stored any thoughts yet
- **THEN** the tool result says no filed thoughts matched, without calling the embedding provider
- **AND** the model tells the user, and nothing is stored

#### Scenario: Bounded rounds

- **WHEN** the model keeps calling tools without finishing
- **THEN** the system stops after the configured number of rounds
- **AND** the chat shows that the answer could not be completed

#### Scenario: Thoughts seen by ref

- **WHEN** a conversation has filed one thought and a search in it returned two others
- **THEN** the next turn tells the model those three thoughts, each with a ref and no id

#### Scenario: Candidates found

- **WHEN** the model proposes a new idea and the similar-thought check finds a filed idea on the same subject
- **THEN** no card is shown yet, and the tool result lists the filed idea by ref
- **AND** the model's second proposal in that turn is shown as its card

#### Scenario: Refused call before a candidate round

- **WHEN** the model proposes a mark on a guessed ref and a new thought about oat milk, the call is refused for the mark, and the user has a similar filed thought about oat milk
- **THEN** the model's corrected call with the oat milk part gets a candidate round, and no card is shown yet
- **AND** the model's proposal after that round is shown as its card

### Requirement: The offer before an action may propose nothing

Before archive or `/compact`, when no proposal with an unsaved part is held, the system SHALL ask the model for a proposal only if the user sent a message after the latest saved proposal. A saved proposal is one with a confirmed part that filed a new thought or added to one; a proposal whose only confirmed parts marked thoughts done SHALL NOT count as saved. The model SHALL be told which thoughts this conversation has seen, each by its ref, including those it already filed, SHALL be free to propose nothing, and SHALL be steered to leave out greetings, thanks, and small talk. When the discussion since the latest saved proposal continues one of those thoughts, the offer SHALL propose it as an addition to that thought, not as a new thought. A new part in the offer SHALL go through the similar-thought check. When the model proposes nothing, the action SHALL go ahead with no offer.

#### Scenario: Nothing said since the last saved card

- **WHEN** a user confirms every card of a proposal that filed a thought and then sends `/compact` without another message
- **THEN** no proposal is offered and the model is not asked for one

#### Scenario: Only thanks since

- **WHEN** a user confirms a card, sends `thanks`, and then sends `/compact`
- **THEN** no proposal is offered

#### Scenario: New facts on the same topic

- **WHEN** a user files `Buy a bike lock`, asks about lock colours, strength, and prices, and then sends `/compact`
- **THEN** the offer does not repeat `Buy a bike lock` as a new thought
- **AND** it offers the new facts as an addition to `Buy a bike lock`

#### Scenario: Offer finds an older thought

- **WHEN** a user discusses a podcast about cartography, never files it, and archives the conversation, and they filed `Podcast about maps` a year ago in another conversation
- **THEN** the offer adds to `Podcast about maps`, or its card offers to add to it

#### Scenario: Only a status card confirmed since

- **WHEN** a user discusses a podcast idea, then confirms every card of a proposal whose only part marks `Call the plumber` done, and then sends `/compact` without another message
- **THEN** the model is asked for a proposal before compacting
