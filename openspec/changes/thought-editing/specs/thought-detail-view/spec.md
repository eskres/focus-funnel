## MODIFIED Requirements

### Requirement: A thought opens in a side sheet

Opening a thought SHALL show a side sheet over the chat with its title, summary, tags, category, raw text, and the dates it was filed and last changed. The chat SHALL stay in place behind it. A thought with no raw text SHALL show no raw text section. A raw text that is the same as the summary SHALL NOT be shown twice. The raw text SHALL be read-only: the sheet SHALL offer no way to change it.

#### Scenario: Open from a saved card

- **WHEN** a user clicks the link on a saved proposal card
- **THEN** a side sheet shows the thought's title, summary, tags, category, raw text, and dates
- **AND** the conversation is still visible behind it

#### Scenario: Close

- **WHEN** the user closes the sheet
- **THEN** the chat is as it was, with the same scroll position and any unsent text in the input

#### Scenario: No changes from the sheet

- **WHEN** a user views a thought in the sheet and does not choose Edit or Delete
- **THEN** the thought is unchanged when the sheet closes

#### Scenario: Raw text stays as written

- **WHEN** a user opens a thought that has raw text and chooses Edit
- **THEN** the title, summary, tags, and category become editable
- **AND** the raw text shows as before, with no field to change it

### Requirement: Only the owner sees a thought

The system SHALL return, change, or delete a thought only for its owner. A thought of another user and a thought that does not exist SHALL get the same answer, HTTP 404 with error code `not_found`, for reading, changing, and deleting, and the sheet SHALL say the thought no longer exists.

#### Scenario: Another user's thought

- **WHEN** a user opens an address that names another user's thought
- **THEN** the sheet says the thought no longer exists
- **AND** nothing of the thought is shown

#### Scenario: Change or delete another user's thought

- **WHEN** a user sends a change or a delete for a thought another user owns
- **THEN** the answer is HTTP 404 with error code `not_found`, the same as for a thought that does not exist
- **AND** the other user's thought is unchanged

## ADDED Requirements

### Requirement: A thought can be edited in the sheet

The sheet SHALL offer an Edit button. Edit SHALL turn the title, summary, tags, and category into fields in place, filled with the current values, with Save and Cancel. The category SHALL be chosen from the user's categories, or none; a category the user has since removed SHALL stay a choice while the thought has it. The fields SHALL be checked as a proposal card's fields are. A refused save SHALL show an error that names the field and SHALL keep the user's text in the fields. A saved change SHALL show in the sheet at once, with the new "changed" date, and search SHALL find the thought by its new content and not its old. Cancel SHALL leave the thought as it was. The thought's origin SHALL NOT change when the thought is edited.

#### Scenario: Edit and save

- **WHEN** a user opens a thought, chooses Edit, changes the title to `Dentist in May`, and saves
- **THEN** the sheet shows `Dentist in May` as the title and a later "changed" date
- **AND** a search for `dentist` finds the thought

#### Scenario: Empty title

- **WHEN** a user clears the title and saves
- **THEN** the sheet shows an error that names the title
- **AND** the fields keep the user's text, and the thought is unchanged

#### Scenario: Cancel

- **WHEN** a user changes the summary and chooses Cancel
- **THEN** the sheet shows the thought as it was before Edit, and the thought is unchanged

#### Scenario: Removed category kept

- **WHEN** a thought has the category `trip`, the user removed `trip` from their categories, and the user edits only the title and saves
- **THEN** the thought keeps the category `trip`

#### Scenario: Category not the user's

- **WHEN** a change names a category that is not one of the user's categories and not the thought's current category
- **THEN** the change is refused with an error that names the category, and the thought is unchanged

#### Scenario: Origin kept

- **WHEN** a user edits a thought that was saved from a conversation
- **THEN** the sheet still shows the same origin

#### Scenario: Embedding provider down

- **WHEN** a user saves a new summary while the embedding provider cannot be reached
- **THEN** the change is saved and a search for a word in the new summary finds the thought

### Requirement: A thought can be deleted from the sheet

The sheet SHALL offer a Delete button. Delete SHALL ask for confirmation in a dialog that names the thought and says that the delete cannot be undone. Confirming SHALL delete the thought and close the sheet, and search SHALL no longer find it. Cancelling SHALL leave the thought as it was. A delete that fails SHALL show the reason in the dialog, and the thought SHALL stay.

#### Scenario: Delete

- **WHEN** a user opens a thought, chooses Delete, and confirms
- **THEN** the sheet closes and the user stays in the conversation
- **AND** a search for the thought's title does not return it

#### Scenario: Cancel the delete

- **WHEN** a user chooses Delete and then Cancel
- **THEN** the sheet still shows the thought, and the thought is not deleted

#### Scenario: Old address after delete

- **WHEN** a user deletes a thought and then opens an address that names it, or its link in a sources list
- **THEN** the sheet says the thought no longer exists
