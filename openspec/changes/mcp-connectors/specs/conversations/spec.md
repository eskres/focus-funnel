# Spec Delta

## ADDED Requirements

### Requirement: A conversation keeps which connectors are on

A conversation SHALL store which of the user's connectors are on in it. A new conversation SHALL store none. Resuming, archiving, and restoring a conversation SHALL keep its connectors. The conversation's details SHALL list its connectors that are on, so the toggle shows them when the conversation is opened. A connector that is removed, or that the operator no longer defines, SHALL no longer be listed for any conversation, and the conversation SHALL go on without it.

#### Scenario: Resume keeps connectors

- **WHEN** a user turns on the calendar connector, leaves the conversation, and opens it again later
- **THEN** the calendar connector is still on

#### Scenario: Operator removes a connector

- **WHEN** the operator removes a connector from the configuration and restarts the server
- **THEN** conversations that had it on no longer list it and no longer offer its tools
- **AND** their messages, including earlier results from that connector, are kept

#### Scenario: Another user's conversation

- **WHEN** a user tries to turn a connector on in a conversation that belongs to someone else
- **THEN** the system responds with HTTP 404 and error code `not_found`
