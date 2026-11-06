## MODIFIED Requirements

### Requirement: A default model and a loadout

The user SHALL be able to add up to five models from the model lists of the providers they have keys for, each entry being a provider and a model, to a loadout, mark one as the default, and remove models. Each model in the loadout SHALL have an optional reasoning effort. A new conversation SHALL start with the default model and its effort, except a weekly review conversation, which the system makes: it SHALL start with no model, and SHALL take the default model the user has, with its effort, at their first message there. Removing the default model SHALL require choosing another one, or leave the default unset.

#### Scenario: Add a model to the loadout

- **WHEN** a user adds a model from their model list
- **THEN** the loadout lists it and it can be chosen in a conversation

#### Scenario: Sixth model

- **WHEN** a user with five models in the loadout adds another
- **THEN** the system stores nothing and says the loadout is full

#### Scenario: Default model

- **WHEN** a user marks a loadout model as the default
- **THEN** new conversations start with that model and its effort

#### Scenario: A weekly review takes the default at the first message

- **WHEN** a user's default model is `Model A` when their weekly review conversation is made, they then mark `Model B` as the default, and send their first message in the review
- **THEN** the message is answered by `Model B` with its effort, and the review conversation keeps `Model B`

#### Scenario: Remove the default

- **WHEN** a user removes the default model
- **THEN** the default is unset until the user chooses another
- **AND** the chat responds with `model_not_set` for new conversations
