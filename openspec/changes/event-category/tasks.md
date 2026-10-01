## 1. Data

- [ ] 1.1 Add one Alembic revision with `down_revision = "8a4d6f2b9c13"` (the single head on main, checked 2026-09-29) that deletes `user_categories` rows named `event`, with a downgrade that does nothing (design decision 2). Before writing it, run `uv run alembic heads` in `backend/`; if another revision landed on `8a4d6f2b9c13` first (for example from `thought-appending`), use that one as `down_revision`. Move the single-head test from `tests/test_thought_origin_migration.py` to a new `tests/test_event_category_migration.py`. Check with pytest that there is a single head and it is this revision, that `upgrade head`, `downgrade -1`, `upgrade head`, and `alembic check` run cleanly on SQLite and on Postgres, and that the upgrade deletes one user's added `event` while it keeps their `recipe`, another user's rows, and a stored thought's category `event`

## 2. Backend

- [ ] 2.1 Append `event` to `FIXED_CATEGORIES` in `app/thoughts/categories.py`, and change "five fixed kinds" to "six" in its module docstring and in the `UserCategory` docstring in `app/models/category.py`. Add `event` to the lists in `tests/test_categories.py` and `tests/test_chat_turn.py`. Check with pytest that `GET /api/settings/categories` lists `event` last under `fixed`, that adding `Event` answers 409 `category_exists`, that removing `event` answers 422, that confirming a card with the category `event` stores it, and that the tool's category enum ends with `event` before the added ones
- [ ] 2.2 Add the `event` sentence from design decision 3 to `CATEGORY_DESCRIPTION` in `app/chat/prompt.py`. Check with pytest that the tool's category description holds the sentence, then in the running app with a real key send the four `/push` messages from the spec's "Every thought has a category" scenarios and check that each card shows the category the spec names

## 3. Frontend

- [ ] 3.1 Append `event` to `FIXED_CATEGORIES` in `lib/thoughts.ts` and change "five fixed kinds" to "six" in its comment and in both places in `components/categories-settings.tsx`. Add `event` to the lists in `components/categories-settings.test.tsx` and `components/chat/proposal-card.test.tsx`. Check with vitest that the settings list shows `event` with no remove button, that the text says "six fixed kinds", and that the card's dropdown offers `event` after `reference` and before `recipe`

## 4. End to end

- [ ] 4.1 In the running app, start from the database before this change with one user who added `event` and `recipe` and has a thought filed as `event`. Restart the backend so it runs the migration. Check that the settings page lists `event` once as a fixed kind and `recipe` as added, that the user can add 19 more categories and not a 20th, that the thought still shows `event`, and save a screenshot of the categories settings under `.context/`
