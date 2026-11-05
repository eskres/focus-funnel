## ADDED Requirements

### Requirement: The model proposes reminders only when asked

A proposal part's date SHALL take optional reminders, and so SHALL each of its two date choices. The proposal tool SHALL tell the model to give reminders only when the user asks to be reminded, in minutes before the start, with 0 when the user names no time before.

#### Scenario: Remind me with no time

- **WHEN** a user sends `/push call mum Sunday, remind me` on Wednesday 4 November 2026
- **THEN** the proposal part has the start `2026-11-08` and the reminder 0

#### Scenario: The day before

- **WHEN** a user sends `/push passport renewal on 20 November, remind me the day before`
- **THEN** the proposal part has the start `2026-11-20` and the reminder 1,440

### Requirement: Repeats and reminders from the model are checked and noted

A repeat or reminders the model gives that are not valid SHALL be dropped from the part, and the rest of the part, its date included, SHALL be kept. A held proposal's note to the model SHALL include each part's repeat and reminders.

#### Scenario: Not valid from the model

- **WHEN** the model proposes a part dated `2026-11-09` with a repeat every `fortnight`
- **THEN** the card shows the part with the date `2026-11-09` and no repeat

#### Scenario: Held proposal with a repeat

- **WHEN** a proposal with a part repeating every week on Monday is held and the user sends another message
- **THEN** the note to the model about the held proposal says that the part repeats every week on Monday

### Requirement: The model reads that a thought repeats

The model SHALL be told that marking a repeating thought done ends all its occurrences. Wherever the model reads a filed thought by its ref, in the seen-thoughts note, in a list of similar-thought candidates, and in the search result, a repeating thought SHALL show that it repeats and how. When to propose a mark on a repeating thought is set by the mark requirements below.

#### Scenario: Seen weekly thought

- **WHEN** a conversation has seen `Take the bins out`, repeating every week on Monday
- **THEN** the note to the model about the thoughts the conversation has seen says that `Take the bins out` repeats every week on Monday

#### Scenario: Weekly thought among similar thoughts

- **WHEN** a user sends `/push took the bins out` and `Take the bins out`, repeating every week on Monday, is a similar-thought candidate
- **THEN** the candidate list says that `Take the bins out` repeats every week on Monday

### Requirement: The search result shows a repeat

The search result SHALL show a repeating thought once, with the occurrence that matched, or its first occurrence when no thought-date filter was given, and with its repeat.

#### Scenario: What is on this week

- **WHEN** a user with `Take the bins out`, repeating every week on Monday from 2 November 2026, asks what is on this week on Wednesday 11 November 2026
- **THEN** the search result lists `Take the bins out` once, on Monday 9 November, and says it repeats every week on Monday

## MODIFIED Requirements

### Requirement: The tools carry dates

Each proposal part SHALL take an optional date: a start, and an optional end, each a date or a date and time. Instead of one date, a part SHALL be able to give two date choices. The proposal tool SHALL tell the model to give a date only when the thought is about a set date or time, to work out a weekday or a relative day such as "tomorrow" from today's date, and to give a time or an end only when the user names one. A weekday SHALL mean the soonest such day after today, with one date, except for a repeating date (below). The model SHALL NOT guess an ambiguous day, and SHALL give two choices instead:

- A weekday that is today's weekday: today, and the same weekday one week later.
- "Next" with a weekday: the soonest such day after today, and the same weekday one week after that.

A date SHALL take an optional repeat, and a date choice SHALL NOT take one. The model SHALL be told to give a repeat only when the user says the thing repeats. A repeating date SHALL start at its first occurrence on or after today, where today counts: a weekday that is today's weekday SHALL mean today. A repeating date SHALL NOT get two choices, and a repeat the model gives on a choice SHALL be dropped, and the choice kept.

The model SHALL be told that weeks start on Monday, so "this week" runs from Monday to Sunday. A date or a choice the model gives that is not valid SHALL be dropped from the part, and the rest of the part SHALL be kept; when one valid choice is left, it SHALL become the part's date. The search tool SHALL take an optional first and last day for the thought's own date, separate from its start date for when the thought was filed, and the query SHALL be optional when those days are given. The search result SHALL show each dated thought's date. A held proposal's note to the model SHALL include each part's date, or both its choices.

#### Scenario: What is on this week

- **WHEN** a user asks what is on this week on Friday 2 October 2026
- **THEN** the model can call the search tool with no query and the days 28 September to 4 October 2026 as the thought's dates
- **AND** the tool result lists the dated thoughts in those days, each with its date

#### Scenario: Another weekday

- **WHEN** a user sends `/push dinner with Sam Friday at 7` on Wednesday 30 September 2026
- **THEN** the proposal part has the one date `2026-10-02T19:00` and no choices

#### Scenario: Today's weekday

- **WHEN** a user sends `/push dinner with Sam Friday at 7` on Friday 2 October 2026
- **THEN** the proposal part has two choices, `2026-10-02T19:00` and `2026-10-09T19:00`, and no single date

#### Scenario: Next weekday

- **WHEN** a user sends `/push call the plumber next Friday` on Wednesday 30 September 2026
- **THEN** the proposal part has two choices, `2026-10-02` and `2026-10-09`, and no single date

#### Scenario: Relative day

- **WHEN** a user sends `/push dentist tomorrow at 9` on Wednesday 30 September 2026
- **THEN** the proposal part has the start `2026-10-01T09:00` and no end

#### Scenario: Not valid from the model

- **WHEN** the model proposes a part with the start `2026-02-30`
- **THEN** the card shows the part's title, summary, tags, and category, and no date

#### Scenario: Held proposal with a date

- **WHEN** a proposal with a dated part is held and the user sends another message
- **THEN** the note to the model about the held proposal includes the part's date

#### Scenario: One valid choice

- **WHEN** the model gives a part the two choices `2026-10-02` and `2026-02-30`
- **THEN** the part has the one date `2026-10-02` and no choices

#### Scenario: Every Friday said on a Friday

- **WHEN** a user sends `/push yoga every Friday at 7am` on Friday 6 November 2026
- **THEN** the proposal part has the one date `2026-11-06T07:00`, repeating every week on Friday, and no choices

#### Scenario: Every Monday said on a Wednesday

- **WHEN** a user sends `/push take the bins out every Monday` on Wednesday 4 November 2026
- **THEN** the proposal part has the one date `2026-11-09`, repeating every week on Monday, and no choices

#### Scenario: One-off

- **WHEN** a user sends `/push dinner with Sam Friday at 7` on Wednesday 4 November 2026
- **THEN** the proposal part has no repeat

#### Scenario: Repeat on a choice

- **WHEN** the model gives a part the two choices `2026-11-06` and `2026-11-13`, each with a repeat every week on Friday
- **THEN** the part has the two choices, and neither has a repeat

### Requirement: The model proposes marking thoughts done

The proposal tool SHALL let the model name, by its ref, a thought the conversation has seen, to mark it done, beside or instead of new thoughts and additions, in the same proposal. The system SHALL steer the model to propose such a mark when the user says they finished a thing the conversation has seen. Before archive and `/compact`, the system SHALL steer the model not to propose a new thought for a finished task that the conversation already proposed to mark done. A repeating thought SHALL be the exception: the system SHALL steer the model not to propose marking a thought that repeats done because the user says they did it once, and to propose the mark only when the user says the repeating thing has ended or they stopped it.

#### Scenario: I called the plumber

- **WHEN** a conversation filed the task `Call the plumber`, and the user then sends `I called the plumber`
- **THEN** the model makes a proposal with one part that marks `Call the plumber` done
- **AND** the task is still open

#### Scenario: Done and something new

- **WHEN** a conversation has seen the task `Call the plumber`, and the user sends `I called the plumber, and I need to buy oat milk`
- **THEN** the model makes one proposal with two parts: one that marks `Call the plumber` done, and one new thought about oat milk

#### Scenario: Only a finished task at /compact

- **WHEN** a conversation's only exchange is `I called the plumber` and a confirmed card that marked `Call the plumber` done, and the user sends `/compact`
- **THEN** the model is asked for a proposal, and proposes no new thought about calling the plumber

#### Scenario: One week's bins

- **WHEN** a conversation has seen `Take the bins out`, an open thought repeating every week, and the user says "I took the bins out"
- **THEN** the model does not propose marking it done

#### Scenario: Stopped for good

- **WHEN** the same user says "we don't do the bins any more, the council collects them"
- **THEN** the model proposes marking `Take the bins out` done

### Requirement: The model finds a finished task it has not seen

When the user says they finished a thing the conversation has not seen, the system SHALL steer the model to search the user's open thoughts for it before any proposal in that turn, and then to make one proposal with the mark, by the ref the search gave, and anything else to propose. When the search finds no open thought for it, the model SHALL NOT propose a mark. When the open thought the search finds repeats, the model SHALL propose the mark only when the user says the repeating thing has ended or they stopped it. A turn SHALL have room for a refused proposal, a search, a second proposal, and the reply.

#### Scenario: Task filed in another conversation

- **WHEN** a user filed `Call the plumber` in another conversation, and sends `I called the plumber` in a new one
- **THEN** the model searches with the status `open`, and then proposes marking `Call the plumber` done

#### Scenario: Nothing open matches

- **WHEN** a user has no open thought about a plumber and sends `I called the plumber`
- **THEN** no card marks any thought done

#### Scenario: Unseen finished task and something new

- **WHEN** a user filed `Call the plumber` in another conversation, and sends `I called the plumber, and I need to buy oat milk` in a new one
- **THEN** the model searches with the status `open` before it proposes anything
- **AND** it then makes one proposal that marks `Call the plumber` done and proposes a new thought about oat milk

#### Scenario: Guessed ref, then search

- **WHEN** the model first proposes a mark on a ref the conversation has not seen, and the user filed `Call the plumber` elsewhere
- **THEN** the model can still search, propose marking `Call the plumber` done, and reply in the same turn

#### Scenario: Unseen weekly thought

- **WHEN** a user filed `Take the bins out`, repeating every week on Monday, in another conversation, and sends `I took the bins out` in a new one
- **THEN** no card marks `Take the bins out` done

### Requirement: A finished task among similar thoughts is marked done

The system SHALL steer the model to send a mark only with a ref the conversation has seen. When the similar-thought check lists an open thought that the user's message says they finished, the system SHALL steer the model to propose marking that thought done, by the ref the check gave, instead of proposing the finished thing as a new thought or as an addition. This SHALL also hold when `/push` forces the turn's first call to be a proposal, so that the search cannot come first. When the listed open thought repeats, the system SHALL steer the model not to mark it done unless the user says the repeating thing has ended or they stopped it; the turn SHALL then end with no mark, and with either one new note about what the user did or no card.

#### Scenario: Push a finished task the conversation has not seen

- **WHEN** a user filed the open task `Call the plumber` in another conversation, and sends `/push I called the plumber` in a new one
- **THEN** the turn ends with one proposal, and it marks `Call the plumber` done
- **AND** it proposes no new thought about calling the plumber and no addition to `Call the plumber`

#### Scenario: Finished task listed as a similar thought

- **WHEN** the model proposes a new note `Called the plumber`, and the similar-thought check lists the open task `Call the plumber` by its ref
- **THEN** the model's next proposal marks `Call the plumber` done by that ref, and holds no part about calling the plumber

#### Scenario: Push one occurrence of a weekly thought

- **WHEN** a user filed `Take the bins out`, repeating every week on Monday, in another conversation, sends `/push took the bins out` in a new one, and the similar-thought check lists `Take the bins out` by its ref
- **THEN** no card marks `Take the bins out` done
- **AND** the turn ends with either one card holding a new note about taking the bins out, or no card

### Requirement: The repeated-task line leaves room for a finished task

When the similar-thought check asks about a new part with the category `task`, its line that a repeated task is usually a new task SHALL say that this does not hold when the user says they finished it. When a listed thought repeats, the tool result SHALL also say that a repeating thought is marked done only when the user says it has ended or they stopped it.

#### Scenario: Finished task question for a task part

- **WHEN** the model's new note about calling the plumber has the category `task`, and the similar-thought check lists the open task `Call the plumber`
- **THEN** the tool result says a repeated task is usually a new task unless the user says they finished it
- **AND** the model's next proposal marks `Call the plumber` done by that ref, and holds no part about calling the plumber

#### Scenario: Task question with a repeating thought listed

- **WHEN** the model's new note about taking the bins out has the category `task`, and the similar-thought check lists the open `Take the bins out`, repeating every week on Monday
- **THEN** the tool result says a repeating thought is marked done only when the user says it has ended or they stopped it
- **AND** the model's next proposal does not mark `Take the bins out` done

### Requirement: A held part the user finished is not filed

When the user says they finished a thing that is a part of the held proposal that was never confirmed, there is no thought to mark. The system SHALL steer the model to leave that part out of its next proposal, to propose no mark for it, and to tell the user that the card was never filed and can be passed over. When that held part repeats, doing it once does not end it: the system SHALL steer the model to keep the part, with its repeat, in its next proposal, to propose no mark for it, and not to tell the user that the card can be passed over.

#### Scenario: Finished before it was filed

- **WHEN** a proposal from `/push call the plumber` is held and not confirmed, the user has no filed thought about a plumber, and the user sends `I called the plumber`
- **THEN** no card files `Call the plumber` and no card marks it done
- **AND** the reply says the plumber card was never filed and can be passed over

#### Scenario: One occurrence of a held weekly part

- **WHEN** a proposal from `/push take the bins out every Monday` is held and not confirmed, and the user sends `I took the bins out`
- **THEN** no card marks any thought done
- **AND** the bins part, repeating every week on Monday, is still held, or is in the turn's new proposal with its repeat
- **AND** the reply does not say the bins card can be passed over

### Requirement: Several open matches mark the newest

When a search for a finished thing finds several open thoughts for it, the system SHALL steer the model to propose marking only the most recently filed one done, and to name the older ones in its reply, so the user can close them from the sheet. A match that repeats SHALL never be the one marked because the user did the thing once; it SHALL be marked only when the user says the repeating thing has ended or they stopped it.

#### Scenario: Several open matches

- **WHEN** a user filed the task `Buy oat milk` in October and again in November, both are open, and the user sends `I bought the oat milk` in a new conversation
- **THEN** the model searches with the status `open`, and then proposes one mark, on the `Buy oat milk` filed in November
- **AND** its reply names the older `Buy oat milk`, so the user can close it from the sheet

#### Scenario: A repeating match among several

- **WHEN** a user filed `Take the bins out` in October, a one-off, and in November `Take the bins out`, repeating every week on Monday, both are open, and the user sends `I took the bins out` in a new conversation
- **THEN** no card marks the repeating `Take the bins out` done

### Requirement: A finished task with a held proposal

When a proposal is held and the user's message says they finished a thing that is not a part of the held proposal, the system SHALL steer the model to make one proposal that holds the held proposal's parts and the mark. When the thing is not among the thoughts the conversation has seen, the model SHALL first search the user's open thoughts for it, before it proposes the held proposal again. When the finished thing is an open thought that repeats, the system SHALL steer the model to keep the held parts and to add no mark, unless the user says the repeating thing has ended or they stopped it.

#### Scenario: Held proposal and an unseen finished task

- **WHEN** a proposal about oat milk is held, and the user sends `I called the plumber` about a task filed in another conversation
- **THEN** the model searches with the status `open` first
- **AND** it then makes one proposal that holds the oat milk part and marks `Call the plumber` done

#### Scenario: Held proposal and a seen finished task

- **WHEN** the conversation filed the task `Call the plumber`, a later proposal about oat milk is held, and the user sends `I called the plumber`
- **THEN** the model makes one proposal that holds the oat milk part and marks `Call the plumber` done
- **AND** it does not first propose the oat milk part alone

#### Scenario: Held proposal and one occurrence of a weekly thought

- **WHEN** the conversation has seen `Take the bins out`, an open thought repeating every week on Monday, a later proposal about oat milk is held, and the user sends `I took the bins out`
- **THEN** no card marks `Take the bins out` done
- **AND** the oat milk part is still held, or is in the turn's new proposal
