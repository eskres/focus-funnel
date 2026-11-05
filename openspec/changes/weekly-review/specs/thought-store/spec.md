## MODIFIED Requirements

### Requirement: Every thought has an open or done status

Every thought SHALL have a status, `open`, `done`, or `archived`. A thought SHALL be stored as `open`. The system SHALL keep the time of the thought's last status change, and none for a thought whose status never changed. A status other than `open`, `done`, or `archived` SHALL be refused naming the field `status`, and the thought SHALL be unchanged. Only the thought's owner SHALL change its status; another user SHALL get the same answer as for a thought that does not exist.

#### Scenario: New thought

- **WHEN** a thought is stored
- **THEN** it is read back with the status `open` and no status change time

#### Scenario: Marked done

- **WHEN** a user sets an open thought's status to `done`
- **THEN** it is read back with the status `done` and the time of that change

#### Scenario: Reopened

- **WHEN** a user sets a done thought's status back to `open`
- **THEN** it is read back with the status `open` and the time it was reopened

#### Scenario: Archived

- **WHEN** a user sets an open thought's status to `archived`
- **THEN** it is read back with the status `archived` and the time of that change

#### Scenario: Not a status

- **WHEN** a user sets a thought's status to `pending`
- **THEN** the system refuses it naming `status`, and the thought is unchanged

#### Scenario: Another user's thought

- **WHEN** a user sets the status of a thought another user owns
- **THEN** the system answers as if the thought did not exist
- **AND** the other user's thought is unchanged

## ADDED Requirements

### Requirement: An archived thought keeps everything else

Archiving a thought or restoring it to `open` SHALL follow the status change rules: it SHALL change nothing else of the thought, need no embedding call, and keep its search entries. An archived thought SHALL keep its date, repeat, reminders, additions, and origin, and SHALL be restored with all of them.

#### Scenario: Archived and restored

- **WHEN** a user archives the dated idea `Podcast about maps` and later restores it
- **THEN** it is `open` again with the same title, summary, tags, category, date, and "changed" date
- **AND** no embedding call was made
