## Purpose

Defines the providers a user can call, and what is known about each: how to reach it, what its model list reports, how it reports usage, and what the user should know about how it handles their prompts. Any OpenAI-compatible endpoint can be a provider.

## ADDED Requirements

### Requirement: Providers are presets or a custom URL

The system SHALL offer a fixed set of provider presets, each with a stable id, a name, a base URL, a link to where a user gets a key, and a data-handling notice. The presets are Nebius, NVIDIA, and OpenRouter. The system SHALL also offer a custom provider with a base URL entered by the user, for a local or self-hosted model server. The base URLs of presets SHALL NOT be changeable by users.

#### Scenario: Listing presets

- **WHEN** a user lists providers
- **THEN** each preset appears with its name, a link to get a key, and its data-handling notice
- **AND** the custom provider appears with a field for a base URL

#### Scenario: Custom provider

- **WHEN** a user saves a custom provider with a base URL and a key that the endpoint accepts
- **THEN** the provider is stored for that user and its models can be listed

#### Scenario: Preset base URL

- **WHEN** a user tries to change a preset provider's base URL
- **THEN** the system refuses and the base URL is unchanged

### Requirement: The custom provider can be disabled

The operator SHALL be able to disable the custom provider in server configuration. When it is disabled, the system SHALL refuse to save or use a custom base URL, and SHALL respond with a validation error.

#### Scenario: Custom provider disabled

- **WHEN** the custom provider is disabled and a user submits a custom base URL
- **THEN** nothing is stored
- **AND** the system responds with HTTP 422 and error code `validation_error`, saying that custom providers are turned off

#### Scenario: Base URL must be a web address

- **WHEN** a user submits a custom base URL that is not an http or https address
- **THEN** nothing is stored
- **AND** the system responds with HTTP 422 and error code `validation_error`

### Requirement: Provider configuration is server configuration

The system SHALL hold each preset's base URL, key link, data-handling notice, and capabilities in server configuration outside the database, readable by an operator without running the app. The capabilities SHALL say whether the provider's model list reports prices, context length, and features, and how the provider reports token usage in a stream. The configuration SHALL NOT hold any key. The system SHALL refuse to start when a preset is missing its base URL or any capability, or when two presets share an id.

#### Scenario: A preset missing its base URL

- **WHEN** the server starts and a preset has no base URL
- **THEN** the server fails to start
- **AND** the failure message names the preset

#### Scenario: A preset missing a capability

- **WHEN** the server starts and a preset does not say how it reports token usage
- **THEN** the server fails to start
- **AND** the failure message names the preset and the capability

#### Scenario: No keys in configuration

- **WHEN** an operator reads the provider configuration
- **THEN** it holds no API key

### Requirement: Model list per provider

The system SHALL let a logged-in user list the models a provider offers with that user's own key. The list SHALL come from the provider, using that user's key and no other user's key. A user with no usable key SHALL be told so, with a pointer to the provider settings, and SHALL NOT be shown an empty list.

#### Scenario: User with a working key

- **WHEN** a user with a saved, working key lists a provider's models
- **THEN** the system returns the models that key can use

#### Scenario: User with no saved key

- **WHEN** a user with no saved key for a provider lists its models
- **THEN** the system responds with error code `provider_key_missing`
- **AND** the user sees a message with a link to the provider settings

#### Scenario: Saved key no longer accepted

- **WHEN** the provider rejects the user's saved key while listing models
- **THEN** the system responds with error code `provider_key_rejected`

#### Scenario: Provider cannot be reached

- **WHEN** the provider times out, cannot be connected to, or returns a server error while listing models
- **THEN** the system responds with error code `provider_unreachable`
- **AND** the system does not present a partial or stale list as complete

#### Scenario: One user's key never lists for another

- **WHEN** two users with different keys each list models
- **THEN** each list is built with that user's own key

### Requirement: Model information is passed on only when the provider reports it

For each model, the system SHALL report the context length and per-token prices when the provider's list includes them, and SHALL report them as absent otherwise. It SHALL NOT estimate them.

#### Scenario: Provider reports prices

- **WHEN** a provider's model list includes prices and a context length
- **THEN** the system returns them with the model

#### Scenario: Provider reports neither

- **WHEN** a provider's model list has no prices or context length
- **THEN** those fields are absent for its models and the list is otherwise complete

### Requirement: Model list with feature information

For each model the system SHALL report whether the provider says it supports tool calling, says it does not, or says nothing. This information SHALL be advisory and SHALL NOT decide whether a model can be chosen, because a provider may under-report what a model can do.

#### Scenario: Model that reports tool calling

- **WHEN** a provider's list says a model supports tool calling
- **THEN** the model is marked as supporting tool calling

#### Scenario: Model that reports features but not tool calling

- **WHEN** a model reports its features and tool calling is not among them
- **THEN** it is marked as unconfirmed for tool calling and stays selectable

#### Scenario: Model that reports no features

- **WHEN** a provider reports nothing about a model's features, or its list has no feature field at all
- **THEN** the model is marked as unknown for tool calling

### Requirement: The provider's data-handling notice is shown before first use

Before a user saves a key for a provider, the system SHALL show that provider's data-handling notice, and SHALL let the user see it again later in the provider's settings. The notice text SHALL come from server configuration, so an operator can adapt it.

#### Scenario: First key for a provider

- **WHEN** a user starts to save a key for a provider that has a notice
- **THEN** the notice is shown and the user must accept it before the key is saved

#### Scenario: Reading it later

- **WHEN** a user opens a provider's settings after saving a key
- **THEN** the notice is available to read

### Requirement: Provider errors are named the same way for every provider

The system SHALL map a provider's failures to the same error codes whichever provider it is: an unreachable provider to `provider_unreachable`, a rate limit to `provider_rate_limited`, and any other client error that has no code of its own to `provider_request_refused`, carrying the provider's message. It SHALL NOT retry a failed call against another provider or model.

#### Scenario: Rate limit

- **WHEN** a provider refuses a call because too many requests were sent
- **THEN** the system responds with error code `provider_rate_limited`, saying to wait and try again

#### Scenario: Another refusal

- **WHEN** a provider refuses a call with a client error that has no other code, such as an account with no credit
- **THEN** the system responds with error code `provider_request_refused` carrying the provider's message

#### Scenario: No retry elsewhere

- **WHEN** any provider call fails
- **THEN** no other provider or model is called
