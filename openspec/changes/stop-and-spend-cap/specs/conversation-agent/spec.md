## ADDED Requirements

### Requirement: The owner can stop a running turn

The owner SHALL be able to stop a running turn from any tab, which ends it on the server: no model call or tool starts after the stop, and the model call in flight is closed. The stop SHALL answer at once; the turn's stream says when the answer has ended. Stopping a conversation with no running turn SHALL succeed and change nothing. Another user SHALL get a not-found response, the same as for an unknown conversation.

#### Scenario: Stop while the model writes

- **WHEN** the owner stops a turn while its answer is arriving
- **THEN** the model call is closed and no further model call starts
- **AND** every tab that follows the turn gets the end of the answer with code `answer_stopped`

#### Scenario: Stop from a second tab

- **WHEN** the owner follows a running turn in a second tab and stops it there
- **THEN** the turn ends on the server
- **AND** both tabs show the answer as stopped

#### Scenario: Send right after a stop

- **WHEN** the owner sends a message in the conversation right after the answer ended as stopped
- **THEN** the message is answered and the system does not respond with `conversation_busy`

#### Scenario: Nothing running

- **WHEN** the owner stops a conversation whose turn has already ended
- **THEN** the stop succeeds and the stored answer does not change

#### Scenario: Another user's conversation

- **WHEN** a user asks to stop a turn in another user's conversation
- **THEN** the system responds with HTTP 404 and error code `not_found`, the same body as for an unknown conversation
- **AND** the other user's turn keeps running

#### Scenario: Stop after the answer is written

- **WHEN** the stop arrives after the turn has started storing its final answer
- **THEN** the answer is stored as complete, not stopped

#### Scenario: Stop while a failure is stored

- **WHEN** the stop arrives while the turn is storing a failed answer, the end at the tool round limit, or the end at the spend cap
- **THEN** that answer and its error code are kept
- **AND** no stopped answer is added

### Requirement: A stop that comes twice

A stop while a stop is already under way SHALL succeed and SHALL NOT end the turn a second time.

#### Scenario: Two stops at once

- **WHEN** the owner stops a running turn from two tabs at the same time
- **THEN** both stops succeed
- **AND** one stopped answer is stored

### Requirement: A stopped turn keeps what it produced

A stopped turn SHALL store its answer with the status `stopped` and the code `answer_stopped`, which is not shown as a failure. It SHALL keep the text received so far, earlier rounds, finished tool results with their sources, and a proposal already shown, which stays confirmable. A proposal not yet shown SHALL NOT be stored. A built-in tool call without a result SHALL be stored as not run, so the next message can be answered.

#### Scenario: Partial text kept

- **WHEN** the owner stops an answer after part of its text arrived
- **THEN** the stored answer holds that text with status `stopped`
- **AND** the next turn's context includes that text

#### Scenario: Stop after a search

- **WHEN** the owner stops a turn after its search finished and while the model writes the answer
- **THEN** the search result and its sources are kept with the answer

#### Scenario: Proposal shown before the stop

- **WHEN** the owner stops a turn after its proposal card was shown
- **THEN** the card stays and can be confirmed

#### Scenario: Stop while a tool runs

- **WHEN** the owner stops a turn while a search or proposal tool call has no result yet
- **THEN** that tool call is stored as not run, with no proposal for it
- **AND** the next message in the conversation is answered

#### Scenario: Stop is not a failure

- **WHEN** a stopped answer is shown again after the conversation is reopened
- **THEN** it shows as stopped, not as failed or cut short

### Requirement: A stop stores each thing once

A stop that comes while the turn is storing something SHALL let that store finish, and SHALL then end the turn as stopped before its next model call or tool call, without the owner stopping it again. What that store produced SHALL be shown before the answer ends: a proposal card, an action card, or the monthly usage warning. A stop SHALL NOT record a model call's usage twice or store the same text twice. A server shutdown during a stop SHALL NOT store a second answer.

#### Scenario: Stop while the proposal is being stored

- **WHEN** the owner stops a turn while its proposal is being stored and the store completes
- **THEN** the proposal card is shown before the answer ends as stopped
- **AND** the stopped answer is stored once

#### Scenario: Stop while usage is being recorded

- **WHEN** the owner stops a turn while the usage of its model call is being recorded, and the model asked for a tool in that call
- **THEN** that call has one usage record, not two
- **AND** the turn ends as stopped before the tool runs

#### Scenario: Stop while the warning is noted

- **WHEN** the owner stops a turn while the round that reached their warning threshold is being recorded
- **THEN** the warning notice is shown before the answer ends as stopped
- **AND** the warning is noted for the month once

#### Scenario: Server stops during a stop

- **WHEN** the server shuts down while a stopped answer is being stored
- **THEN** one stopped answer is stored
- **AND** the conversation is free for the next message

### Requirement: A stopped turn and connector calls

A connector tool call that may have reached its server when the turn was stopped SHALL be stored as stopped while it ran, saying that it may have run, and SHALL NOT be stored as not run. A connector action card not yet shown SHALL NOT be stored; one already shown SHALL stay pending and approvable until the next turn starts. A stopped turn SHALL still expire the action cards of earlier turns, as any turn that starts does. A stop SHALL keep the usage of calls that answered before it.

#### Scenario: Stop while a connector action runs

- **WHEN** the owner stops a turn while an always-allowed connector tool such as `calendar__create_event` is waiting for its server
- **THEN** that tool call is stored as stopped while it ran, saying that it may have run and should be checked before running it again
- **AND** the next turn's context does not say that it did not run

#### Scenario: Action card shown before the stop

- **WHEN** the owner stops a turn after a connector action card was shown
- **THEN** the card stays pending
- **AND** approving it runs the action once

#### Scenario: Older cards after a stopped turn

- **WHEN** a conversation has a pending action card from an earlier turn, and the owner sends a message and stops the answer before its first model call has finished
- **THEN** that card has expired
- **AND** approving it responds with HTTP 409 and error code `action_expired`

#### Scenario: Search paid before the stop

- **WHEN** the owner stops a turn while its search waits after the query was embedded
- **THEN** the embedding call's usage is kept

## MODIFIED Requirements

### Requirement: Conversations run independently

Each conversation SHALL use its own stored model and effort. A turn running in one conversation SHALL NOT block a turn in another conversation of the same user, whether in the same browser tab or another. Only one turn at a time SHALL run in a single conversation.

A turn SHALL run to completion on the server whether or not the browser that sent the message is still connected. Closing the tab, switching conversations, or losing the connection SHALL NOT stop the model call, the tools, or the storing of the answer. What the turn produces SHALL be stored the same way whether or not anyone is watching: a complete answer as complete, a failed answer as failed, a cut answer as cut, and a stopped answer as stopped. While a turn runs, its owner SHALL be able to follow it again from the start of the answer, from any tab; another user SHALL get a not-found response. The conversation SHALL be free for the next message as soon as the turn ends, however it ends. When the server stops or restarts during a turn, the turn's answer SHALL be stored as failed, with the text received so far where the server could store it, and the conversation SHALL be free once the server is back. Only the owner SHALL be able to stop a running turn, and only by asking to stop it, never by leaving.

#### Scenario: Two conversations, two models

- **WHEN** a user has one conversation on model A and another on model B and sends a message in each
- **THEN** each message is answered by its own conversation's model
- **AND** neither answer uses the other conversation's messages

#### Scenario: Turns overlap in different conversations

- **WHEN** a user sends a message in a second conversation while the first is still answering
- **THEN** both answers arrive

#### Scenario: Second turn in the same conversation

- **WHEN** a user sends a message in a conversation that is still answering, from another tab
- **THEN** the system responds with error code `conversation_busy`
- **AND** the running turn is not affected

#### Scenario: Leaving mid-answer

- **WHEN** a user switches to another conversation while an answer is streaming
- **THEN** the model call continues
- **AND** the finished answer is stored, with its tool results, proposal, and sources

#### Scenario: Tab closed mid-answer

- **WHEN** a user closes the tab while an answer is streaming
- **THEN** the finished answer is stored
- **AND** the usage of every model call in the turn is recorded

#### Scenario: Free once the turn ends

- **WHEN** a turn ends after its browser disconnected
- **THEN** the next message in that conversation is answered
- **AND** the system does not respond with `conversation_busy`

#### Scenario: Failure while nobody watches

- **WHEN** the provider fails a turn after its browser disconnected
- **THEN** the answer is stored as failed with the provider's error code, as when the browser stays connected
- **AND** the conversation is free for the next message

#### Scenario: Following a running turn again

- **WHEN** the owner asks to follow a conversation's running turn
- **THEN** the system sends every event of the answer so far, then the rest as it arrives

#### Scenario: Following another user's turn

- **WHEN** a user asks to follow a running turn in another user's conversation
- **THEN** the system responds with HTTP 404

#### Scenario: Nothing running

- **WHEN** the owner asks to follow a conversation that has no running turn
- **THEN** the system says that no turn is running, without an error
- **AND** the stored messages hold the last answer

#### Scenario: Server restart mid-turn

- **WHEN** the server restarts while a turn is running
- **THEN** after the restart the answer shows as failed and can be sent again
- **AND** the conversation is free for the next message without waiting

#### Scenario: Demo key during a turn

- **WHEN** a demo visitor sends a message and then closes the tab
- **THEN** the turn finishes with the key sent with that message
- **AND** the key is not stored on the server and is not sent to the browser

#### Scenario: Stopped turn frees the conversation

- **WHEN** the owner stops a running turn
- **THEN** the answer is stored as stopped, not as failed
- **AND** the conversation is free for the next message

### Requirement: The offer before an action may propose nothing

Before archive or `/compact`, when no proposal with an unsaved part is held, the system SHALL ask the model for a proposal only if the user sent a message after the latest proposal with a saved part. The model SHALL be told which thoughts this conversation has seen, each by its ref, including those it already filed, SHALL be free to propose nothing, and SHALL be steered to leave out greetings, thanks, and small talk. When the discussion since the latest saved proposal continues one of those thoughts, the offer SHALL propose it as an addition to that thought, not as a new thought. A new part in the offer SHALL go through the similar-thought check. When the model proposes nothing, the action SHALL go ahead with no offer. When the user's monthly spend cap is reached, the model SHALL NOT be asked and the action SHALL go ahead with no offer; a held proposal with an unsaved part SHALL still be offered.

#### Scenario: Nothing said since the last saved card

- **WHEN** a user confirms every card of a proposal and then sends `/compact` without another message
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

#### Scenario: Archive at the spend cap

- **WHEN** a user whose month reached their spend cap archives a conversation with a new message since its latest saved proposal and no held proposal
- **THEN** the model is not asked for an offer
- **AND** the conversation is archived with no offer

#### Scenario: Held proposal at the spend cap

- **WHEN** a user whose month reached their spend cap archives a conversation that holds a proposal with an unsaved part
- **THEN** that proposal is offered as before archive, with no model call
