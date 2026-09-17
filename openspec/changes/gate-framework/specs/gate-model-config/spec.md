## Purpose

Lets each user choose which Nebius model each gate uses, and how it is called. No gate has a default model: a gate is unset until the user picks one, guided by a hint that says what to prioritise. A model that cannot do what a gate needs is flagged, and the Test action is what proves it.

## ADDED Requirements

### Requirement: Fixed set of gates

The system SHALL offer a fixed set of gates. This release has four: `router`, `push`, `pull`, and `explore`. Each gate SHALL have a stable id, a name to show the user, a hint saying what to prioritise when choosing a model, and the list of model features it uses. Users SHALL NOT be able to add, rename, or remove gates. Adding a gate later SHALL NOT change the shape of the settings, the settings API, or the stored overrides.

#### Scenario: Listing the gates

- **WHEN** a logged-in user asks for their gate settings
- **THEN** the system returns exactly the four gates `router`, `push`, `pull`, and `explore`
- **AND** each gate carries its id, its display name, its hint, and the model features it uses

#### Scenario: Gate that does not exist

- **WHEN** a user saves, resets, or tests settings for a gate id that is not in the set
- **THEN** the system responds with HTTP 404 and error code `not_found`

#### Scenario: Explore uses tool calling

- **WHEN** a user asks for their gate settings
- **THEN** the `explore` gate lists tool calling among the model features it uses

### Requirement: Settings per gate

Every gate SHALL have a model, a temperature, a maximum number of tokens in a reply, and an optional reasoning effort. The model SHALL have no system default: until the user chooses one, the gate's model is unset. Temperature and token limit SHALL fall back to system defaults. Reasoning effort SHALL be sent to the provider only when the user has set it. The system SHALL report, per setting, whether the value in force came from the user, from the system, or is unset. Editing a gate's system prompt is out of scope.

#### Scenario: Nothing chosen yet

- **WHEN** a user with no override for a gate asks for their gate settings
- **THEN** the gate's model is reported as unset
- **AND** the temperature and token limit hold the system defaults and are reported as coming from the system
- **AND** the reasoning effort is reported as unset

#### Scenario: Override on some settings only

- **WHEN** a user has saved a model and a temperature for a gate, but no token limit
- **THEN** the model and temperature are the saved values and are reported as coming from the user
- **AND** the token limit is the system default and is reported as coming from the system

#### Scenario: Gate call uses the settings in force

- **WHEN** a gate calls a model for a user
- **THEN** it uses the model, temperature, and token limit that gate resolves to for that user
- **AND** it sends a reasoning effort only when that user has set one for the gate

### Requirement: Gate configuration is server configuration

The system SHALL hold, for every gate, a default temperature, a default token limit, and the hint shown with the model chooser, in server configuration outside the database. Configuration SHALL be readable by an operator without running the app. It SHALL NOT hold a default model for any gate. The system SHALL refuse to start when a gate has no configuration entry, when an entry is missing the temperature, the token limit, or the hint, or when a value is outside the allowed range.

#### Scenario: A gate has no configuration entry

- **WHEN** the server starts and one of the gates has no entry in configuration
- **THEN** the server fails to start
- **AND** the failure message names the gate and what is missing

#### Scenario: Entry without a hint

- **WHEN** the server starts and a gate's entry has no hint
- **THEN** the server fails to start
- **AND** the failure message names the gate

#### Scenario: Default outside the allowed range

- **WHEN** the server starts and a configured default temperature or token limit is outside the allowed range
- **THEN** the server fails to start
- **AND** the failure message names the gate and the setting

#### Scenario: No model ids in configuration

- **WHEN** an operator reads the gate configuration
- **THEN** it holds no model id for any gate

### Requirement: Model list with feature information

The system SHALL let a logged-in user list the models their own Nebius key can use. For every model the system SHALL report, for each model feature any gate uses, whether the provider says the model supports it, says it does not, or says nothing. This information SHALL be advisory: it SHALL NOT decide whether a model can be chosen, because a provider may under-report what a model can do.

#### Scenario: Model that reports tool calling

- **WHEN** a user lists models and a model reports that it supports tool calling
- **THEN** that model is marked as supporting tool calling

#### Scenario: Model that reports features but not tool calling

- **WHEN** a user lists models and a model reports its supported features, and tool calling is not among them
- **THEN** that model is marked as unconfirmed for tool calling rather than unusable

#### Scenario: Model that reports no feature information

- **WHEN** a user lists models and a model reports nothing about its supported features
- **THEN** that model is marked as unknown for tool calling

#### Scenario: Model list in the settings UI

- **WHEN** a user opens the model chooser for a gate that uses a feature
- **THEN** every model the user's key can use is selectable
- **AND** models that do not report the feature are marked as unconfirmed, with the Test action offered as the way to confirm them

### Requirement: An override is checked before it is saved

The system SHALL check an override before storing it. A model SHALL be stored only when it appears in the model list for that user's key. Temperature, token limit, and reasoning effort SHALL be within their allowed values. Nothing SHALL be stored when any part of the override is refused. A model that does not report a feature the gate uses SHALL still be stored.

#### Scenario: Valid override

- **WHEN** a user saves an override naming a model from their model list, with a temperature and token limit in range
- **THEN** the system stores the override
- **AND** the gate's settings report the new values as coming from the user

#### Scenario: Model not in the user's model list

- **WHEN** a user saves an override naming a model that their key cannot use
- **THEN** the system stores nothing
- **AND** the system responds with error code `gate_model_unknown` and a message naming the model

#### Scenario: Model that does not report a feature the gate uses

- **WHEN** a user saves an override for `explore` naming a model that does not report tool calling
- **THEN** the system stores the override
- **AND** the response marks the choice as unconfirmed for tool calling and points to the Test action

#### Scenario: Value out of range

- **WHEN** a user saves an override whose temperature or token limit is outside the allowed range
- **THEN** the system stores nothing
- **AND** the system responds with HTTP 422 and error code `validation_error`

#### Scenario: A refused override leaves an earlier one untouched

- **WHEN** a user who already has a saved override for a gate saves a new one that is refused
- **THEN** the earlier override is unchanged and still in force

### Requirement: A gate with no model cannot run

When a gate's model is unset, the system SHALL NOT choose a model for the user. It SHALL fail the call with error code `gate_model_not_set`, naming the gate and pointing to gate settings.

#### Scenario: Message sent to a gate with no model

- **WHEN** a gate with an unset model is asked to handle a message
- **THEN** the system responds with error code `gate_model_not_set` naming the gate
- **AND** no model is called

#### Scenario: A new user sends their first message

- **WHEN** a user who has never chosen any model sends a message with no command
- **THEN** the system responds with `gate_model_not_set` naming the router gate
- **AND** the message points the user to gate settings

### Requirement: Reset a gate

The system SHALL let a user delete a gate's override. After a reset the gate's model SHALL be unset again, its temperature and token limit SHALL be the system defaults, and its reasoning effort SHALL be unset. Resetting a gate that has no override SHALL succeed and change nothing.

#### Scenario: Reset a gate with an override

- **WHEN** a user resets a gate that has a saved override
- **THEN** the system deletes the override
- **AND** the gate's model is reported as unset and its other settings as coming from the system

#### Scenario: Reset a gate with no override

- **WHEN** a user resets a gate that has no saved override
- **THEN** the system reports success and the gate stays unset

#### Scenario: Reset affects one gate only

- **WHEN** a user with overrides on two gates resets one of them
- **THEN** the other gate's override is unchanged

### Requirement: Test a gate's model

The system SHALL let a user test a gate. A test SHALL send a short prompt to the gate's model in force, with that gate's temperature, token limit, and reasoning effort. For a gate that uses a model feature, the test SHALL exercise that feature. The test SHALL report either success or the reason it failed, and SHALL NOT change any stored setting.

#### Scenario: Test succeeds

- **WHEN** a user tests a gate whose model answers
- **THEN** the system reports success, naming the model that answered

#### Scenario: Test a gate with no model

- **WHEN** a user tests a gate whose model is unset
- **THEN** the system reports failure with error code `gate_model_not_set`

#### Scenario: Test on a model that cannot use the gate's feature

- **WHEN** a user tests `explore` and the model rejects or ignores the tool it was offered
- **THEN** the system reports failure with error code `gate_model_unsupported`, naming the feature

#### Scenario: Test when the model is gone

- **WHEN** a user tests a gate whose model the Nebius account can no longer use
- **THEN** the system reports failure with error code `gate_model_unavailable`

#### Scenario: Test when the provider refuses the reasoning effort

- **WHEN** a user tests a gate whose reasoning effort the model refuses
- **THEN** the system reports failure naming the reasoning effort as the reason
- **AND** the stored settings are unchanged

#### Scenario: Test that produces no answer within the token limit

- **WHEN** a user tests a gate and the model spends the whole token limit without producing an answer
- **THEN** the system reports failure saying the token limit was reached before an answer

#### Scenario: Test without a usable key

- **WHEN** a user with no saved Nebius key tests a gate
- **THEN** the system responds with error code `nebius_key_missing`

#### Scenario: Test leaves settings unchanged

- **WHEN** a test fails for any reason
- **THEN** the gate's stored override, if any, is unchanged

### Requirement: An unavailable model never falls back to another model

When a gate's model in force cannot be used, the system SHALL fail the call with an error that names the gate and the model and points the user to gate settings. The system SHALL NOT retry the call with any other model, and SHALL NOT change the stored settings.

#### Scenario: Gate model withdrawn by the provider

- **WHEN** a gate runs and Nebius reports that the gate's model does not exist or is not available to this key
- **THEN** the system responds with error code `gate_model_unavailable`
- **AND** the message names the gate and the model and points to gate settings
- **AND** no other model is called

#### Scenario: Nebius cannot be reached during a gate call

- **WHEN** a gate call times out, cannot connect, or gets a server error from Nebius
- **THEN** the system responds with error code `nebius_unreachable`
- **AND** no other model is called

### Requirement: Gate settings belong to one user

Gate overrides SHALL be owned by the user who saved them. One user's overrides SHALL NOT affect another user's gates, and SHALL NOT be readable or changeable by another user.

#### Scenario: Two users, different choices

- **WHEN** user A saves an override for a gate and user B has none
- **THEN** user B's gate is still unset

#### Scenario: Reset by another user

- **WHEN** user B resets a gate
- **THEN** user A's override for that gate is unchanged

### Requirement: Gate settings in the settings page

The settings page SHALL have a section for gate settings with one block per gate. Each block SHALL offer a model chooser, a temperature field, a token limit field, an optional reasoning effort, a "Test" action, and a "Reset" action. Each block SHALL show the gate's hint with its model chooser, and SHALL show, per setting, whether the value in force is the user's, the system's, or unset. The page SHALL show the outcome of a test and the reason a save was refused.

#### Scenario: Opening gate settings for the first time

- **WHEN** a user who has chosen nothing opens the gate settings section
- **THEN** each of the four gates appears with its model shown as not set
- **AND** each gate shows its hint saying what to prioritise, with an example model

#### Scenario: Settings show where each value came from

- **WHEN** a user with a saved model for one gate opens gate settings
- **THEN** that gate shows the model as coming from the user
- **AND** its temperature and token limit show whether they came from the user or the system

#### Scenario: Refused save shown to the user

- **WHEN** a save is refused because the model is not in the user's model list
- **THEN** the page shows a message naming the model and keeps the earlier values

#### Scenario: Gate settings without a Nebius key

- **WHEN** a user with no saved Nebius key opens gate settings
- **THEN** the page shows that a Nebius API key is needed, with a link to the API key settings
- **AND** the model choosers are empty rather than showing an unexplained failure
