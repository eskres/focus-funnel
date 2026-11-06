## Purpose

Gives a user who asks for it a weekly review conversation, waiting at a weekday and hour of their choosing, that lists what they filed that week, so they can look back and carry on from it without the app spending anything on their key.

## ADDED Requirements

### Requirement: The weekly review is a setting, off by default

Settings SHALL offer a weekly review with a switch, off by default, a weekday, and an hour, Sunday at 18:00 by default. The time SHALL be in the time zone of the browser that last saved the setting, UTC until it is first saved, and the section SHALL name that zone. Only the owner SHALL read or change their setting.

#### Scenario: Default

- **WHEN** a user who never changed the setting opens Settings
- **THEN** the weekly review is off, bringing back old ideas is off, and the time is Sunday at 18:00 UTC

#### Scenario: Turned on

- **WHEN** a user in `Europe/Oslo` turns the weekly review on for Friday at 17:00 and reloads Settings
- **THEN** it shows on, Friday, 17:00, in `Europe/Oslo`

#### Scenario: Saved from another zone

- **WHEN** the same user saves the setting again from a browser in `America/New_York`
- **THEN** the review comes at Friday 17:00 in `America/New_York`

### Requirement: Setting values are checked

A weekday other than Monday to Sunday, an hour that is not a whole number from 0 to 23, a time zone the server does not know, or a switch that is not true or false SHALL be refused with 422 `validation_error` naming the field, and the setting SHALL be unchanged.

#### Scenario: Hour out of range

- **WHEN** a user saves the hour 24
- **THEN** it is refused naming `hour`, and the setting is as before

#### Scenario: Unknown zone

- **WHEN** a user saves the time zone `Mars/Base`
- **THEN** it is refused naming `time_zone`, and the setting is as before

### Requirement: A review conversation is made at the chosen time

When the weekly review is on, the system SHALL make one conversation for the user at the chosen weekday and hour, each week, within about five minutes. A review missed while the server was down SHALL be made once when it is back, not once per missed week. Turning the review off SHALL stop the next one.

#### Scenario: On time

- **WHEN** a user's review is on for Sunday at 18:00 in `Europe/Oslo`, and they filed thoughts that week
- **THEN** a conversation titled with the week's days appears in their sidebar by about 18:05 Oslo time that Sunday

#### Scenario: Down over the review time

- **WHEN** the server was down from Sunday 17:00 to Tuesday 09:00 over a user's Sunday 18:00 review
- **THEN** one review conversation is made soon after 09:00 on Tuesday, listing the thoughts filed up to Sunday 18:00, and the next one comes the following Sunday

#### Scenario: Turned off

- **WHEN** a user turns the review off on Saturday
- **THEN** no review conversation is made for them on Sunday

### Requirement: A changed setting brings no second review

Changing the setting SHALL NOT bring a review sooner than 6 days after the last weekly time, also when the change is saved while that weekly time's review is being made. The new weekday and hour SHALL apply from then on, and the next review SHALL list what was filed since the last weekly time. While the review or resurfacing is on, Settings SHALL show when the next weekly time is, in the setting's time zone.

#### Scenario: Changed after this week's review

- **WHEN** a user's Sunday 18:00 review has been made, and at 19:00 that Sunday they change the hour to 20:00 and save
- **THEN** no second review is made that day, and the next review comes the following Sunday at 20:00
- **AND** it lists the thoughts filed since 18:00 that Sunday, and none listed in the first

#### Scenario: Moved to an earlier weekday

- **WHEN** a user in `Europe/Oslo` whose Sunday 18:00 review was made on Sunday 8 November 2026 moves it to Wednesday at 18:00 on Monday 9 November and saves
- **THEN** Settings shows the next review on Wednesday 18 November at 18:00, and no review is made on Wednesday 11 November

#### Scenario: Changed while the review is being made

- **WHEN** a user's Sunday 18:00 review is being made, and at that moment they change the hour to 20:00 and save
- **THEN** no second review is made that day, and the next review comes the following Sunday at 20:00

### Requirement: Saving the setting does not skip a due review

Saving the setting while a weekly time is due and its review not yet made SHALL NOT skip that review: it SHALL still be made within about five minutes of its time, with the switches just saved, and a new weekday and hour SHALL apply from the next one.

#### Scenario: Saved before the review is made

- **WHEN** a user's Sunday 18:00 review is due, and at 18:02, before it is made, they save the setting with the same weekday and hour
- **THEN** that review is still made by about 18:05, and the next one comes the following Sunday at 18:00

#### Scenario: Moved before the review is made

- **WHEN** a user's Sunday 18:00 review is due, and at 18:02, before it is made, they change the hour to 20:00 and save
- **THEN** that review is still made by about 18:05, no second one is made that day, and the next one comes the following Sunday at 20:00

### Requirement: One user's failed review does not stop others

A review that fails for one user SHALL NOT stop or delay the reviews of other users, and that user's next review SHALL come at their next weekly time and SHALL list the thoughts the failed one would have listed. The log SHALL name the user and the kind of error, and SHALL hold nothing of their thoughts.

#### Scenario: One user's review fails

- **WHEN** three users' reviews are due at the same time, and making the second user's fails
- **THEN** the first and third users get their reviews, and the second user's next review comes at their next weekly time
- **AND** the log names the second user and the kind of error, and holds none of their titles

#### Scenario: The next review after a failed one

- **WHEN** the second user's review failed one week, and their next review is made
- **THEN** it lists the thoughts filed in the failed week as well as those filed since

### Requirement: Making a review spends nothing

Making a review conversation SHALL make no model call and no embedding call, and SHALL record no usage. The model SHALL run in it only when the user sends a message there, as in any conversation, under the user's spend cap. The review conversation SHALL be made with no model: the user's first message there SHALL take the default model the user has when they send it, or be refused asking them to pick one, as in any conversation with no model. The system SHALL NOT choose a model.

#### Scenario: No call

- **WHEN** a review conversation is made
- **THEN** no request reaches a model provider, and the user's usage is unchanged

#### Scenario: Reply at the cap

- **WHEN** a user whose month has reached the spend cap replies in a review conversation
- **THEN** the reply is refused at the cap, as in any conversation

#### Scenario: Default model

- **WHEN** a user's default model is `Model A` when a review is made, the user then changes the default to `Model B`, and replies in the review
- **THEN** the reply is answered by `Model B`, and the conversation keeps `Model B`

### Requirement: The review lists the week's thoughts

The review SHALL hold one message, written by the system, that lists the thoughts the user filed since the previous weekly time the system handled, over at most the 21 days before the review time, or in the 7 days before the review time when there was no previous weekly time. It SHALL be ordered with open tasks first, then the rest by category, newest filed first in each group, each group with its name and count. Each line SHALL show the title, and the date and status when the thought has them.

#### Scenario: Open tasks first

- **WHEN** a user filed the open task `Call the plumber`, the done task `Buy oat milk`, and the idea `Podcast about maps` that week
- **THEN** the review lists `Call the plumber` under open tasks first, then `Buy oat milk` under task marked done, then `Podcast about maps` under idea

#### Scenario: Only that week

- **WHEN** a user's previous review was 7 days before this one, and they filed a thought 8 days before this review's time
- **THEN** the review does not list it

#### Scenario: Across the end of daylight saving

- **WHEN** a user's Sunday 18:00 review in `Europe/Oslo` failed on 25 October 2026, the last weekly time handled was 18 October, and the next review is made on 1 November
- **THEN** it lists the thoughts filed since 18:00 on 18 October

### Requirement: A review's days are named in the user's time zone

A review's title and message SHALL name its days in the time zone of the setting, from the day it starts to the day of the review time, with the year of a day that is not in the year of the review time.

#### Scenario: Across the turn of the year

- **WHEN** a user's review in `Europe/Oslo` is made on Sunday 3 January 2027, and the previous weekly time was Sunday 27 December 2026
- **THEN** the review is titled `Weekly review, 27 Dec 2026 – 3 Jan`, and its message is headed with the same days

### Requirement: Consecutive reviews neither overlap nor leave a gap

A review's days SHALL include the instant they start at and SHALL leave out the review time itself, so a thought filed at exactly a weekly time is listed and counted in exactly one review. The count, the count of open tasks, each group's count, and the listed lines SHALL use the same days, and a group's count SHALL count all its thoughts in those days, also those not listed.

#### Scenario: Filed at the review time

- **WHEN** a user filed a thought at exactly their Sunday 18:00 weekly time
- **THEN** the review made for that Sunday does not list it, and the next week's review does

### Requirement: A review holds only the user's own thoughts

The review SHALL list and count only the user's own thoughts, and its conversation and notification SHALL belong to that user, also when several users' reviews are made at the same time.

#### Scenario: Two users due together

- **WHEN** two users with the review and resurfacing on are due at the same time, and each filed thoughts that week and has an untouched idea
- **THEN** each user's review lists and counts only their own thoughts, in its first line and in each group's count
- **AND** each user's resurfaced notifications name only their own ideas

### Requirement: A big week is cut as a filed-days list is

The review SHALL list at most the configured number of results for a filed-days list, the same number the search tool lists, and SHALL say how many more were filed and that the user can ask for one category. A filed-days list in the chat SHALL show the same number for a week of thoughts with titles of ordinary length; it MAY stop earlier only when its size budget is reached, and SHALL then say how many more were filed.

#### Scenario: A big week

- **WHEN** a user filed 70 thoughts that week, and the configured number of results for a filed-days list is 30
- **THEN** the review lists 30 and says 40 more were filed, and that the user can ask for one category
- **AND** each group shown is headed with the count of its thoughts filed that week, so a group can count more thoughts than are shown under it

### Requirement: An empty week makes no review

When the user filed nothing in the review's days, the system SHALL make no review conversation and no review notification for that week, whether or not ideas were resurfaced at the same time. The review SHALL NOT name resurfaced ideas.

#### Scenario: Nothing filed

- **WHEN** a user with the review on filed nothing all week
- **THEN** no review conversation and no review notification appear

#### Scenario: Nothing filed, ideas resurfaced

- **WHEN** a user with the review and resurfacing on filed nothing all week, and has two untouched ideas
- **THEN** no review conversation and no review notification appear
- **AND** each idea appears as its own resurfaced notification

### Requirement: The user is told a review is waiting

A new review SHALL come with an in-app notification, "Weekly review", saying how many thoughts were filed and how many open tasks are among them. Clicking it SHALL open the review conversation. It SHALL NOT be sent as a browser notification. Each week's review SHALL be made and notified once.

#### Scenario: Notified

- **WHEN** a review with 12 thoughts, 3 of them open tasks, is made
- **THEN** the Notifications link shows one more unread, and the page lists "Weekly review" saying 12 thoughts were filed and 3 are open tasks

#### Scenario: Open it

- **WHEN** the user clicks that notification
- **THEN** the review conversation opens

#### Scenario: Not twice

- **WHEN** the server stops while a review is being made and starts again
- **THEN** the user has one review conversation and one notification for that week

### Requirement: A review conversation is an ordinary conversation

A review conversation SHALL be listed in the sidebar like any other, newest activity first, with the title `Weekly review, <days>`, and SHALL be renamed, archived, restored, and deleted like any other. A review made while the user has the app open SHALL be listed in the sidebar, and marked as the open conversation, once the user opens it, with no message sent and no reload. Another user SHALL get the same answer as for a conversation that does not exist.

#### Scenario: Listed

- **WHEN** a review for 1 to 8 November is made
- **THEN** the sidebar lists `Weekly review, 1–8 Nov` at the top

#### Scenario: Listed while the app is open

- **WHEN** a user has the app open when their review is made, and opens it from its notification
- **THEN** the sidebar lists `Weekly review, 1–8 Nov` at the top and marks it as the open conversation

#### Scenario: Archived

- **WHEN** a user archives a review conversation they never wrote in
- **THEN** it moves to "Archived", and no model is asked

#### Scenario: Another user's review

- **WHEN** a user opens the address of another user's review conversation
- **THEN** the answer is the same as for a conversation that does not exist

### Requirement: Demo mode has no weekly review

In demo mode, Settings SHALL NOT show the weekly review, its routes SHALL answer 404 `not_found`, and no review conversation SHALL be made.

#### Scenario: Demo visitor

- **WHEN** a demo visitor opens Settings
- **THEN** there is no weekly review section, and a request for the setting answers 404
