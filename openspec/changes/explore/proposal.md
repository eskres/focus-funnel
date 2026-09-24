> **Planning status:** Proposal only. Write the specs, design, and tasks when this change is picked up. Depends on `conversation-agent`, `thought-storage`, and `push-and-pull`.

## Why

Most of what this change first planned is now in `conversation-agent`. There, `/explore` is the default mode of a stored conversation: the user talks a thought through with one model, the model can call `search_thoughts`, and a discussion ends in a proposal card that the user edits and confirms. Conversations persist, so a half-developed idea can be picked up later from the sidebar, and account deletion in `thought-storage` covers them.

Two parts are left. The user should see which past thoughts informed an answer while exploring, and a thought saved from a conversation should say where it came from.

## What Changes

- Each time `search_thoughts` runs during a discussion, show the related thoughts it returned next to the answer, using the sources list from `push-and-pull`, so the user sees what informed the answer.
- Link a thought saved from a conversation back to that conversation and the message position of its proposal. The thought detail view opens the conversation at that point.
- If the conversation is deleted, the thought keeps its content and loses only the link.

## Capabilities

### New Capabilities
- `thought-origin`: The link from a saved thought to the conversation it came from.

### Modified Capabilities
- `chat-interface`: Shows related thoughts when the search tool runs during a discussion.
- `thought-store`: Adds an optional link from a thought to its conversation.
- `thought-detail-view`: Shows and opens the source conversation.

## Impact

- **Backend:** a nullable `conversation_id` and message position on `thoughts`, set on delete to null, filled when a proposal is confirmed.
- **Frontend:** the related-thoughts display during a discussion, and the source-conversation link on the thought detail page.
- **Naming:** the folder name is historical. `/explore` is a mode of the one chat model.
