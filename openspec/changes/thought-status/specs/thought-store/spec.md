## ADDED Requirements

### Requirement: Every thought has an open or done status

Every thought SHALL have a status, `open` or `done`. A thought SHALL be stored as `open`. The system SHALL keep the time of the thought's last status change, and none for a thought whose status never changed. A status other than `open` or `done` SHALL be refused naming the field `status`, and the thought SHALL be unchanged. Only the thought's owner SHALL change its status; another user SHALL get the same answer as for a thought that does not exist.

#### Scenario: New thought

- **WHEN** a thought is stored
- **THEN** it is read back with the status `open` and no status change time

#### Scenario: Marked done

- **WHEN** a user sets an open thought's status to `done`
- **THEN** it is read back with the status `done` and the time of that change

#### Scenario: Reopened

- **WHEN** a user sets a done thought's status back to `open`
- **THEN** it is read back with the status `open` and the time it was reopened

#### Scenario: Not a status

- **WHEN** a user sets a thought's status to `archived`
- **THEN** the system refuses it naming `status`, and the thought is unchanged

#### Scenario: Another user's thought

- **WHEN** a user sets the status of a thought another user owns
- **THEN** the system answers as if the thought did not exist
- **AND** the other user's thought is unchanged

### Requirement: A status change leaves the rest of the thought alone

Changing a thought's status SHALL NOT change its title, summary, tags, category, raw text, date, origin, or the time it was last updated. It SHALL NOT need an embedding call and SHALL NOT change the thought's search entries, so search SHALL find the thought as before. Setting the status a thought already has SHALL change nothing, including the time of its last status change.

#### Scenario: Done keeps the rest

- **WHEN** a user marks a thought titled `Call the plumber` done
- **THEN** its title, summary, tags, category, raw text, and updated time are as before
- **AND** no embedding call is made
- **AND** a search for `plumber` still finds it

#### Scenario: Same status again

- **WHEN** a user marks a thought done that is already done
- **THEN** the thought and the time of its last status change are as before
