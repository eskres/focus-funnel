## Context

See `proposal.md` for why. What exists today (checked 2026-09-29, main at `2d091e1`):

- The fixed kinds live in code, not the database. `FIXED_CATEGORIES` in `backend/app/thoughts/categories.py` feeds the settings answer (`routers/settings_categories.py`), the tool enum through `user_categories()`, the confirm check in `routers/conversations.py`, and the default `TOOLS` in `chat/prompt.py`.
- The frontend keeps its own copy in `frontend/lib/thoughts.ts`. `components/chat/categories-context.tsx` uses it only until `GET /api/settings/categories` answers, and as the value outside the provider.
- `user_categories` holds the added ones: one row per user and name, unique on `(user_id, name)`. `add_category()` stores the name cleaned (trimmed, lowercased, inner spaces collapsed), so an added `Event` is stored as `event`.
- `thoughts.category` is free text. It does not reference `user_categories`.
- `CATEGORY_DESCRIPTION` in `chat/prompt.py` defines each fixed kind in one sentence. `note` is already "something that happened or someone said".
- Alembic has one head, `8a4d6f2b9c13` (explore, merged in #22). `tests/test_thought_origin_migration.py` asserts that this revision is the single head.
- The backend container runs `alembic upgrade head` on start (`backend/docker-entrypoint.sh`).

## Goals / Non-Goals

**Goals:**

- One list of fixed kinds per side, with `event` last, and no other code path that names the kinds.
- A migration that leaves no user with two `event` entries.

**Non-Goals:**

- A per-user choice to hide a fixed kind.
- Dates on thoughts. `event` is a category only; the model does not store when the event is.
- Changing any stored thought's category, for example moving dated `task` thoughts to `event`.

## Decisions

### 1. Append `event` after `reference`

The fixed list becomes `("task", "idea", "decision", "note", "reference", "event")`. Appending keeps the order users already see and puts the new kind where a user looks for something new. Alphabetical order was rejected: it would move every existing kind in the card's dropdown.

### 2. Delete the added rows in a data migration

One Alembic revision runs `DELETE FROM user_categories WHERE name = 'event'`. There is no schema change. An exact match is enough because `add_category()` always stores the cleaned name.

Rejected: filter `event` out of `added_categories()` at read time. The row would stay, count toward the 20, and make `DELETE /api/settings/categories/event` answer "fixed kind" for a row that still exists. A one-time delete leaves nothing to explain later.

The downgrade does nothing. The deleted rows cannot be told apart from users who never added `event`, and after a downgrade `event` is simply not offered until the user adds it again. Thoughts keep `event` either way.

### 3. The description draws the lines, not the code

`CATEGORY_DESCRIPTION` gains one sentence in the same style as the others:

> event: something planned for a set date or time, such as an appointment, a meeting, a trip, or a dinner. Something to do or arrange is a task, even on a set day; something that already happened is a note.

The "even on a set day" clause is new next to the proposal's wording. Without it, `/push call the plumber on Monday` (a `task` scenario in the spec today) matches "planned for a set date". No code checks the category the model picks; the card lets the user change it.

### 4. Keep the frontend copy of the list

`frontend/lib/thoughts.ts` keeps `FIXED_CATEGORIES`, now with `event`. It is only a first value before the settings answer arrives. Deleting it would leave the card's dropdown empty for that moment. The two lists are kept in step by the tests that list the kinds on each side.

## Risks / Trade-offs

- [The model files dated to-dos as `event`] → The description says that something to do is a `task` even on a set day, and the spec has a scenario for each line. The user can change the category on the card.
- [A browser with the old bundle during a deploy shows five kinds] → It shows the settings answer as soon as it arrives, and the old fallback is only used before that. Confirming `event` still passes, because the backend check uses the backend list.
- [A user loses an added `event` they thought of as their own] → Nothing they filed changes, and the fixed `event` has the same name. It frees a slot.

## Migration Plan

1. Deploy. The container runs `alembic upgrade head`, which deletes the added `event` rows before the app serves requests.
2. Rollback: deploy the previous image and run `alembic downgrade -1`. Nothing is restored (see decision 2). Users who want `event` back add it again.

### Revision order

- This revision's `down_revision` is `8a4d6f2b9c13`, the head on main (checked 2026-09-29 with `alembic heads`).
- `thought-appending` has no change folder or branch yet. If it adds a revision on `8a4d6f2b9c13` too, the two make a second head. Whoever merges last sets their `down_revision` to the other's revision and moves the single-head test to their own migration.
