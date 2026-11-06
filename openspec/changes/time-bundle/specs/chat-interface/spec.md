## ADDED Requirements

### Requirement: A status card for a repeating thought says it stops repeating

A card that proposes marking a repeating thought done SHALL say that marking it done stops it repeating, before it is confirmed. A card for a thought that does not repeat SHALL NOT say so.

#### Scenario: Weekly thought

- **WHEN** the model proposes marking `Take the bins out`, which repeats every week, done
- **THEN** the card says "Mark done: Take the bins out" and "Marking it done stops it repeating."

#### Scenario: One-off task

- **WHEN** the model proposes marking `Call the plumber`, which does not repeat, done
- **THEN** the card does not say anything about repeating
