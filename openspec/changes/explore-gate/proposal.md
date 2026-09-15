> **Planning status:** Proposal only. Write the specs, design, and tasks when this change is picked up. Depends on `push-and-pull-gates`.

## Why

A raw brain dump is often not ready to file. /explore lets the user talk a thought through with a model, pull in related past thoughts, and save a refined version when it is ready. Sessions persist, so a half-developed idea can be picked up later.

## What Changes

- Store /explore conversations as sessions in Postgres, with every message.
- Let users list, reopen, rename, and delete sessions.
- Stream /explore answers from the explore gate model, which sees the session's message history.
- Give the explore model a search tool over past thoughts, using the same search as /pull. The model decides when to call it. Each time the tool runs, show the related thoughts it returned so the user sees what informed the answer.
- When the user presses "Save", the model drafts a refined thought from the session. The draft goes into the /push preview flow, including the split suggestion, before anything is stored.
- Link a thought saved from a session back to that session, so the user can see where the thought came from.

## Capabilities

### New Capabilities
- `explore-gate`: Discussion, use of related thoughts, and the save-to-/push flow.
- `explore-sessions`: Storing, listing, reopening, renaming, and deleting sessions.

### Modified Capabilities
- `message-routing`: Replaces the explore placeholder handler with the real one.
- `thought-store`: Adds an optional link from a thought to the explore session it came from.
- `account-data-deletion`: Also deletes the user's explore sessions.

## Impact

- **Backend:** `explore_sessions` and `explore_messages` tables, the explore gate handler with a tool-calling loop, a thought search tool, a save-draft endpoint that feeds the /push preview.
- **Frontend:** session list, session view, related-thoughts panel shown when the tool runs, Save action.
- **Model constraint:** The explore gate's model must support tool calling on Nebius. This depends on the required-features check in `gate-framework`. Confirm which Nebius models support tool calling when choosing the default model.
