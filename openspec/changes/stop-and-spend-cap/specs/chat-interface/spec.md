## ADDED Requirements

### Requirement: An answer can be stopped

While an answer is running, the chat SHALL show a Stop button in place of Send, in every tab that shows the answer, including a tab that follows it after coming back. Stop SHALL end the answer on the server. The chat SHALL keep what arrived and say that the user stopped the answer, without showing it as an error, and SHALL let the user send the next message once the answer has ended.

#### Scenario: Stop while text arrives

- **WHEN** a user presses Stop while an answer's text is arriving
- **THEN** no more text arrives
- **AND** the text that arrived stays, with a note that the answer was stopped
- **AND** the user can send the next message

#### Scenario: Stop is busy until the answer ends

- **WHEN** a user presses Stop
- **THEN** the button shows that it is stopping and cannot be pressed again until the answer has ended

#### Scenario: Stop as the answer finishes

- **WHEN** a user presses Stop and the answer finishes before the stop takes effect
- **THEN** the answer shows as complete, not stopped
- **AND** the user can send the next message

#### Scenario: Stop in a second tab

- **WHEN** a user follows a running answer in a second tab and presses Stop there
- **THEN** both tabs show the answer as stopped
- **AND** both tabs let the user send the next message

#### Scenario: Stopped answer reopened

- **WHEN** a user reopens a conversation whose last answer was stopped
- **THEN** the chat shows the text, tools, sources, and proposal card that were kept, with the note that the answer was stopped

#### Scenario: Stop failed

- **WHEN** the stop request cannot reach the server
- **THEN** the chat says that the answer could not be stopped
- **AND** the Stop button can be pressed again while the answer runs

#### Scenario: No Stop for compact

- **WHEN** a `/compact` summary is being written
- **THEN** the summary dialog's Cancel ends it, as before, and no Stop button is shown

### Requirement: A tool cut off by a stop says so

A tool that had not finished when the answer stopped SHALL show that it stopped before it finished, with no sign that it is still running and not as finished. The chat SHALL show it the same way live and after the conversation is reopened.

#### Scenario: Stop while a tool runs

- **WHEN** a user presses Stop while the chat shows a tool running, such as a search of their thoughts
- **THEN** that tool shows that it stopped before it finished, and no longer shows as running
- **AND** after the conversation is reopened it shows the same, not as finished

#### Scenario: Stop while the model asks for a tool

- **WHEN** a user presses Stop after the chat showed a tool starting and before the model finished asking for it
- **THEN** that tool shows that it stopped before it finished
- **AND** after the conversation is reopened the same tool shows the same

## MODIFIED Requirements

### Requirement: Errors are shown in the chat

When a message cannot be answered, the chat SHALL show the reason in place of the answer, and the user's message SHALL stay in the conversation. Errors about a provider key SHALL link to the provider settings. Errors about the model, including no model chosen and an unavailable model, SHALL link to the model settings. A full context SHALL advise `/compact`, a model with a larger context, or a new conversation. A reply that ran out of room SHALL offer to try again. A reached spend cap SHALL say that the monthly cap was reached, name it, and link to the usage settings where it can be raised or removed, also when `/compact` is refused, where the summary dialog shows it.

#### Scenario: No provider key saved

- **WHEN** a user with no saved key for their conversation's provider sends a message
- **THEN** the chat shows that a key for that provider is needed, with a link to the provider settings

#### Scenario: No model chosen

- **WHEN** a user with no default model sends a message
- **THEN** the chat shows that a model is needed, with a link to the model settings
- **AND** no answer from any model appears

#### Scenario: Model unavailable

- **WHEN** the conversation's model cannot be used
- **THEN** the chat shows which model failed, with a link to the model settings
- **AND** the chat does not show an answer from a different model

#### Scenario: Context full

- **WHEN** a message cannot fit in the model's context
- **THEN** the chat says the conversation is full and advises `/compact`, a model with a larger context, or a new conversation

#### Scenario: Reply ran out of room

- **WHEN** a reply stops at the system's length limit
- **THEN** the chat keeps any text received, says the model ran out of room, and offers to try again

#### Scenario: User message kept after a failure

- **WHEN** any error is shown for a message
- **THEN** the user's message is still visible in the conversation

#### Scenario: Spend cap reached

- **WHEN** a user whose month has reached their spend cap sends a message
- **THEN** the chat says the monthly spend cap was reached and names it, with a link to the usage settings
- **AND** no answer from any model appears

#### Scenario: Spend cap reached during an answer

- **WHEN** an answer ends because its usage reached the spend cap
- **THEN** the chat keeps the tools, sources, and proposal card the answer produced
- **AND** shows the spend cap message with the link to the usage settings, also after the conversation is reopened

#### Scenario: Spend cap reached in a new conversation

- **WHEN** a user whose month has reached their spend cap sends the first message of a new conversation
- **THEN** the chat shows the spend cap message, and the new conversation holds the user's message and is listed with the user's conversations
- **AND** after the user raises the cap and sends the same message again, it is answered in that same conversation, and the message shows once

#### Scenario: Sending again after an answer ended at the cap

- **WHEN** an answer ended at the spend cap after it showed tools, sources, or a proposal card, and the user raises the cap and sends the same text again
- **THEN** the text is sent as a new message with its own answer
- **AND** the earlier answer keeps its tools, sources, and proposal card, also after the conversation is reopened

#### Scenario: Compact at the spend cap

- **WHEN** a user whose month has reached their spend cap sends `/compact`
- **THEN** the summary dialog says the monthly spend cap was reached and names it, with a link to the usage settings
- **AND** nothing in the conversation changes

### Requirement: Sending a message

The chat screen SHALL offer a message input and a way to send it. A sent message SHALL appear in the conversation straight away, and the input SHALL be cleared and ready for the next message. A message that is empty or only whitespace SHALL NOT be sent.

#### Scenario: Sending text

- **WHEN** a logged-in user types a message and sends it
- **THEN** the message appears in the conversation as the user's message
- **AND** the input is cleared

#### Scenario: Empty message

- **WHEN** a user tries to send an empty message or one made only of whitespace
- **THEN** nothing is sent and the conversation does not change

#### Scenario: Sending while an answer is still arriving

- **WHEN** an answer is still arriving
- **THEN** the user cannot send another message in that conversation until that answer has ended: finished, failed, or stopped

### Requirement: Thinking is shown

While the model is working and no text has arrived yet, the chat SHALL show that the model is thinking. The indication SHALL end when the first text or tool call arrives, or the answer fails or is stopped.

#### Scenario: Waiting for the first text

- **WHEN** a message has been sent and no part of the answer has arrived
- **THEN** the chat shows that the model is thinking

#### Scenario: First text arrives

- **WHEN** the first text of the answer arrives
- **THEN** the thinking indication is replaced by the text

#### Scenario: Stopped before any text

- **WHEN** a user presses Stop before any text of the answer has arrived
- **THEN** the thinking indication ends
- **AND** the chat says that the user stopped the answer

### Requirement: Answers arrive a piece at a time

An answer SHALL be shown as it is produced, not only when it is complete. Each piece SHALL appear as it arrives. When the connection breaks while an answer is arriving, the chat SHALL keep what it received and follow the answer again: if the answer is still running it SHALL carry on showing it, and if it has ended it SHALL show the stored answer. The chat SHALL say that an answer was cut short only when the stored answer did not finish and was not stopped; a stored answer that was stopped SHALL show as stopped.

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
- **AND** it says the answer was cut short only if the stored answer did not finish and was not stopped

#### Scenario: Connection drops and the answer is stopped meanwhile

- **WHEN** the connection breaks and, before the chat follows the answer again, the user stops it from another tab
- **THEN** the chat shows the stored stopped answer with the note that the user stopped it
- **AND** it does not say that the answer was cut short

#### Scenario: Server cannot be reached again

- **WHEN** the connection breaks and the chat cannot reach the server to follow the answer
- **THEN** the part already received stays in the conversation
- **AND** the chat shows that the answer was cut short and the conversation can be opened again
