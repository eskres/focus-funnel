## Why

A user files "Buy new bike lock", then keeps talking about it: colours, strength, prices. Or they file an idea and come back to it a year later in another conversation. Today each follow-up becomes a separate new thought, so what the user knows about one thing is spread over many thoughts. A follow-up should build up the thought that exists instead.

## What Changes

- `propose_thought` can mark a part as an addition to a filed thought, by a short ref (`T1`, `T2`, …) instead of an id. The model can name only thoughts this conversation has seen: filed from it, added to from it, or found by one of its searches. The server resolves the ref and treats any other ref as a new thought. Refs are fixed per conversation and never renumbered.
- Each turn, and the offer before `/compact` and archive, tells the model which thoughts the conversation has seen, with their refs and summaries, so a follow-up is proposed as an addition.
- Before a new thought is proposed, a similar-thought check searches all the user's thoughts, in every conversation and of any age:
  1. The server finds up to 3 candidates, by meaning and by words.
  2. The model decides in the same turn: add to a candidate, or keep the thought new.
  3. When the model keeps it new but a strong match exists, the card says "Similar: <title> (filed <date>). Add to it instead?"
  For a task, steps 1 and 2 run and the model is told that a repeated task is usually new; step 3 is skipped.
- The check adapts to any embedding model. Each search index learns how similar the user's unrelated thoughts are, and sets its own cut-offs from that. An operator command measures the check against a labelled test set for any embedding model and chat model.
- The card for an addition says "Add to: <title>". It shows the current summary beside the proposed new one, with the changes marked, and the tags and category. The user can edit them, then choose Add or File as new thought instead. An addition never changes the title.
- Confirming an addition updates the thought through the store, so search stays in step. The raw text gains the new user messages after a dated separator. Messages already added are not added again. The original text is kept at the start; when the limit of 20,000 characters is reached, the oldest additions are left out first.
- A confirm is refused when the thought changed after the addition was proposed, and the card shows the current version to review.
- Each addition is recorded with the thought's fields before it. The detail view lists where each addition came from and offers "Undo last addition".
- The thought's origin stays the proposal it was first filed from.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `thought-filing`: a proposal part can add to a filed thought; the similar-thought check; how an addition changes the raw text; merging is not offered when a part is an addition.
- `conversation-agent`: the proposal tool takes an addition ref and the model is told which thoughts the conversation has seen ("Tools to file and find thoughts"); the offer before archive and `/compact` proposes additions and checks new parts ("The offer before an action may propose nothing", added by `explore`).
- `chat-interface`: the addition card and the "Similar" hint on a new card.
- `thought-detail-view`: the list of additions and "Undo last addition".
- `embedding-management`: each index learns its similarity baseline; the operator command that measures the check.

## Impact

- Backend: `app/chat/tools.py` and `app/chat/prompt.py` (tool schema, seen-thoughts note, candidate result), `app/chat/turn.py` and `app/chat/proposal.py` (the check, refs, the offer), `app/routers/conversations.py` (confirm as an addition), `app/routers/thoughts.py` (additions, undo), `app/thoughts/store.py` (an update that the caller commits), `app/thoughts/search.py` (search with a vector already computed), `app/thoughts/indexing.py` (the baseline), a new `app/evals/similar_thoughts.py` and its test set.
- Data: one migration: a `thought_additions` table and two baseline columns on `search_indexes`.
- Frontend: `components/chat/proposal-card.tsx` (addition card, "Similar" hint), `components/chat/thought-sheet.tsx` (additions, undo), `lib/sse.ts`, `lib/thoughts.ts`.
- Cost on the user's key: one embedding call per proposal that has a new part (all parts in one request), one more tool round when candidates are found, and one embedding call per confirmed addition or undo.
- Depends on `explore` (merged into `main` in #22 (`2d091e1`) and archived, including its `conversation-agent` requirements) and on `thought-editing` (planned, not built).
