# chat-model-loadout Specification

## Purpose

Lets each user choose which models the chat can use, from any provider they have a key for, and how they are called: one default model, a small loadout to switch between per conversation, a reasoning effort for each, and one temperature. No model is chosen for the user.

## Requirements

### Requirement: No default model

The system SHALL NOT choose a chat model for a user. Until the user picks a default model, the chat SHALL NOT call a model, and the system SHALL respond with error code `model_not_set` and point to the model settings. Server configuration SHALL NOT hold a model id.

#### Scenario: A new user sends their first message

- **WHEN** a user who has never chosen a model sends a message
- **THEN** the system responds with error code `model_not_set`
- **AND** no model is called

#### Scenario: No model ids in configuration

- **WHEN** an operator reads the server's chat configuration
- **THEN** it holds no model id

### Requirement: A default model and a loadout

The user SHALL be able to add up to five models from the model lists of the providers they have keys for, each entry being a provider and a model, to a loadout, mark one as the default, and remove models. Each model in the loadout SHALL have an optional reasoning effort. A new conversation SHALL start with the default model and its effort. Removing the default model SHALL require choosing another one, or leave the default unset.

#### Scenario: Add a model to the loadout

- **WHEN** a user adds a model from their model list
- **THEN** the loadout lists it and it can be chosen in a conversation

#### Scenario: Sixth model

- **WHEN** a user with five models in the loadout adds another
- **THEN** the system stores nothing and says the loadout is full

#### Scenario: Default model

- **WHEN** a user marks a loadout model as the default
- **THEN** new conversations start with that model and its effort

#### Scenario: Remove the default

- **WHEN** a user removes the default model
- **THEN** the default is unset until the user chooses another
- **AND** the chat responds with `model_not_set` for new conversations

### Requirement: One temperature and no token limit setting

The user SHALL have one temperature setting that applies to every chat call, within the allowed range, with a system default. The user SHALL NOT have a setting for the maximum length of a reply. The system SHALL apply its own limit.

#### Scenario: Temperature in force

- **WHEN** a user has not set a temperature
- **THEN** calls use the system default and the settings show that it comes from the system

#### Scenario: Temperature out of range

- **WHEN** a user saves a temperature outside the allowed range
- **THEN** the system stores nothing and responds with HTTP 422 and error code `validation_error`

#### Scenario: No token limit setting

- **WHEN** a user opens the model settings
- **THEN** there is no field for a reply length limit

### Requirement: A choice is checked before it is saved

The system SHALL check a loadout entry before storing it. The provider SHALL have a saved key for the user, and the model SHALL appear in that provider's model list for that key, and the reasoning effort SHALL be a value the provider documents. Nothing SHALL be stored when any part is refused, and an earlier choice SHALL stay in force.

#### Scenario: Model not in the user's list

- **WHEN** a user saves a model their key cannot use
- **THEN** nothing is stored
- **AND** the system responds with error code `model_unknown`, naming the provider and the model

#### Scenario: Unconfirmed tool calling

- **WHEN** a user saves a model that does not report tool calling
- **THEN** it is stored and marked unconfirmed, with the Test action offered

#### Scenario: A refused save keeps the earlier choice

- **WHEN** a save is refused
- **THEN** the earlier loadout is unchanged

### Requirement: Reasoning effort options come from configuration

The system SHALL hold, in server configuration, which reasoning efforts a model accepts, matched by model id. The effort choices offered for a model SHALL NOT include an effort that configuration marks as unsupported for it. For a model that configuration does not mention, every documented effort SHALL be offered, and the Test action SHALL report a problem with it. Reasoning effort SHALL be sent to the provider only when the user set one.

#### Scenario: Effort known to break a model

- **WHEN** configuration marks `none` as unsupported for a model
- **THEN** the effort choices for that model do not include `none`

#### Scenario: Model not in configuration

- **WHEN** a model is not mentioned in configuration
- **THEN** every documented effort is offered

#### Scenario: No effort set

- **WHEN** no effort is set for a model
- **THEN** no reasoning effort is sent to the provider

### Requirement: The composer picks the model and effort per conversation

The input box SHALL have a dropdown listing the loadout models and, for the chosen model, a reasoning effort choice. The choice SHALL be stored with the conversation. Changing it SHALL apply from the next message and SHALL keep the earlier messages as context. The dropdown SHALL link to the model settings.

#### Scenario: Switch model in a conversation

- **WHEN** a user picks another loadout model in the dropdown and sends a message
- **THEN** that message is answered by the new model with the earlier messages as context
- **AND** the conversation now stores the new model

#### Scenario: Effort choice

- **WHEN** a user picks an effort for the chosen model
- **THEN** it is stored with the conversation and sent with later calls

#### Scenario: New conversation

- **WHEN** a user starts a new conversation after switching model in another one
- **THEN** the new conversation starts with the default model

#### Scenario: Model outside the loadout

- **WHEN** an open conversation uses a model that is not in the loadout
- **THEN** the dropdown lists it, marked as not in the loadout, alongside the loadout models

### Requirement: Test a model

The system SHALL let a user test a model and effort. A test SHALL send a short prompt with the user's temperature and effort, and a one-tool probe. It SHALL report success naming the model, or the reason it failed, and SHALL NOT change any stored setting.

#### Scenario: Test succeeds

- **WHEN** a user tests a model that answers and can call the probe tool
- **THEN** the system reports success, naming the model

#### Scenario: Empty answer

- **WHEN** a test returns no text and no tool call
- **THEN** the system reports failure saying the model returned an empty answer, naming the effort if one was set

#### Scenario: Model that rejects tools

- **WHEN** the model rejects or ignores the probe tool
- **THEN** the system reports failure with error code `model_unsupported`, naming tool calling

#### Scenario: Effort refused

- **WHEN** the provider refuses the reasoning effort
- **THEN** the system reports failure naming the effort as the reason

#### Scenario: Model gone

- **WHEN** the account can no longer use the model
- **THEN** the system reports failure with error code `model_unavailable`

#### Scenario: No key

- **WHEN** a user with no saved key for the model's provider tests a model
- **THEN** the system responds with error code `provider_key_missing`

#### Scenario: Settings unchanged

- **WHEN** a test fails for any reason
- **THEN** every stored setting is unchanged

### Requirement: Model settings belong to one user

The loadout, default model, and temperature SHALL be owned by the user who saved them. One user's settings SHALL NOT affect, or be readable by, another user.

#### Scenario: Two users, different models

- **WHEN** user A saves a default model and user B has none
- **THEN** user B still has no default model

### Requirement: Model settings in the settings page

The settings page SHALL have a model section with the loadout as slots, the default marked, an effort choice for each, the temperature, and a Test action. It SHALL show a hint about what to look for in a chat model, with an example, and SHALL mark models that do not report tool calling as unconfirmed. Without a saved key it SHALL show that a provider key is needed, with a link to the provider settings, and empty choosers.

#### Scenario: First visit

- **WHEN** a user who has chosen nothing opens the model section
- **THEN** the default shows as not set, with the hint

#### Scenario: No key

- **WHEN** a user with no saved key opens the model section
- **THEN** the page shows that a provider key is needed, with a link to the provider settings

#### Scenario: Refused save shown

- **WHEN** a save is refused
- **THEN** the page shows the reason and keeps the earlier values

### Requirement: A conversation keeps its own model

A conversation SHALL keep the provider, model, and reasoning effort stored with it. Later changes to the default model or to the loadout SHALL NOT change an existing conversation. A conversation whose model is no longer in the loadout SHALL keep using it for as long as the user's key can use it, and the model dropdown SHALL still show it, marked as not in the loadout. A conversation with no model yet SHALL take the default model, with its effort, at its next message and store it. Switching a conversation to another model SHALL set its effort to that model's effort in the loadout, or to none, and SHALL NOT keep an effort the new model is known not to accept.

#### Scenario: Default changes later

- **WHEN** a user changes the default model after starting a conversation
- **THEN** the earlier conversation still uses its own model

#### Scenario: Model removed from the loadout

- **WHEN** a user removes a model from the loadout that an older conversation uses, and the key can still use it
- **THEN** the older conversation is still answered by that model
- **AND** the dropdown shows it, marked as not in the loadout

#### Scenario: Model withdrawn by the provider

- **WHEN** an older conversation's model is no longer available to the key
- **THEN** the system responds with error code `model_unavailable`, naming the model
- **AND** the user can pick another model in the dropdown and carry on with the earlier messages as context

#### Scenario: Conversation with no model yet

- **WHEN** a user with no default sends a first message, gets `model_not_set`, then chooses a default and sends again in the same conversation
- **THEN** the conversation stores the default at that message and uses it afterwards

#### Scenario: Effort follows the model

- **WHEN** a user switches a conversation from a model with effort `high` to a model that has no effort in the loadout
- **THEN** the conversation's effort is none

#### Scenario: Effort the new model refuses

- **WHEN** a user switches to a model that configuration marks as not accepting the conversation's effort
- **THEN** the effort is cleared
