## Why

A filed thought can be read in the detail sheet but never fixed or removed. A typo in a title, a wrong category, or a thought filed by mistake stays forever. The store already updates and deletes thoughts with search kept in step; only the API and the sheet are missing.

## What Changes

- The thought detail sheet gets an Edit button. Title, summary, tags, and category become fields in place, with Save and Cancel. A refused save names the field and keeps the user's text. After a save, the sheet shows the new "changed" date.
- The sheet gets a Delete button with a confirmation dialog. After a delete, the sheet closes and search no longer finds the thought.
- The raw text stays read-only. It is the record of what the user wrote.
- New endpoints `PATCH /api/thoughts/{id}` and `DELETE /api/thoughts/{id}`, owner-scoped: another user's thought gets the same 404 `not_found` as a missing one. Errors use `{"error":{"code","message"}}`. The Next.js catch-all proxy already forwards both methods; a proxy test covers them.
- The category check that confirm uses moves to one shared helper, used by confirm and by the edit. The edit also keeps a category the user has since removed, if the thought already has it.
- A saved proposal card shows the thought's current title. When the thought is deleted, the card says "Deleted" and has no Open link. The conversation's messages answer carries each saved part's current title, or that it is deleted. The card in an open chat changes at once after an edit or delete in the sheet.
- A sources list under an answer does not change after an edit or delete. It is the record of what the answer read.
- The thought's origin (from the `explore` change) is not changed by an edit.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `thought-detail-view`: the sheet is no longer read-only. It edits title, summary, tags, and category, and deletes the thought after confirmation. The raw text stays read-only. The "No changes from the sheet" scenario is replaced.
- `chat-interface`: a saved proposal card shows the thought's current title, and says "Deleted" with no link once the thought is deleted.
- `thought-store`: the update rule now matches the store: a tags-only update embeds only the first entry again, and a category-only update needs no embedding. The old wording said neither needs a new embedding.

## Impact

- Backend: `backend/app/routers/thoughts.py` (PATCH, DELETE), `backend/app/thoughts/categories.py` (shared category check), `backend/app/routers/conversations.py` (confirm uses the shared check; the messages answer adds each saved part's current title or deleted state). `update_thought()` and `delete_thought()` in `backend/app/thoughts/store.py` are used as they are.
- Frontend: `components/chat/thought-sheet.tsx` (edit mode, delete dialog), `components/chat/proposal-card.tsx` (current title, "Deleted"), `lib/thoughts.ts` (`updateThought`, `deleteThought`, a thought-changed event), `lib/sse.ts` (part fields).
- No migration. No new dependency.
- Cost: an edit of title, summary, or tags makes one embedding call on the user's key. A category-only edit makes none.
- Depends on the `explore` change (thought origin), merged into `main` in #22 (`2d091e1`) and archived.
