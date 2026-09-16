## Purpose

Lets each user choose which Nebius model each gate uses, and with which temperature and token limit. Every gate has a system default, a user can override it, and a model that cannot do what a gate needs is refused before it is saved.

## ADDED Requirements

### Requirement: Fixed set of gates

The system SHALL offer a fixed set of gates. This release has four: `router`, `push`, `pull`, and `explore`. Each gate SHALL have a stable id, a name to show the user, and the list of model features it needs. Users SHALL NOT be able to add, rename, or remove gates. Adding a gate later SHALL NOT change the shape of the settings, the settings API, or the stored overrides.

#### Scenario: Listing the gates

- **WHEN** a logged-in user asks for their gate settings
- **THEN** the system returns exactly the four gates `router`, `push`, `pull`, and `explore`
- **AND** each gate carries its id, its display name, and the model features it needs

#### Scenario: Gate that does not exist

- **WHEN** a user saves, resets, or tests settings for a gate id that is not in the set
- **THEN** the system responds with HTTP 404 and error code `not_found`

#### Scenario: Explore needs tool calling

- **WHEN** a user asks for their gate settings
- **THEN** the `explore` gate lists tool calling among the model features it needs

### Requirement: Three settings per gate

Every gate SHALL have exactly three settings: the model, the temperature, and the maximum number of tokens in a reply. Each setting SHALL take the user's override when one exists for that setting, and the system default otherwise. The system SHALL report, per setting, whether the value in force came from the user or from the system. Editing a gate's system prompt is out of scope.

#### Scenario: No override saved

- **WHEN** a user with no override for a gate asks for their gate settings
- **THEN** all three settings hold the system default values for that gate
- **AND** each setting is reported as coming from the system

#### Scenario: Override on some settings only

- **WHEN** a user has saved an override for a gate's temperature but not for its model or token limit
- **THEN** the temperature is the saved value and is reported as coming from the user
- **AND** the model and token limit are the system defaults and are reported as coming from the system

#### Scenario: Gate call uses the settings in force

- **WHEN** a gate calls a model for a user
- **THEN** it uses the model, temperature, and token limit that gate resolves to for that user

### Requirement: System defaults are server configuration

The system SHALL hold a default model, temperature, and token limit for every gate in server configuration, outside the database. Defaults SHALL be readable by an operator without running the app. The system SHALL refuse to start when a gate has no default, when a default is missing one of the three settings, or when a default value is outside the allowed range.

#### Scenario: A gate has no configured default

- **WHEN** the server starts and one of the gates has no default settings in configuration
- **THEN** the server fails to start
- **AND** the failure message names the gate and the missing settings

#### Scenario: Default outside the allowed range

- **WHEN** the server starts and a configured default temperature or token limit is outside the allowed range
- **THEN** the server fails to start
- **AND** the failure message names the gate and the setting

### Requirement: Model list marked for each gate's needs

The system SHALL let a logged-in user list the models their own Nebius key can use. For every model the system SHALL report, for each model feature any gate needs, whether the model supports it, does not support it, or whether support is unknown because the model reports nothing about that feature.

#### Scenario: Model that reports tool calling

- **WHEN** a user lists models and a model reports that it supports tool calling
- **THEN** that model is marked as supporting tool calling

#### Scenario: Model that reports features but not tool calling

- **WHEN** a user lists models and a model reports its supported features, and tool calling is not among them
- **THEN** that model is marked as not supporting tool calling

#### Scenario: Model that reports no feature information

- **WHEN** a user lists models and a model reports nothing about its supported features
- **THEN** that model is marked as unknown for tool calling, not as supporting or not supporting it

#### Scenario: Model list in the settings UI

- **WHEN** a user opens the model dropdown for a gate that needs a feature
- **THEN** models that do not support that feature are shown as not usable for this gate and cannot be chosen
- **AND** models whose support is unknown can be chosen and are shown as unconfirmed

### Requirement: An override is checked before it is saved

The system SHALL check an override before storing it. A model SHALL be stored only when it appears in the model list for that user's key. A model that is marked as not supporting a feature the gate needs SHALL be refused. Temperature and token limit SHALL be within the allowed range. Nothing SHALL be stored when any part of the override is refused.

#### Scenario: Valid override

- **WHEN** a user saves an override naming a model from their model list, with a temperature and token limit in range
- **THEN** the system stores the override
- **AND** the gate's settings report the new values as coming from the user

#### Scenario: Model not in the user's model list

- **WHEN** a user saves an override naming a model that their key cannot use
- **THEN** the system stores nothing
- **AND** the system responds with error code `gate_model_unknown` and a message naming the model

#### Scenario: Model lacks a feature the gate needs

- **WHEN** a user saves an override for `explore` naming a model marked as not supporting tool calling
- **THEN** the system stores nothing
- **AND** the system responds with error code `gate_model_unsupported` and a message naming the missing feature

#### Scenario: Same model allowed on a gate that does not need the feature

- **WHEN** a user saves an override for `push` naming a model that does not support tool calling
- **THEN** the system stores the override, because `push` does not need tool calling

#### Scenario: Value out of range

- **WHEN** a user saves an override whose temperature or token limit is outside the allowed range
- **THEN** the system stores nothing
- **AND** the system responds with HTTP 422 and error code `validation_error`

#### Scenario: A refused override leaves an earlier one untouched

- **WHEN** a user who already has a saved override for a gate saves a new one that is refused
- **THEN** the earlier override is unchanged and still in force

### Requirement: Reset a gate to its default

The system SHALL let a user delete a gate's override. After a reset the gate SHALL use the system defaults for all three settings. Resetting a gate that has no override SHALL succeed and change nothing.

#### Scenario: Reset a gate with an override

- **WHEN** a user resets a gate that has a saved override
- **THEN** the system deletes the override
- **AND** the gate's settings report the system defaults as coming from the system

#### Scenario: Reset a gate with no override

- **WHEN** a user resets a gate that has no saved override
- **THEN** the system reports success and the gate keeps its system defaults

#### Scenario: Reset affects one gate only

- **WHEN** a user with overrides on two gates resets one of them
- **THEN** the other gate's override is unchanged

### Requirement: Test a gate's model

The system SHALL let a user test a gate. A test SHALL send a short prompt to the gate's model in force, with that gate's temperature and token limit. For a gate that needs a model feature, the test SHALL exercise that feature. The test SHALL report either success or the reason it failed, and SHALL NOT change any stored setting.

#### Scenario: Test succeeds

- **WHEN** a user tests a gate whose model answers
- **THEN** the system reports success, naming the model that answered

#### Scenario: Test on a model the gate's feature check fails

- **WHEN** a user tests `explore` and the model rejects or ignores the tool it was offered
- **THEN** the system reports failure with error code `gate_model_unsupported`

#### Scenario: Test when the model is gone

- **WHEN** a user tests a gate whose model the Nebius account can no longer use
- **THEN** the system reports failure with error code `gate_model_unavailable`

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

#### Scenario: Default model withdrawn

- **WHEN** a gate with no user override runs and its system default model is not available
- **THEN** the system responds with error code `gate_model_unavailable` and tells the user to choose a model for that gate

#### Scenario: Nebius cannot be reached during a gate call

- **WHEN** a gate call times out, cannot connect, or gets a server error from Nebius
- **THEN** the system responds with error code `nebius_unreachable`
- **AND** no other model is called

### Requirement: Gate settings belong to one user

Gate overrides SHALL be owned by the user who saved them. One user's overrides SHALL NOT affect another user's gates, and SHALL NOT be readable or changeable by another user.

#### Scenario: Two users, different overrides

- **WHEN** user A saves an override for a gate and user B has none
- **THEN** user B's gate still resolves to the system defaults

#### Scenario: Reset by another user

- **WHEN** user B resets a gate
- **THEN** user A's override for that gate is unchanged

### Requirement: Gate settings in the settings page

The settings page SHALL have a section for gate settings with one block per gate. Each block SHALL offer a model dropdown, a temperature field, a token limit field, a "Test" action, and a "Reset to default" action. Each block SHALL show, per setting, whether the value in force is the user's or the system's. The page SHALL show the outcome of a test and the reason a save was refused.

#### Scenario: Opening gate settings

- **WHEN** a user opens the gate settings section
- **THEN** each of the four gates appears with its current model, temperature, and token limit
- **AND** each setting shows whether it came from the user or the system

#### Scenario: Refused save shown to the user

- **WHEN** a save is refused because the model lacks a feature the gate needs
- **THEN** the page shows a message naming the missing feature and keeps the earlier values

#### Scenario: Gate settings without a Nebius key

- **WHEN** a user with no saved Nebius key opens gate settings
- **THEN** the page shows that a Nebius API key is needed, with a link to the API key settings
- **AND** the model dropdowns are empty rather than showing an unexplained failure
