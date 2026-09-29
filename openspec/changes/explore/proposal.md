> **Planning status:** Planned 2026-09-25: specs, design, and tasks written. Depends on `push-and-pull`, built on branch `push-and-pull-tasks` and not yet merged.

## Why

Most of what this change first planned is now in `conversation-agent`. There, `/explore` is the default mode of a stored conversation: the user talks a thought through with one model, the model can call `search_thoughts`, and a discussion ends in a proposal card that the user edits and confirms. Conversations persist, so a half-developed idea can be picked up later from the sidebar, and account deletion in `thought-storage` covers them.

Two parts were left. The first, showing which past thoughts informed an answer while exploring, is now in `push-and-pull`: its sources list shows under every answer whose searches returned thoughts, in any mode. The part left is that a thought saved from a conversation should say where it came from.

## What Changes

- Link a thought saved from a conversation to the proposal it came from, and so to that conversation and the card's place in it. This covers `/push` and discussions alike.
- The thought detail view shows the conversation's current title and whether it is archived. Clicking it opens the conversation scrolled to the proposal card, with the card marked for a moment.
- If the conversation is deleted, the thought keeps its content and loses only the link.
- Thoughts saved before this change get their link from the stored proposals.

## Capabilities

### New Capabilities
- `thought-origin`: The link from a saved thought to its conversation, how the detail view shows it, and opening the conversation at the proposal card.

### Modified Capabilities
- `conversation-agent`: two added requirements, from bugs found while testing this change: one proposal per answer, and the offer before archive or `/compact` may propose nothing. Neither changes an existing requirement.

The origin's display and the address that opens a conversation at a card are in `thought-origin`, because `thought-detail-view` is not a main spec until `push-and-pull` is archived.

## Impact

- **Backend:** a nullable `proposal_id` on `thoughts`, set to null when the proposal's conversation is deleted, filled when a proposal is confirmed, and backfilled from `proposals`. The thought detail answer gains an `origin`.
- **Frontend:** the origin section in the thought detail sheet, and a conversation address that scrolls to and marks a proposal card.
- **Naming:** the folder name is historical. `/explore` is a mode of the one chat model.
