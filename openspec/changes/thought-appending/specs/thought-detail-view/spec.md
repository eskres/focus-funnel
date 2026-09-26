## ADDED Requirements

### Requirement: The sheet lists a thought's additions

The sheet SHALL list each addition to the thought, newest first, with its date and the title of the conversation it came from, as the conversation has it now, linked to that conversation at the addition's card. An addition whose conversation was deleted SHALL NOT be listed. A thought with no additions SHALL show no additions section. The thought's origin SHALL stay the proposal it was first filed from.

#### Scenario: Two additions

- **WHEN** a thought was added to from two conversations and the user opens it
- **THEN** the sheet lists both additions with their dates and conversation titles
- **AND** the origin still shows the conversation the thought was first filed from

#### Scenario: Open an addition

- **WHEN** the user clicks an addition in the list
- **THEN** the sheet closes and that conversation shows with the addition's card in view

### Requirement: The last addition can be undone

The sheet SHALL offer to undo the newest addition that is not already undone. Undoing SHALL ask for confirmation, then SHALL restore the summary, tags, category, and raw text the thought had before that addition, and search SHALL find the thought by the restored content. Undo SHALL be refused when the thought was changed after that addition, and the sheet SHALL say why. The addition's card SHALL then say that the addition was undone, and the proposal SHALL NOT be offered again to file.

#### Scenario: Undo

- **WHEN** a user undoes the last addition and confirms
- **THEN** the sheet shows the summary and tags from before that addition
- **AND** the addition's card says it was undone

#### Scenario: Changed since

- **WHEN** a user edits the thought's title after an addition and then tries to undo it
- **THEN** the undo is refused, the sheet says the thought changed after the addition, and nothing changes
