> **Planning status:** Proposal only. Write the specs, design, and tasks when this change is picked up. Depends on `conversation-agent` and `thought-storage`.

## Why

Filing thoughts away (`/push`) and finding them again (`/pull`) are the core value of Focus Funnel. `conversation-agent` gives the chat model two tools for this, `propose_thought` and `search_thoughts`, and a proposal card the user edits and confirms. `thought-storage` makes the search tool real. Confirming a proposal still answers that saving is not available yet, and a search result is not yet shown to the user as sources. This change turns a confirmed proposal into a stored thought, and turns a question into an answer built from stored thoughts with links to them.

## What Changes

- **Filing (`/push` and proposals from a discussion):**
  - Replace the `save_thought` seam behind the confirm endpoint with a real save through `thought-storage`. The card shows that the thought was saved and links to it.
  - The raw text is always kept alongside the summary. The design decides what the raw text is for a proposal that ends a discussion rather than a single `/push` message.
  - Add a category to the `propose_thought` tool and the card.
  - Give the model the user's existing tags in the turn context, so it reuses them where they fit.
  - Nothing saves without the user's confirmation, as in `conversation-agent`.
- **Split suggestion:** If the text holds several separate thoughts, the model proposes each one, and the chat shows one card per part. The user can confirm each, edit the parts, or merge them into one thought.
- **Recall (`/pull` and search from a discussion):**
  - When `search_thoughts` returns thoughts, the chat shows them as sources under the answer and links to each one.
  - Sources start in relevance order, and a toggle re-sorts the same results newest first.
  - The user can filter by one or more tags, which the search tool passes to the search.
- **When nothing matches:** the tool result says so, and the model says so plainly and does not invent an answer.
- **Thought detail view:** Shows the raw text, summary, title, tags, category, and dates. Source links and the saved-proposal link open this view.

## Capabilities

### New Capabilities
- `thought-filing`: Saving a confirmed proposal, tag reuse, category, and the split suggestion.
- `thought-recall`: Sources under an answer, tag filters, newest-first sort, and the empty-result behavior.
- `thought-detail-view`: Viewing a single stored thought.

### Modified Capabilities
- `conversation-agent`: Confirming a proposal saves it; the proposal tool gains a category; the search tool takes tag filters and returns source ids.
- `chat-interface`: The proposal card shows the saved outcome and a link; answers show their sources.

## Impact

- **Backend:** the real `save_thought` function, the category field in the proposal tool and `held_proposal`, existing tags in the turn context, source ids in the `tool` event, and a thought detail endpoint.
- **Frontend:** saved state on the proposal card, one card per part for a split, a sources list with tag filter and newest-first toggle, and the thought detail page.
- **Naming:** the folder name is historical. Both behaviors run through the one chat model and its tools.
