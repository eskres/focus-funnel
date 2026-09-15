> **Planning status:** Proposal only. Write the specs, design, and tasks when this change is picked up. Depends on `gate-framework` and `thought-storage`.

## Why

Filing thoughts away (/push) and finding them again (/pull) are the core value of Focus Funnel. Everything before this change is groundwork. This change turns a brain dump into stored, searchable thoughts, and turns questions into answers built from those thoughts.

## What Changes

- **/push:**
  - The push gate model writes a title, summary, tags, and category for the user's text.
  - The model sees the user's existing tags and reuses them where they fit.
  - The user sees a preview and can edit any field before saving. Nothing saves without the user's confirmation.
  - The raw text is always kept alongside the summary.
- **/push split suggestion:**
  - If the model decides the text holds several separate thoughts, it suggests a split and asks the user.
  - The user can accept the split (each part gets its own preview), change the suggested parts, or save everything as one thought.
- **/pull:**
  - Search the user's thoughts by meaning.
  - Stream an answer from the pull gate model that is built from the matching thoughts.
  - Link to each source thought the answer uses.
- **/pull filters and sorting:** Filter by one or more tags. Source thoughts start in relevance order, and a toggle re-sorts the same results newest first.
- **When nothing matches:** /pull says so plainly and does not invent an answer.
- **Thought detail view:** Shows the raw text, summary, title, tags, category, and dates. /pull answers link to this view.

## Capabilities

### New Capabilities
- `push-gate`: Writing the preview, editing and confirming it, and the split suggestion flow.
- `pull-gate`: Retrieval, the written answer with source links, tag filters, newest-first sort, and the empty-result behavior.
- `thought-detail-view`: Viewing a single stored thought.

### Modified Capabilities
- `message-routing`: Replaces the push and pull placeholder handlers with real ones.

## Impact

- **Backend:** push and pull gate handlers, prompts, a structured preview response for push, an SSE answer stream for pull, and endpoints to confirm a push.
- **Frontend:** push preview and edit UI, split suggestion UI, pull answer with source links, tag filter and newest-first toggle, thought detail page.
