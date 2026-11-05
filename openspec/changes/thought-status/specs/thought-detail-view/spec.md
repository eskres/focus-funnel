## ADDED Requirements

### Requirement: The sheet marks a thought done

The sheet SHALL show whether the thought is done, with a Done toggle the user can turn on or off without choosing Edit. Turning it SHALL save at once. A done thought SHALL show the date it was marked done. A change that fails SHALL put the toggle back and SHALL show the reason. The toggle SHALL NOT change the thought's "changed" date or any of its other fields.

#### Scenario: Mark done

- **WHEN** a user opens the open task `Call the plumber` and turns on Done
- **THEN** the sheet shows the task as done, with today's date
- **AND** its "changed" date is as before

#### Scenario: Reopen

- **WHEN** a user opens a done task and turns off Done
- **THEN** the sheet shows the task as open, with no done date

#### Scenario: Change fails

- **WHEN** a user turns on Done and the change is refused
- **THEN** the toggle is off again, and the sheet shows the reason

#### Scenario: Still found

- **WHEN** a user marks a task done in the sheet and then searches for its title
- **THEN** the search finds the task
