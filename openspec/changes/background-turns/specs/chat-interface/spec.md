## MODIFIED Requirements

### Requirement: Answers arrive a piece at a time

An answer SHALL be shown as it is produced, not only when it is complete. Each piece SHALL appear as it arrives. When the connection breaks while an answer is arriving, the chat SHALL keep what it received and follow the answer again: if the answer is still running it SHALL carry on showing it, and if it has ended it SHALL show the stored answer. The chat SHALL say that an answer was cut short only when the stored answer did not finish.

#### Scenario: Partial answer visible

- **WHEN** the first part of an answer arrives and the rest has not
- **THEN** the part that arrived is visible in the conversation
- **AND** the chat shows that the answer is still being written

#### Scenario: Answer completes

- **WHEN** the last part of an answer arrives
- **THEN** the chat stops showing the answer as in progress
- **AND** the full answer text is the parts joined in the order they arrived

#### Scenario: Connection drops in the middle

- **WHEN** the connection breaks while an answer is arriving and the answer is still running
- **THEN** the part already received stays in the conversation
- **AND** the chat follows the answer again and shows the rest as it arrives

#### Scenario: Connection drops and the answer ends meanwhile

- **WHEN** the connection breaks and the answer ends before the chat follows it again
- **THEN** the chat shows the stored answer
- **AND** it says the answer was cut short only if the stored answer did not finish

#### Scenario: Server cannot be reached again

- **WHEN** the connection breaks and the chat cannot reach the server to follow the answer
- **THEN** the part already received stays in the conversation
- **AND** the chat shows that the answer was cut short and the conversation can be opened again

## ADDED Requirements

### Requirement: Coming back to an answer

When a user opens a conversation, the chat SHALL show any answer that finished while the user was away in full, as if the user had watched it: its text, the tools it used, its proposal cards, its sources, and any error. When the conversation's answer is still running, the chat SHALL show the answer so far as in progress, show the rest as it arrives, and keep the message input from sending in that conversation until the answer ends. Leaving a conversation SHALL NOT stop its answer.

#### Scenario: Finished while away

- **WHEN** a user sends a message, switches to another conversation, and comes back after the answer finished
- **THEN** the chat shows the full answer with its tool results, proposal cards, and sources
- **AND** the user can send the next message

#### Scenario: Still running on return

- **WHEN** a user comes back to a conversation whose answer is still running
- **THEN** the chat shows the answer so far, marked as in progress
- **AND** the rest of the answer appears as it arrives
- **AND** the user cannot send another message in that conversation until the answer ends

#### Scenario: Proposal made while away

- **WHEN** the model proposed a thought while the user was in another conversation
- **THEN** on return the proposal card shows and can be edited and confirmed

#### Scenario: Failed while away

- **WHEN** an answer failed while the user was away
- **THEN** on return the chat shows the reason in place of the answer, as when the user watched it fail

#### Scenario: Two tabs on one answer

- **WHEN** a user opens a conversation in a second tab while its answer is running
- **THEN** both tabs show the answer as it arrives
