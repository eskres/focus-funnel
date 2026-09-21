## Purpose

Shows the user what their chat costs. Every model call is recorded with its tokens and an estimated cost, and settings shows the spend over time and can warn when it passes a limit the user sets. The real account balance is not shown, because providers generally do not offer it through an API key, and Nebius does not.

## ADDED Requirements

### Requirement: Every model call is recorded

The system SHALL record, for every model call it makes for a user, the provider, the model, the prompt tokens, the completion tokens, the time, and the conversation, when there is one. It SHALL record an estimated cost calculated from the per-token prices the provider lists for that model at the time of the call. When the provider reports no price, the cost SHALL be recorded as unknown. A record SHALL NOT hold any message text. A call that fails without a reported token count SHALL NOT be recorded.

#### Scenario: A chat answer

- **WHEN** a model answers a message
- **THEN** a record holds the model, the reported tokens, and the estimated cost
- **AND** the record holds no message text

#### Scenario: Compaction and tests

- **WHEN** a `/compact` summary or a model test calls the model
- **THEN** those calls are recorded too

#### Scenario: Two models in one conversation

- **WHEN** a user switches model in the middle of a conversation
- **THEN** each call is recorded against the model that made it

#### Scenario: Price unknown

- **WHEN** the provider lists no price for the model
- **THEN** the record's cost is unknown and its tokens are still recorded

### Requirement: Usage is shown as a graph in settings

The settings page SHALL show the user's estimated daily spend as a graph, for a period the user can choose, with the spend by model and the total for the current month. It SHALL be labelled an estimate, based on list prices, for calls made through this app. It SHALL NOT show an account balance, and SHALL link to the provider's console for it when the provider has one. Calls with an unknown cost SHALL be counted in tokens and marked.

#### Scenario: Spend over time

- **WHEN** a user opens the usage section
- **THEN** it shows a graph of estimated spend per day and the month's total

#### Scenario: By model

- **WHEN** a user has used two models
- **THEN** the section shows the spend for each

#### Scenario: Change the period

- **WHEN** a user picks a longer period
- **THEN** the graph covers that period

#### Scenario: No usage yet

- **WHEN** a user with no records opens the section
- **THEN** it says that nothing has been used yet

#### Scenario: Balance is not shown

- **WHEN** a user looks for their balance
- **THEN** the section says the balance is only in the provider's console, with a link when one is known

### Requirement: A warning threshold

The user SHALL be able to set a monthly warning threshold, in estimated dollars or in tokens. When the month's usage reaches it, the chat SHALL show a notice once, and the settings SHALL show that the threshold was passed. The warning SHALL NOT block the chat.

#### Scenario: Threshold reached

- **WHEN** a user's usage for the month reaches their threshold
- **THEN** the chat shows a notice that names the threshold
- **AND** the user can keep chatting

#### Scenario: Notice not repeated

- **WHEN** the user keeps chatting after the notice
- **THEN** the notice is not shown again that month

#### Scenario: Threshold in tokens

- **WHEN** a user sets the threshold in tokens
- **THEN** the month's tokens, not the estimated cost, are compared with it

#### Scenario: No threshold

- **WHEN** a user has set no threshold
- **THEN** no warning is shown

### Requirement: Usage belongs to one user

Usage records SHALL be owned by the user whose call made them. One user SHALL NOT see or change another user's usage. Deleting a conversation SHALL NOT delete its usage records. Deleting a user's data SHALL delete them.

#### Scenario: Two users

- **WHEN** user A has usage and user B has none
- **THEN** user B's usage section shows nothing used

#### Scenario: Conversation deleted

- **WHEN** a user deletes a conversation
- **THEN** the spend it caused is still in their usage totals
