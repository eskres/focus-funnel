## Purpose

Decides which gate handles each chat message: an explicit leading slash command always wins, and everything else is classified by the router gate. The user always sees which gate handled a message and why.

## ADDED Requirements

### Requirement: A leading slash command picks the gate

A message that begins with `/push`, `/pull`, or `/explore` SHALL go to that gate. The command SHALL be matched at the start of the message, ignoring leading whitespace, without regard to letter case, and only when the command is followed by whitespace or by the end of the message. The rest of the message, with the command removed, SHALL be the content the gate receives. A command SHALL always win over classification: the router gate SHALL NOT run for a message that starts with a command.

#### Scenario: Message with a command

- **WHEN** a user sends `/push buy oat milk`
- **THEN** the push gate handles the message
- **AND** the gate receives `buy oat milk` as the content
- **AND** the router gate does not run

#### Scenario: Command in a different case

- **WHEN** a user sends `/Pull what did I say about rent?`
- **THEN** the pull gate handles the message

#### Scenario: Leading whitespace before the command

- **WHEN** a user sends a message that begins with spaces followed by `/explore an idea`
- **THEN** the explore gate handles the message

#### Scenario: Word that only starts like a command

- **WHEN** a user sends `/pushing the deadline again`
- **THEN** the message is not treated as a command
- **AND** the router gate decides which gate handles it

#### Scenario: Slash command not at the start

- **WHEN** a user sends `remind me to /push this later`
- **THEN** the message is not treated as a command
- **AND** the router gate decides which gate handles it

#### Scenario: Unknown command

- **WHEN** a user sends `/archive something`
- **THEN** the message is not treated as a command
- **AND** the router gate decides which gate handles it

#### Scenario: Command with no content

- **WHEN** a user sends a message that is only `/push`, with nothing after it
- **THEN** no gate runs
- **AND** the system responds with HTTP 422 and error code `validation_error`, saying the command needs a message

#### Scenario: The router gate cannot be addressed

- **WHEN** a user sends `/router something`
- **THEN** the message is not treated as a command
- **AND** the router gate decides which gate handles it as ordinary text

### Requirement: Messages without a command go to the router gate

A message that does not begin with a gate command SHALL be sent to the router gate. The router gate SHALL classify the message as `push`, `pull`, or `explore`, and the chosen gate SHALL then handle the message. The router gate SHALL use the model, temperature, and token limit in force for the `router` gate.

#### Scenario: Message that files something away

- **WHEN** a user sends a message with no command that states something to remember
- **THEN** the router gate classifies it
- **AND** the gate it picked handles the message

#### Scenario: Router uses its own settings

- **WHEN** the router gate classifies a message for a user who has overridden the router gate's model
- **THEN** the classification call uses that user's overridden model

#### Scenario: Empty message

- **WHEN** a user sends an empty message or one made only of whitespace
- **THEN** no gate runs
- **AND** the system responds with HTTP 422 and error code `validation_error`

### Requirement: The answer says which gate handled the message

Every answer SHALL carry the id of the gate that handled the message and whether that gate was chosen by an explicit command or by the router. The chat SHALL show this with the answer.

#### Scenario: Gate chosen by command

- **WHEN** a message handled by an explicit command is answered
- **THEN** the answer names that gate and reports that it was chosen by the command

#### Scenario: Gate chosen by the router

- **WHEN** a message with no command is answered
- **THEN** the answer names the gate the router picked and reports that the router chose it

#### Scenario: Routing result arrives before the answer text

- **WHEN** a message is answered
- **THEN** the routing result reaches the client before any of the answer text, so the label is shown while the answer is still arriving

### Requirement: An unusable classification fails clearly

When the router gate's answer is not one of `push`, `pull`, or `explore`, the system SHALL NOT guess a gate and SHALL NOT run any gate handler. It SHALL report error code `routing_failed` with a message that asks the user to start the message with `/push`, `/pull`, or `/explore`.

#### Scenario: Classification cannot be read

- **WHEN** the router gate returns an answer that names no known gate
- **THEN** no gate handler runs
- **AND** the system reports error code `routing_failed` with a message suggesting an explicit command

#### Scenario: Router model unavailable

- **WHEN** the router gate's model in force cannot be used
- **THEN** the system reports error code `gate_model_unavailable` naming the router gate
- **AND** no other model is used to classify the message

#### Scenario: Router gate has no model chosen

- **WHEN** a message with no command arrives and the router gate's model is unset
- **THEN** the system reports error code `gate_model_not_set` naming the router gate
- **AND** the message tells the user to choose a router model or to start the message with `/push`, `/pull`, or `/explore`
- **AND** no model is called

### Requirement: Placeholder answers until the gates are built

Until the push, pull, and explore gates have their own behavior, each SHALL answer with a short message saying that the gate is not available yet. The routing result SHALL still be reported as it would be for a real answer.

#### Scenario: Push placeholder

- **WHEN** a message is routed to the push gate
- **THEN** the answer says that the push gate is not available yet
- **AND** the answer is labelled as handled by the push gate

#### Scenario: Placeholder after router classification

- **WHEN** the router classifies a message as pull and the pull gate is still a placeholder
- **THEN** the answer says that the pull gate is not available yet
- **AND** the answer reports that the router chose the pull gate

#### Scenario: Routing still checked

- **WHEN** a placeholder gate answers
- **THEN** the routing result carries the same fields it will carry once the gate is built
