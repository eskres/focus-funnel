> **Planning status:** Planned 2026-09-24: specs, design, and tasks written. Depends on `conversation-agent` and `thought-storage`, both archived.

## Why

Filing thoughts away (`/push`) and finding them again (`/pull`) are the core value of Focus Funnel. `conversation-agent` gives the chat model two tools for this, `propose_thought` and `search_thoughts`, and a proposal card the user edits and confirms. `thought-storage` makes the search tool real. Confirming a proposal still answers that saving is not available yet, and a search result is not yet shown to the user as sources. This change turns a confirmed proposal into a stored thought, and turns a question into an answer built from stored thoughts with links to them.

## What Changes

- **Filing (`/push` and proposals from a discussion):**
  - Replace the `save_thought` seam behind the confirm endpoint with a real save through `thought-storage`. The card shows that the thought was saved and links to it.
  - The raw text is always kept alongside the summary. For `/push` it is the message. For a proposal that ends a discussion it is the user's own messages in that discussion; the summary carries the model's points the user agreed with.
  - Add a category to the `propose_thought` tool and the card. A category is one of five fixed kinds (task, idea, decision, note, reference) or one the user adds in settings.
  - Give the model the user's existing tags in the turn context, so it reuses them where they fit.
  - Nothing saves without the user's confirmation, as in `conversation-agent`.
- **Split suggestion:** If the text holds several separate thoughts, the model proposes each one, and the chat shows one card per part. The user can confirm each, edit the parts, or merge them into one thought with a button, with no model call. Each part keeps the whole message as its raw text.
- **Proposals are kept:** proposal cards and sources come back when a conversation is opened again, with their saved state.
- **Recall (`/pull` and search from a discussion):**
  - When `search_thoughts` returns thoughts, the chat shows them as sources under the answer and links to each one.
  - Sources start in relevance order, and a toggle re-sorts the same results newest first.
  - The user can filter the shown sources by one or more of their tags, in the browser. The model's own tag filter still goes to the search.
- **When nothing matches:** the tool result says so, and the model says so plainly and does not invent an answer.
- **Thought detail view:** A read-only side sheet over the chat, linkable with `?thought=<id>`. Shows the raw text, summary, title, tags, category, and dates. Source links and the saved-proposal link open it. Editing and deleting a thought come later.

## Capabilities

### New Capabilities
- `thought-filing`: Saving a confirmed proposal, its raw text, tag reuse, categories (with the user's own in settings), and the split suggestion.
- `thought-recall`: Sources under an answer, tag filters, newest-first sort, and the empty-result behavior.
- `thought-detail-view`: Viewing a single stored thought.

### Modified Capabilities
- `conversation-agent`: Confirming a proposal saves it; the proposal tool gains a category; the search tool takes tag filters and returns source ids.
- `chat-interface`: The proposal card shows the saved outcome and a link; answers show their sources.
- `account-data-deletion`: Deleting content keeps the user's categories; deleting the account removes them.

## Impact

- **Backend:** a `proposals` table that replaces `conversations.held_proposal`, the real `save_thought` function, the category field in the proposal tool, a `user_categories` table and its endpoints, existing tags in the turn context, sources in the `tool` event and on the stored tool message, and a thought detail endpoint.
- **Frontend:** saved state on the proposal card, one card per part for a split with a merge button, a sources list with tag filter and newest-first toggle, the thought detail side sheet, and a categories section in settings.
- **Naming:** the folder name is historical. Both behaviors run through the one chat model and its tools.
