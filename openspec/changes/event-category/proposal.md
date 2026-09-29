## Why

Many brain dumps name something that happens at a set time: a dinner on Friday, a dentist appointment, a flight. Today the model files these as a `task` or a `note`, and a user who wants them apart must add their own category first. `event` is common enough to be a fixed kind for everyone.

## What Changes

- `event` becomes a sixth fixed category, after `task`, `idea`, `decision`, `note`, and `reference`. It cannot be removed, and a user cannot add it again.
- The proposal tool tells the model what an `event` is: something planned for a set date or time, such as an appointment, a meeting, a trip, or a dinner. It also tells the model where it ends: arranging something is a `task`, and something that already happened is a `note`.
- A user who already added `event` keeps one `event`, now the fixed one. Their added `event` is removed, which frees one of their 20 added slots. Thoughts already stored with `event` keep it.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `thought-filing`: "Every thought has a category" and "The user can add categories" name six fixed kinds instead of five, and a scenario covers a user who had added `event`.

## Impact

- **Backend:** the fixed list in `app/thoughts/categories.py`, the category description in `app/chat/prompt.py`, and one Alembic migration that deletes `user_categories` rows named `event`.
- **Frontend:** the fixed list in `lib/thoughts.ts` and the "five fixed kinds" text in the categories settings.
- **API:** `GET /api/settings/categories` lists `event` under `fixed`. No new fields.
- **Data:** no change to `thoughts`. Only `user_categories` rows named `event` go.
