## ADDED Requirements

### Requirement: Each index learns its similarity baseline

Each search index SHALL record how similar the user's unrelated thoughts are in that index's embedding model, measured from the entries it already holds, without an embedding call. The baseline SHALL be measured when the index becomes active and again as the user's thoughts grow, and the similar-thought check SHALL set its cut-offs from it. An index with too few thoughts to measure SHALL use the configured search threshold for its model, or the default one. A new embedding model SHALL need no setting for the check to work.

#### Scenario: New embedding model

- **WHEN** the operator switches to an embedding model that has no rule in the configuration and rebuilds a user's index
- **THEN** the new index records its own baseline and the similar-thought check works with it

#### Scenario: Few thoughts

- **WHEN** a user with three thoughts proposes a new one
- **THEN** the check uses the configured threshold for the index's model

### Requirement: The operator can measure the similar-thought check

The operator SHALL be able to run a command-line job, not reachable over the API, that measures the similar-thought check for a named embedding provider and model, and optionally a chat model, against a labelled test set kept in the repository. The job SHALL report how often the true match is among the candidates, how often a thought on the same topic but a different thing is offered, and whether each result meets its target, and SHALL end with a failure status when a target is missed. The test set SHALL be extendable without code changes.

#### Scenario: Measure a new model

- **WHEN** the operator runs the job for an embedding model that was released after the test set was written
- **THEN** the job reports both rates and whether each meets its target

#### Scenario: Target missed

- **WHEN** the true match is among the candidates for fewer pairs than the target
- **THEN** the job ends with a failure status
