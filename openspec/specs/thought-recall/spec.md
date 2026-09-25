# thought-recall Specification

## Purpose

Shows the thoughts an answer was built from as sources under it, which the user can sort, filter by tag, and open, and keeps the model from inventing an answer when nothing matches.

## Requirements

### Requirement: An answer lists its sources

When a search in an answer returns thoughts, the chat SHALL list them as sources under that answer, in the order the search returned them, each with its title, date, and tags. Each source SHALL open the thought. When an answer ran more than one search, the sources SHALL be the thoughts of every search, each once, in the order they first appeared. The sources SHALL be the thoughts the model was shown, not every thought that matched.

#### Scenario: Sources shown

- **WHEN** a user asks `what did I say about milk?` and the search returns `Oat milk` and `Shopping list`
- **THEN** the answer shows both as sources, `Oat milk` first
- **AND** each shows its date and tags

#### Scenario: Open a source

- **WHEN** a user clicks a source
- **THEN** the thought opens in the detail view

#### Scenario: Two searches in one answer

- **WHEN** the model runs two searches in one answer and both return `Oat milk`
- **THEN** `Oat milk` is listed once

#### Scenario: Reopened conversation

- **WHEN** a user opens a conversation again later
- **THEN** each answer shows the same sources it showed before

### Requirement: Sources can be sorted newest first

The sources list SHALL offer a toggle between relevance order and newest first. Newest first SHALL re-sort the same sources by the date they were filed, with no new search.

#### Scenario: Newest first

- **WHEN** a user turns on newest first for sources filed on 2026-08-02 and 2026-09-20
- **THEN** the source from 2026-09-20 is first
- **AND** no search runs

#### Scenario: Back to relevance

- **WHEN** the user turns the toggle off
- **THEN** the sources are back in the search's order

### Requirement: Sources can be filtered by tag

The sources list SHALL offer the tags its sources carry, and the user SHALL be able to pick one or more. With tags picked, the list SHALL show only sources with at least one of them. The filter SHALL act on the listed sources only, with no new search, and SHALL NOT change the answer.

#### Scenario: One tag

- **WHEN** a user picks the tag `travel` on a list with one `travel` source and two others
- **THEN** only the `travel` source is shown

#### Scenario: Two tags

- **WHEN** a user picks `travel` and `work`
- **THEN** sources with either tag are shown

#### Scenario: Clear

- **WHEN** the user clears the picked tags
- **THEN** every source is shown again

### Requirement: No match is said plainly

When a search returns no thoughts, the answer SHALL show no sources, and the model SHALL say that nothing filed matched. The model SHALL NOT present an answer as coming from the user's thoughts when the search returned none.

#### Scenario: Nothing filed about it

- **WHEN** a user asks `what did I decide about the boat?` and the search returns nothing
- **THEN** the answer says nothing filed matched
- **AND** no sources are shown
- **AND** the answer does not describe a decision about a boat as the user's

### Requirement: A source that no longer exists

A source whose thought was deleted SHALL stay in the list, and opening it SHALL say that the thought no longer exists.

#### Scenario: Deleted thought

- **WHEN** a user deletes their content and then opens a source in an old answer
- **THEN** the chat says the thought no longer exists
