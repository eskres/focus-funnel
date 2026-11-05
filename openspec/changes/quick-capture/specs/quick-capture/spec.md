## Purpose

Lets a user send text straight to proposal cards from a small box, or from the phone's share sheet, without opening a conversation. The cards are confirmed on the same page, and nothing is stored as a thought until the user confirms one.

## ADDED Requirements

### Requirement: The Capture page holds the capture box

The app SHALL have a Capture page, reached from a link "Capture" in the sidebar. It SHALL show one text box and a "Make cards" button, and SHALL fit a phone screen 360 pixels wide with no sideways scrolling. "Make cards" SHALL be off while the box is empty or holds only whitespace. The box SHALL be cleared once the capture has started, and SHALL keep its text when the capture is refused.

#### Scenario: Open from the sidebar

- **WHEN** a user clicks "Capture" in the sidebar
- **THEN** the Capture page shows an empty box and a "Make cards" button that is off

#### Scenario: Phone width

- **WHEN** a user opens the Capture page on a screen 360 pixels wide
- **THEN** the box, the button, and the cards fit the width, and the page does not scroll sideways

#### Scenario: Make cards

- **WHEN** a user types `buy oat milk` and presses "Make cards"
- **THEN** the capture shows under the box as making cards, and the box is cleared

### Requirement: Make cards waits for the logged-in user

"Make cards" SHALL be off until the page has read who is logged in. When that cannot be read, for a reason other than an ended session, the page SHALL show the reason and offer a reload, and "Make cards" SHALL stay off.

#### Scenario: User not read yet

- **WHEN** a user types text before the page has read who is logged in
- **THEN** "Make cards" is off until it has

#### Scenario: User cannot be read

- **WHEN** the page cannot read who is logged in, for a reason other than an ended session
- **THEN** the page shows the reason and a reload button, and "Make cards" stays off

### Requirement: A capture is sent once

"Make cards" SHALL be off while a capture is being sent, and SHALL be on again once the answer comes. When the request fails with no answer, the box SHALL keep its text, and the page SHALL load the list once, so a capture that did start is shown.

#### Scenario: Pressed twice

- **WHEN** a user presses "Make cards" twice before the answer comes
- **THEN** one capture is sent

#### Scenario: Connection lost while sending

- **WHEN** the request to make cards fails with no answer
- **THEN** the box keeps the text, and the page loads the list once, showing the capture if it started

### Requirement: A capture becomes proposal cards as /push does

A capture SHALL be handled as `/push` with the box's text: one turn in which the model must use the proposal tool, with the same tools, rules, and tool round limit as a `/push` in a new conversation. The text SHALL be taken as it is: a leading slash command in it SHALL be ordinary text. The model's reply text SHALL NOT be shown on the Capture page.

#### Scenario: One thing

- **WHEN** a user captures `buy oat milk`
- **THEN** the Capture page shows one card with a title, summary, tags, and the category `task`

#### Scenario: Several things

- **WHEN** a user captures `buy oat milk, book the dentist, and idea: a podcast about maps`
- **THEN** the capture shows three cards, with a merge button, before any is confirmed

#### Scenario: Text that starts with a command

- **WHEN** a user captures `/pull what did I say about rent?`
- **THEN** the model must use the proposal tool on that whole text, and no search is forced

### Requirement: A capture uses the user's default model

A capture SHALL use the model and reasoning effort set as the user's default in the model settings. It SHALL NOT use any other model, and SHALL NOT change the user's settings. With no default model, the capture SHALL be refused with HTTP 409 and error code `model_not_set`, before any model call, and the page SHALL link to the model settings.

#### Scenario: Default model

- **WHEN** a user whose default model is model A, with effort `low`, makes a capture
- **THEN** the one model call of each round goes to model A with effort `low`

#### Scenario: No default model

- **WHEN** a user with no default model presses "Make cards"
- **THEN** no model is called and nothing is stored
- **AND** the page says a model is needed, with a link to the model settings, and the box keeps the text

#### Scenario: Model unavailable

- **WHEN** the provider reports that the default model is not available to the key
- **THEN** the page shows error code `model_unavailable` naming the model
- **AND** no other model is called

### Requirement: Nothing is stored as a thought until a card is confirmed

A capture SHALL store no thought by itself. A thought SHALL be stored only when the user confirms one of its cards, with the card's fields as the user left them, and with the captured text as its raw text. Confirming the same card twice SHALL store one thought.

#### Scenario: Before confirming

- **WHEN** a user captures `buy oat milk` and the card shows
- **THEN** the user has no new thought

#### Scenario: Confirm

- **WHEN** a user changes the card's title to `Oat milk` and confirms it
- **THEN** one thought titled `Oat milk` is stored, with the raw text `buy oat milk`
- **AND** the card shows that it was saved, with a link that opens the thought

### Requirement: A capture's cards are reviewed on the Capture page

Each part of a capture's proposal SHALL show on the Capture page as the same card the chat shows for that part, with the same fields, actions, and confirm, including a merge, an addition to a filed thought, a "Similar" hint, a date with its choices, and a mark done. A saved card's link SHALL open the thought in the side sheet over the Capture page.

#### Scenario: Open a saved thought

- **WHEN** a user confirms a card and clicks its link
- **THEN** the side sheet shows the thought, and the Capture page stays visible behind it

#### Scenario: Merge

- **WHEN** a capture shows two cards and the user merges them and confirms
- **THEN** one thought is stored

### Requirement: A capture is read in the user's time zone

The browser SHALL send its IANA time zone with each capture. The model SHALL be told today's date and weekday in that zone, and a date on a card SHALL carry that zone, as for a chat message. A missing or unknown time zone SHALL be read as UTC, and the capture SHALL NOT be refused for it.

#### Scenario: Late evening west of UTC

- **WHEN** a user in `America/Los_Angeles` captures `dinner with Sam on Friday at 7` at 22:00 local time on Wednesday 30 September
- **THEN** the card's date is Friday 2 October, 19:00, in `America/Los_Angeles`

#### Scenario: Unknown zone

- **WHEN** a capture arrives with the time zone `Mars/Base`
- **THEN** the capture runs, and the model is told today's date in UTC

### Requirement: A capture checks for similar filed thoughts

A capture SHALL go through the same similar-thought check as `/push`, over all the user's thoughts, so a capture about a filed thought can be proposed as an addition to it, or as marking it done, and a new card can name a strong match.

#### Scenario: Adds to a filed thought

- **WHEN** a user filed `Podcast about maps` a month ago and captures `podcast idea: an episode on old sea charts`
- **THEN** the capture shows a card that adds to `Podcast about maps`, or a new card that offers to add to it

#### Scenario: Finished task

- **WHEN** a user has the open task `Call the plumber` and captures `called the plumber, he comes Monday`
- **THEN** the capture shows a card to mark `Call the plumber` done, and nothing changes until the user confirms it

### Requirement: The Capture page lists the captures that wait

Under the box, the page SHALL list the user's captures that still wait, newest first: one still making cards, one with a card not yet confirmed, and one that ended with no cards. A capture SHALL leave the list once every one of its cards is confirmed and a thought saved from it, or added to from it, still exists. The list SHALL show at most 50 captures and SHALL say when more wait.

#### Scenario: Left for later

- **WHEN** a user captures `buy oat milk`, leaves the page without confirming, and opens it again the next day
- **THEN** the capture is listed with its card, which can still be edited and confirmed

#### Scenario: Every card confirmed

- **WHEN** a user confirms both cards of a capture and opens the page again
- **THEN** that capture is no longer listed

#### Scenario: One card left

- **WHEN** a user confirms one of two cards and opens the page again
- **THEN** the capture is listed with one card saved and one waiting

#### Scenario: More than 50 wait

- **WHEN** 60 captures of a user wait
- **THEN** the page lists the 50 newest and says that more wait

### Requirement: The page says nothing waits only after a load

Until a load of the list has succeeded, the page SHALL show that the list is loading. Only after a load that succeeded, with no capture shown, SHALL the page say nothing waits.

#### Scenario: Nothing waits

- **WHEN** a user with no waiting captures opens the Capture page
- **THEN** the page says nothing waits

#### Scenario: Still loading

- **WHEN** a user opens the Capture page and the list has not loaded yet
- **THEN** the page shows that the list is loading, and does not say that nothing waits

### Requirement: A capture that is still making cards is followed

While a capture is making cards, the page SHALL show it as making cards, from the moment it is stored until its turn ends. Its cards SHALL appear on the page when they are ready, without a reload, also when the user left the page while the capture ran and came back. A capture SHALL keep running when the user leaves the page or the phone closes the browser.

#### Scenario: Cards appear

- **WHEN** a user presses "Make cards" and waits on the page
- **THEN** the capture shows as making cards, then its cards appear without a reload

#### Scenario: Left while running

- **WHEN** a user presses "Make cards", switches to another app at once, and opens the Capture page a minute later
- **THEN** the capture's cards are shown

#### Scenario: Still starting

- **WHEN** a capture is stored and its first model call is still being opened, and the user opens the Capture page in another tab
- **THEN** the capture shows as making cards, with no "Try again"

#### Scenario: A load that started before the capture

- **WHEN** a load of the list that started before "Make cards" was answered returns without the new capture
- **THEN** the new capture stays shown as making cards, with "Dismiss"

#### Scenario: After a restart

- **WHEN** the server restarts while a capture is making cards, before any card
- **THEN** the capture says the server restarted before the cards were made, and offers "Try again"

### Requirement: A shown capture the list no longer holds stops being followed

A shown capture that the list no longer holds SHALL stop showing as making cards, and the page SHALL stop loading the list for it. When it has cards, it SHALL stay shown with them; when it has none, it SHALL be removed from the page.

#### Scenario: Last card confirmed while the turn ends

- **WHEN** a capture's card shows while its turn is still running, and the user confirms that only card
- **THEN** after the next load of the list the capture no longer shows as making cards, keeps its "Saved" link, and the page makes no further load for it

#### Scenario: A capture with no cards removed elsewhere

- **WHEN** a capture is shown as making cards with no cards yet, and it is dismissed or tried again in another tab, and the next load of the list does not hold it
- **THEN** the capture is no longer shown, and the page shows no "No cards were made." and no "Open" link for it

### Requirement: A failed list load keeps the captures shown

The page SHALL NOT load the list while it is hidden. A load that fails SHALL keep the captures shown. A load refused for too many requests SHALL show no alert and SHALL wait before the next load. A load that finds the user logged out SHALL keep the box text and send the user to log in. Any other failed load SHALL show its message, and loading SHALL go on while a capture runs.

#### Scenario: A load fails

- **WHEN** a load of the list fails while a capture is making cards
- **THEN** the captures shown stay, the failure's message shows, and the list is loaded again

#### Scenario: Too many requests

- **WHEN** a load of the list is refused for too many requests
- **THEN** the captures shown stay, no alert shows, and the next load waits

#### Scenario: Hidden tab

- **WHEN** a capture is making cards and the user switches to another tab
- **THEN** the page makes no load until the tab is visible again

### Requirement: A failed load of the full list is tried again

A load of the full list that fails SHALL be tried again, whether or not a capture runs: after the wait the server asks for, or 30 seconds, when it was refused for too many requests, and after 10 seconds for any other failure.

#### Scenario: First load refused for too many requests

- **WHEN** the first load of the list on opening the page is refused for too many requests, with a wait of 12 seconds
- **THEN** the page shows no alert, does not say that nothing waits, and loads the list again after 12 seconds

#### Scenario: First load fails

- **WHEN** the first load of the list on opening the page fails with a server error
- **THEN** the page shows the failure's message, does not say that nothing waits, and loads the list again

### Requirement: A capture that ended with no cards says why

When a capture's turn ends with no proposal, the page SHALL show the captured text and the reason, with a message that names the failure and the same alert and links the chat shows for that error code. With no error, it SHALL say no cards were made, link to the capture's conversation, and offer "Dismiss" but not "Try again". An error after the cards were shown SHALL show under them, and the cards SHALL stay, with no "Try again".

#### Scenario: Provider unreachable mid-answer

- **WHEN** the provider stops answering during a capture's turn, before any card
- **THEN** the capture is listed with its text and says the provider could not be reached

#### Scenario: The model proposed nothing

- **WHEN** a capture's turn ends with a reply and no proposal
- **THEN** the capture is listed with its text, says no cards were made, and links to its conversation, where the reply is
- **AND** it offers "Dismiss", with its confirmation, and no "Try again"

#### Scenario: Cap reached after the cards

- **WHEN** a capture's turn reaches the spend cap after its cards were shown
- **THEN** the cards stay, the cap reason shows under them with a link to the usage settings, and no "Try again" is offered

### Requirement: A stopped capture is not shown as failed

A capture whose turn was stopped SHALL NOT be shown as failed. With cards, they SHALL show with no reason under them. With none, it SHALL be shown as a capture that ended with no cards and no error.

#### Scenario: Stopped capture

- **WHEN** a capture's turn is stopped, from the chat's Stop or by a dismiss that then could not finish
- **THEN** a capture with cards shows them with no reason under them
- **AND** a capture with no cards says no cards were made, with "Open" and "Dismiss" and no "Try again"

### Requirement: A capture that failed with no cards can be tried again

A capture with no cards and an error that the latest list holds, and that is not making cards, SHALL offer one "Try again". It SHALL put the text back in the box, after what the box already holds, and drop the failed capture. A capture that ended with no cards and no error, or whose turn was stopped, SHALL NOT offer "Try again", so its reply is never deleted without a confirmation.

#### Scenario: Try again

- **WHEN** a user presses "Try again" on a capture that failed with no cards
- **THEN** the box holds the captured text, and that capture is no longer listed

#### Scenario: No cards and no error

- **WHEN** a capture's turn ends with a reply and no proposal
- **THEN** it offers no "Try again"

#### Scenario: Still starting is not tried again

- **WHEN** a capture is making cards
- **THEN** it offers no "Try again"

### Requirement: A capture can be dismissed

Each capture that the latest list holds SHALL offer "Dismiss", which asks the user to confirm with a "Dismiss" button. A capture that no existing thought was saved or added to from SHALL then be deleted with its text and cards. Any other capture SHALL be closed: it leaves the list, its unconfirmed cards stay unsaved in its conversation, and its thoughts SHALL keep their origin. A failed dismiss SHALL show the reason and keep the capture.

#### Scenario: Dismiss

- **WHEN** a user dismisses a capture whose card was never confirmed
- **THEN** the dialog says "The text and its cards are deleted."
- **AND** after the user confirms, the capture is no longer listed, its conversation is deleted, and no thought was stored

#### Scenario: Dismiss after saving one card

- **WHEN** a user confirms one of two cards, then dismisses the capture
- **THEN** the dialog says "Cards you have not confirmed are not saved as thoughts. They stay in the capture's conversation, which the saved thoughts link to."
- **AND** after the user confirms, the capture is no longer listed
- **AND** the saved thought stays, with all its content and its origin, which opens the conversation with the unconfirmed card

#### Scenario: Dismiss after marking a task done

- **WHEN** a user captures `called the plumber, he comes Monday`, confirms its card that marks `Call the plumber` done, and dismisses the capture
- **THEN** the dialog says "The text and its cards are deleted."
- **AND** after the user confirms, the capture's conversation is deleted, and `Call the plumber` stays done

#### Scenario: Cancel

- **WHEN** a user presses "Dismiss" and then cancels
- **THEN** the capture is unchanged

### Requirement: The dismiss dialog says what is kept

When the capture would be deleted, the dismiss dialog SHALL say "The text and its cards are deleted." When it would be closed, the dialog SHALL say "Cards you have not confirmed are not saved as thoughts. They stay in the capture's conversation, which the saved thoughts link to."

#### Scenario: Nothing saved

- **WHEN** a user presses "Dismiss" on a capture with no confirmed card
- **THEN** the dialog says "The text and its cards are deleted."

#### Scenario: A card saved

- **WHEN** a user presses "Dismiss" on a capture with one card saved as a thought and one not confirmed
- **THEN** the dialog says "Cards you have not confirmed are not saved as thoughts. They stay in the capture's conversation, which the saved thoughts link to."

### Requirement: A capture that is making cards can be dismissed

A capture that is making cards SHALL offer "Dismiss" too, and its turn SHALL be stopped before it is dismissed, with no model call after that. A capture whose first model call is still being opened, or whose turn does not stop in time, SHALL NOT be dismissed: the dialog SHALL say "This capture is still making cards. Try again in a moment.", and the capture SHALL stay.

#### Scenario: Dismiss while making cards

- **WHEN** a user dismisses a capture that is making cards, and confirms
- **THEN** its turn stops, the capture is no longer listed, and no further model call is made for it

#### Scenario: Dismiss while still starting

- **WHEN** a user dismisses a capture whose first model call is still being opened, and confirms
- **THEN** the dialog says "This capture is still making cards. Try again in a moment.", and the capture stays

### Requirement: Only a waiting capture can be dismissed

A capture still shown on the page but no longer waiting SHALL NOT offer "Dismiss" or "Try again". A dismiss or a "Try again" SHALL change only a capture that still waits: one that left the list because its cards were saved, or that was carried on as a conversation, SHALL be left as it is, with any answer running in it not stopped, and the page SHALL say "This capture no longer waits." Text that "Try again" put in the box SHALL stay there.

#### Scenario: Dismiss after every card is saved is not offered

- **WHEN** a user confirms every card of a capture that stays shown on the page
- **THEN** the capture offers no "Dismiss", and its thoughts keep their origin

#### Scenario: A capture carried on in another tab is not deleted

- **WHEN** a user opens a capture in another tab, sends a message there, and then presses "Dismiss" or "Try again" on the Capture page before the list is loaded again
- **THEN** the conversation is not deleted, and an answer running in it is not stopped
- **AND** the page shows "This capture no longer waits."

### Requirement: A stored capture stays reachable

A capture SHALL stay on the Capture page until it is dismissed, unless a thought saved from it, or a thought added to from it, links to it, or it was carried on as a conversation. A confirmed card that only marked a task done SHALL NOT take a capture off the page. When the user deletes the last thought that links a capture no longer listed, the capture SHALL be listed on the Capture page again, so it can be dismissed.

#### Scenario: Only a task marked done

- **WHEN** a user captures `called the plumber, he comes Monday` and confirms its only card, which marks `Call the plumber` done
- **THEN** the capture is still listed, with its card marked done, and offers "Dismiss"

#### Scenario: Saved thought deleted

- **WHEN** a user confirms the only card of a capture, which leaves the list, and then deletes the thought saved from it
- **THEN** the capture is listed on the Capture page again, with its card shown as deleted, and offers "Dismiss"

#### Scenario: One of two saved thoughts deleted

- **WHEN** a user confirms both cards of a capture and deletes one of the two thoughts
- **THEN** the capture is not listed, and the other thought keeps its origin

### Requirement: A capture is checked before any model call

A capture SHALL be refused with HTTP 422 and error code `validation_error` naming `text` when its text is empty or only whitespace, or longer than 20,000 characters. Every refusal before the capture's turn starts SHALL store nothing: no capture, no message, no thought. Every error SHALL use the shape `{"error":{"code","message"}}`. The page SHALL show the message and keep the text in the box.

#### Scenario: Too long

- **WHEN** a capture's text has 20,001 characters
- **THEN** the system responds with HTTP 422, error code `validation_error`, and a message naming `text`
- **AND** nothing is stored, and the box keeps the text

#### Scenario: No key for the provider

- **WHEN** a user with no saved key for the default model's provider presses "Make cards"
- **THEN** the page shows that a key for that provider is needed, with a link to the provider settings
- **AND** no capture is listed, and the box keeps the text

### Requirement: A capture too long for the model is refused

A capture whose text does not fit the default model's context SHALL be refused with HTTP 409 and error code `context_full`, before the model is called, and SHALL store nothing. Its message SHALL name the model and say to shorten the text or set a default model with a larger context in Settings. The page SHALL show the message under the title "This text is too long", not "This conversation is full", and keep the text in the box.

#### Scenario: Too long for the model

- **WHEN** a user whose default model has a context too small for the text presses "Make cards"
- **THEN** the page shows "This text is too long for <model>. Shorten it, or set a default model with a larger context in Settings.", with the model's name, under the title "This text is too long"
- **AND** no capture is listed, nothing is stored, and the box keeps the text

### Requirement: A capture at the spend cap is refused

When the month's usage has reached the user's spend cap, a capture SHALL be refused with HTTP 409 and error code `spend_cap_reached` before any model call, and nothing SHALL be stored. The page SHALL show the reason with a link to the usage settings, and keep the text. A capture whose turn reaches the cap SHALL end as a chat turn does, keeping any cards already shown.

#### Scenario: At the cap

- **WHEN** a user whose month has reached their cap presses "Make cards"
- **THEN** the page shows "Monthly spend cap reached", names the cap, and links to the usage settings
- **AND** no model is called, no usage is recorded, and nothing is stored

#### Scenario: Cap raised

- **WHEN** the user raises the cap above the month's usage and presses "Make cards" again
- **THEN** the capture makes cards

### Requirement: Only the owner reaches a capture

A capture SHALL belong to the user who made it. The list SHALL hold only that user's captures. Confirming a card of, dismissing, or reading another user's capture SHALL respond with HTTP 404 and error code `not_found`, with the same body as for a capture that does not exist, and SHALL change nothing, also while that capture is making cards.

#### Scenario: Another user's list

- **WHEN** user A has a waiting capture and user B opens the Capture page
- **THEN** user B's list does not hold user A's capture

#### Scenario: Another user's capture

- **WHEN** user B sends a confirm or a dismiss for user A's capture
- **THEN** the system responds with HTTP 404 and error code `not_found`, with the same body as for an unknown id
- **AND** user A's capture and thoughts are unchanged

#### Scenario: Another user's running capture

- **WHEN** user B dismisses user A's capture while it is making cards
- **THEN** the system responds at once with HTTP 404 and the same body as for an unknown id
- **AND** user A's capture keeps making cards

### Requirement: Captures are deleted with the user's content

Deleting the user's content or account, and the end of a demo session, SHALL delete their captures with their conversations.

#### Scenario: Content deleted

- **WHEN** a user with waiting captures deletes their content in settings
- **THEN** no capture of that user remains, and the Capture page lists none

#### Scenario: Account deleted

- **WHEN** a user with waiting captures deletes their account
- **THEN** no capture of that user remains

### Requirement: A capture leaves the usage warning to the chat

A capture SHALL record its usage as any turn does, and its usage SHALL count toward the warning threshold and the spend cap. A capture SHALL NOT use up the month's usage warning: when a capture brings the month to the warning threshold, the notice SHALL be shown with the next chat answer.

#### Scenario: Threshold crossed by a capture

- **WHEN** a capture brings the month's usage to the user's warning threshold, and the user then sends a chat message
- **THEN** the chat shows the warning notice with that answer

### Requirement: Quick capture in demo mode

In `demo` mode the Capture page SHALL work as for a logged-in user, with the visitor's held key. The demo notice SHALL be shown before the visitor's first capture when it was not accepted yet, and the capture SHALL NOT be sent until the visitor accepts it. When a call from the Capture page finds the demo session ended, the page SHALL keep no text for a later login, SHALL NOT send the visitor to a login, and SHALL show that the demo session ended.

#### Scenario: First capture in demo mode

- **WHEN** a demo visitor who has not accepted the notice presses "Make cards"
- **THEN** the notice is shown, and the capture is sent only after the visitor accepts it

#### Scenario: Held key

- **WHEN** a demo visitor with a held key for the default model's provider makes a capture
- **THEN** the capture makes cards with that key

#### Scenario: Demo session ends on the Capture page

- **WHEN** a demo visitor's session ends, and the Capture page then makes cards or loads the list
- **THEN** the page shows that the demo session ended
- **AND** no text is kept for a later login, and the visitor is not sent to a login
