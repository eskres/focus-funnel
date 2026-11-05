## MODIFIED Requirements

### Requirement: The sidebar lists conversations

The chat screen SHALL show a sidebar on the left that lists the user's conversations that are not archived, with the most recently active first. Each entry SHALL show the conversation's title. A title SHALL start as the beginning of the first message and SHALL be editable by the user. The sidebar SHALL offer a way to start a new conversation. Opening the chat screen SHALL start a new, empty conversation. A conversation made by a quick capture SHALL NOT be listed, neither in the main list nor under "Archived". A message other than /compact that the chat stores in it, or sends again after a failed answer, including one then refused at the spend cap, for a full context, or for a missing provider key, SHALL make it an ordinary conversation, listed like any other from then on. /compact, and a message refused because an answer is running, SHALL leave it a capture.

#### Scenario: Newest activity first

- **WHEN** a user sends a message in an older conversation
- **THEN** that conversation moves to the top of the sidebar

#### Scenario: Title from the first message

- **WHEN** a conversation's first message is `buy oat milk tomorrow`
- **THEN** the conversation's title starts with `buy oat milk tomorrow`

#### Scenario: Rename

- **WHEN** a user renames a conversation
- **THEN** the sidebar shows the new title and the change is kept after a reload

#### Scenario: Opening the chat

- **WHEN** a user opens the chat screen
- **THEN** the conversation area is empty and shows the command list
- **AND** the sidebar lists the user's earlier conversations

#### Scenario: No conversations yet

- **WHEN** a user with no conversations opens the chat screen
- **THEN** the sidebar says there are no conversations yet

#### Scenario: A capture is not listed

- **WHEN** a user makes a quick capture and opens the chat screen
- **THEN** the sidebar does not list the capture

#### Scenario: Carry on in a capture

- **WHEN** a user opens a thought's origin in a capture, and sends a message in that conversation
- **THEN** the message is answered in that conversation, and it appears at the top of the sidebar
- **AND** the capture is no longer listed on the Capture page

#### Scenario: Resend in a capture

- **WHEN** a capture's turn failed, and the user opens it and sends the same message again
- **THEN** the conversation is listed in the sidebar, and the capture is no longer listed on the Capture page

#### Scenario: Refused at the cap in a capture

- **WHEN** a user whose month has reached the spend cap opens a capture from a thought's origin and sends a message there
- **THEN** the message is refused at the cap and stays in the conversation
- **AND** the sidebar lists the conversation, and the Capture page no longer lists the capture

#### Scenario: /compact in a capture

- **WHEN** a user opens a capture from a thought's origin and sends `/compact` there
- **THEN** the sidebar does not list the conversation
- **AND** the capture is still listed on the Capture page, when it still waits
