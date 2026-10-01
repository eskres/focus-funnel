## Context

See `proposal.md` for why. This change comes after two others, in this order:

1. `explore` (thought origin): merged into `main` in #22 (`2d091e1`) and archived (2026-10-01). It adds `thoughts.proposal_id` (`ON DELETE SET NULL`), `origin` on `GET /api/thoughts/{id}`, and the origin section and `?proposal=` anchor in the chat. Its migration is `8a4d6f2b9c13`.
2. `thought-editing`: planned, not built. It adds `PATCH` and `DELETE /api/thoughts/{id}`, `check_category()`, `saved_title` and `deleted` on proposal parts, the `thought-changed` window event, and edit mode in `ThoughtSheet`.

What exists on `main`, and matters here:

- `propose_thought` takes `{"thoughts": [{title, summary, tags, category}]}` (`app/chat/prompt.py`, `app/chat/tools.py`). `write_proposal()` stores the parts as JSON on a `proposals` row. A part counts as saved when it has a `thought_id`, and `prompt.py` and `proposal.py` both rely on that.
- `raw_text_for()` picks the user's messages since the latest proposal with a saved part, and `fit_raw_text()` keeps the most recent whole messages within `MAX_RAW_TEXT` (20,000, defined in `app/thoughts/store.py`).
- `offer_proposal()` on `main` returns the held proposal, or makes one forced `propose_thought` call over the conversation with no note. Three fixes merged with `explore` in #22 change this, and this change builds on them:
  - `23e5179`: one proposal per turn. A second `propose_thought` in a turn gets `ALREADY_PROPOSED` and stores nothing (`Turn._proposed`).
  - `873ffa3`: the offer makes no model call when the user said nothing since the last saved proposal.
  - `d018dcd`: the offer's call is asked, not forced (`asked_proposal()`), so the model can decline. `offer_note()` adds `OFFER_NOTE` and `FILED_NOTE`, which lists the titles of thoughts filed from this conversation and allows new facts about the same topic. Checked on Nemotron: a talk about lock colours and prices offers a new thought, "Research bike lock price ranges". That is the case this change turns into an addition.
- Search is hybrid (meaning and words, merged by reciprocal rank fusion) with no age penalty. The meaning cut-off comes from `min_similarity_for(model)`, glob rules per embedding model in `chat.yaml` with a default. A search's sources are stored on its tool message as `details.sources` (`id`, `title`, `created_at`, `tags`).
- `update_thought()` commits by itself. `add_thought()` does not, so confirm can commit the thought and the part's `thought_id` together.
- `app/reembed.py` is the pattern for an operator command: `python -m app.<name>`, argparse, not reachable over the API.

## Goals / Non-Goals

**Goals:**

- A follow-up builds up the thought that exists, whether it comes minutes or a year later, in the same conversation or another.
- The similar-thought check works with embedding models and chat models released after this change, with no code change.
- An addition can be reviewed before and undone after.

**Non-Goals:**

- Adding to a thought from outside the chat (the detail view edits; it does not append).
- Merging two filed thoughts into one.
- Changing a thought's title by an addition. The user renames in the detail view.
- Undoing anything but the newest addition.

## Decisions

### 1. Two changes, and specs that do not overlap

Editing in the detail view ships as `thought-editing`; this change adds appending on top. Where both touch one spec, this change uses ADDED requirements, not a second MODIFIED of the same requirement: `chat-interface` gets "An addition is reviewed in the chat", and `thought-detail-view` gets the additions list and undo. So `thought-editing` and this change archive in either order without one overwriting the other.

`explore` adds two `conversation-agent` requirements in `a441648`: "One proposal per answer" and "The offer before an action may propose nothing". This change:

- modifies "The offer before an action may propose nothing": the model is told the seen thoughts by ref, a continuing discussion is offered as an addition, and new parts go through the check. So this change must archive after `explore`;
- leaves "One proposal per answer" as it is. A candidate round shows no proposal, so the model's next call is not "again in an answer that already shows a proposal";
- modifies "Tools to file and find thoughts", which neither earlier change touches;
- does not modify "A proposal is held while the conversation carries on". The offer's new behaviour lives in the offer requirement.

### 2. Refs: `T1`, `T2`, … by first appearance in the conversation

A thought gets a ref the first time the conversation sees it, in this order of stored rows: each proposal's parts (by position, then part index) with a `thought_id` or `add_to`, each tool message's `details.sources` (search results), and each tool message's `details.similar` (check candidates). The server numbers distinct thought ids in that order. The rows are never rewritten, and a deleted thought keeps its id in them, so a number never moves and is never given to another thought.

The refs are computed from rows a turn already loads (`list_messages()` and `list_proposals()`), so they need no table and no extra query. A ref is resolved to a thought id when the proposal is written, and the part stores the id. After that, the ref is only text in the history.

The model sees the refs in a system note placed just before the held-proposal note, on every turn. In the offer, this note replaces `FILED_NOTE`'s list of titles; `OFFER_NOTE` stays:

> Thoughts this conversation has seen. To add to one instead of filing a new thought, set add_to to its ref. …

It lists up to `filing.seen_thoughts` (config, default 3) thoughts, most recently seen first, each with ref, title, tags, category, filing date, and summary cut to `filing.seen_summary_chars` (default 1,500). Deleted thoughts are skipped. Search results in the tool text also carry their ref, so the model can name a thought it just found.

`parse_proposal()` refuses two parts with the same `add_to` (`ToolArgumentError`, which the model gets back and fixes in the next round). A ref that is not in the conversation's list, or whose thought is gone or belongs to another user, makes the part a new thought; the server logs it.

**Alternatives:** thought UUIDs in the tool (rejected: the `conversation-agent` spec keeps ids from the model, and they cost more tokens); refs numbered per turn (rejected: a delete or the cap shifts the numbers, and an old `T1` in the history would name another thought); only thoughts filed from this conversation (rejected: a user who comes back to an idea a year later, in a new chat, could never build on it); a table of refs (rejected: the stored rows already fix the order).

### 3. Part shape

A stored part gains optional keys: `add_to` (thought id), `based_on` (the thought's `updated_at` when the proposal was written), `similar` (`{thought_id}` for the "Similar" hint), and, once confirmed, `thought_id` as today. The tool schema gains, per part, `add_to` (a ref) and `new` (true when the model keeps it new after a candidate round). For an addition, the model's `title` is ignored; the schema description says so.

The proposal payload (stream event, messages answer, offered proposal) adds, per part, `target`: the thought's current `{title, summary, tags, category, updated_at}`, or `{deleted: true}`, read in the same one-query lookup that `thought-editing` adds for `saved_title`; and `similar`: `{thought_id, title, created_at}` or null. For an addition, the card pre-fills tags with the current tags followed by the model's new ones, without repeats, and the category with the model's category, else the current one.

### 4. The similar-thought check: three layers

**Layer 1, candidates.** When a `propose_thought` call has new parts (no `add_to`, no `new: true`), the server embeds all their queries (title, summary, tags) in **one** embedding request, then runs the hybrid search SQL once per part with that vector. `search.py` gains a function that takes a vector instead of embedding the query itself. A candidate passes the *candidate cut-off* (decision 5) or the existing word-share rule, up to 3 per part, excluding thoughts already named by another part. With no key or a provider error, the words half still runs.

**Layer 2, the model decides.** If any part has candidates, no proposal is written. The tool result lists the candidates with their refs, filing dates, tags, and summaries, and asks the model to call `propose_thought` again, giving each new part `add_to` or `new: true`. For a part with the category `task`, the result adds: "A repeated task is usually a new task." The candidates are stored as `details.similar` on that tool message, so they get refs. A candidate round writes no proposal, so it does not set `Turn._proposed`; the one-proposal-per-turn rule still refuses any call after a proposal is written. A second `propose_thought` in the same turn skips layer 2. It runs layer 1 again only to find layer 3's strong match, because the model may reorder or rewrite the parts; that is one more embedding call, and no more model calls. The existing round limit bounds this; the check adds at most one round.

**Layer 3, the user decides.** When the written proposal has a new, non-task part whose best candidate passed the *strong cut-off*, the part stores `similar`, and the card shows the hint. "Add to it instead" turns the card into an addition card on the client; the confirm then sends `add_to`. The server accepts it because the candidate is in the conversation's seen list.

**The offer before `/compact` and archive** makes its asked call as on `main`, with the seen-thoughts note. If layer 1 finds candidates, it makes a second asked call with the candidate note appended. The model can decline either call, and then nothing is offered. So the offer costs two model calls only when candidates exist.

**Alternatives:** always send the top 3 to the model with no cut-off (rejected: a tool round and about 3,000 tokens on every proposal); only layer 3 (rejected: the user would have to spot every match; the model sees the discussion and judges better); a separate judge model call (rejected: an extra call and a second model the user did not choose); run the check only for `/push` or only for discussions (rejected: the year-later case comes through both).

### 5. Cut-offs that adapt to any embedding model

Similarity scales differ a lot between embedding models, and new ones keep coming. So the cut-offs come from the user's own index, not from a table of models:

- `search_indexes` gains `similarity_p95` and `similarity_p99` (nullable floats) and `baseline_thoughts` (int). They are the 95th and 99th percentile of cosine similarity between the head entries of up to 2,000 random pairs of the user's thoughts in that index. Postgres computes this from stored vectors, with no embedding call.
- The baseline is measured when an index becomes active (after a rebuild), and again when the user's thought count reaches 1.5 times `baseline_thoughts`, in the same request that stores the thought, after its commit.
- Candidate cut-off = `p95 + filing.similar.candidate_margin` (default 0.02). Strong cut-off = `p99 + filing.similar.strong_margin` (default 0.02). Both are never lower than the search cut-off for the model minus `filing.similar.floor_delta` (default 0.1).
- With fewer than `filing.similar.min_thoughts` (default 30) thoughts, the baseline is not measured. The candidate cut-off is then the search cut-off minus `floor_delta`, and the strong cut-off is the search cut-off.
- The `chat.yaml` glob rules still work as an operator override for a model that behaves badly.

The idea: a true match is much more similar than a typical pair of the user's unrelated thoughts, in any model. The percentiles measure "typical" per model and per user.

**Alternatives:** a fixed threshold per model in config (rejected: every new model needs a tuning run before the check works); rank only, top 3 with no cut-off (rejected, see decision 4); a threshold per user learned from their "add" and "file as new" choices (deferred: good later, needs data this change creates).

### 6. The measurement job

`python -m app.evals.similar_thoughts --provider <id> --model <id> [--chat-provider <id> --chat-model <id>]` reads `backend/evals/similar_thoughts.yaml`:

- about 30 **pairs**: a filed thought and the same thing revisited later in other words;
- about 30 **near-misses**: the same topic but a different thing (including repeated tasks);
- about 200 **background** thoughts, so the baseline has a realistic corpus.

It embeds everything with the operator's key from the environment into a temporary in-memory index, measures the baseline as decision 5 does, and reports: recall (the true match is among the candidates) and false-offer rate (a near-miss passes the strong cut-off). Targets are in the file: recall at least 0.9, false offers at most 0.1. With a chat model, it also runs layer 2 on each case and reports how often the model picks right. It exits 1 when a target is missed.

The file is data, so new cases need no code. Run it when a preset or default embedding model is added or changed, and when a new chat model is added to a preset. The first test set is drafted synthetically and reviewed by the project owner.

**Alternatives:** tests in CI with a fake embedder (kept for the logic, but they prove nothing about a real model); a one-off notebook (rejected: not repeatable for the next model).

### 7. Confirming an addition

The confirm route takes, per request, `mode`: `"new"` (today's behaviour) or `"add"` with `add_to`. For `"add"`, in one transaction:

1. Lock the proposal row, as today. Re-read the target: missing or foreign → 404 `not_found`, with the message "The thought this adds to no longer exists. File it as a new thought instead."
2. If `thought.updated_at != part.based_on` → 409 `thought_changed`, with the thought's current fields. The card updates its "current" column and `based_on`, and the user confirms again.
3. Check the fields with `check_fields()` and the category with `check_category(keep=current)`.
4. Build the new raw text (decision 8).
5. Insert a `thought_additions` row with the fields before the change (decision 9).
6. Apply summary, tags, category, and raw text through `apply_update()`: `update_thought()` split into a part that does not commit and a wrapper that does, as `add_thought()` and `store_thought()` already are.
7. Set the part's `thought_id` to the target, and clear the held proposal if every part is now saved. Commit.

The title is never changed. The thought's `proposal_id` (origin) is never changed.

**Alternatives:** a separate "add" endpoint (rejected: the proposal lock, the held-proposal bookkeeping, and the repeat-confirm answer are the same as confirm's); last write wins with no version check (rejected: the card was built from an older summary and would silently overwrite a drawer edit).

### 8. The raw text rule

The messages: the user's messages with a position after the last one this thought already holds from this conversation (the highest `to_position` of its origin proposal and its additions from this conversation), up to the proposal's `to_position`. For a thought first seen in another conversation, that is simply the proposal's raw text. Nothing left → the raw text is unchanged, the fields still update.

The format: `<earlier raw text>\n\n--- added 2026-09-26 ---\n\n<messages joined by blank lines>`.

The cap of 20,000 characters, applied to the blocks (the first block is the text the thought was filed with; each later block is one addition):

1. The first block is kept, cut at its end with `…` only when it is longer than 10,000 characters.
2. Then the newest blocks, whole, newest first, while they fit. The newest block alone is cut at its start if it does not fit.
3. Where blocks were left out, one line: `--- earlier additions left out ---`.

The left-out text is not lost: it stays in its proposal's `raw_text` while that conversation exists.

**Alternatives:** keep only the most recent text, as `fit_raw_text()` does (rejected: after enough additions, the user's original words go first, and they are the record); no cap (rejected: the store refuses raw text over 20,000, and search pieces grow with it).

### 9. `thought_additions` and undo

One table: `id`, `thought_id` (cascade), `user_id`, `proposal_id` (cascade: deleting a conversation removes its additions from the list; the raw text keeps what was added), `from_position`, `to_position`, `added_at`, `after_updated_at`, `before` (JSON: title, summary, tags, category, raw_text), `undone_at` (nullable). Indexed on `thought_id`.

`GET /api/thoughts/{id}` gains `additions`: newest first, each with `id`, `added_at`, `undone`, `conversation_id`, `conversation_title`, `proposal_id`. One join, like `origin`.

`POST /api/thoughts/{id}/additions/{addition_id}/undo` restores `before` through `apply_update()` and sets `undone_at`, in one transaction. It is refused with 409 `thought_changed` unless the addition is the newest not undone and the thought's `updated_at` equals the addition's `after_updated_at`. The part's `thought_id` stays, so the proposal is not offered again; the card reads the addition's `undone` state and says "Addition undone".

**Alternatives:** no undo (rejected: a model rewrite of the summary is otherwise irreversible); keep `before` on the proposal part (rejected: undo and the drawer list would search JSON across proposals); full version history (rejected: more than one undo step is not needed yet).

### 10. Origin and the detail view

`thoughts.proposal_id` keeps the proposal the thought was first filed from. "From" in the detail view means where it started. The additions list (decision 9) shows where it grew, each linked to `/app/<conversation_id>?proposal=<proposal_id>`, reusing `explore`'s anchor.

**Alternatives:** point `proposal_id` at the latest proposal (rejected: "From" would lose the filing date and place).

### 11. Re-embedding

An addition always changes the raw text or the summary, so `apply_update()` re-embeds all the thought's pieces: one embedding call. An undo does the same. A failure is handled as for confirm and edit: the change commits, search finds it by words at once, and the backfill adds the embeddings later. The layer 1 check is one more embedding call per proposal with new parts, and one more when the model proposes again after a candidate round.

### 12. The addition card

The card shows two columns on wide screens, stacked on narrow ones: "Now" (the current summary, read-only) and "After" (the proposed summary, editable). Words removed and added are marked with a word-level diff computed on the client: a small longest-common-subsequence helper in `lib/word-diff.ts`, fine for summaries up to 4,000 characters, with no new dependency. The diff follows the user's edits.

## Risks / Trade-offs

- [Depends on `thought-editing`, not built, and on `explore`, merged and archived] → The tasks start after `thought-editing` merges. If `origin`, `check_category()`, the `saved_title` lookup, or the offer code (`asked_proposal()`, `offer_note()`, `Turn._proposed`) change shape, re-read decisions 2, 3, 4, 7, and 10.
- [This change modifies "The offer before an action may propose nothing", which `explore` added] → `explore` is archived, so the requirement is in the main `conversation-agent` spec. If a later change modifies it first, rebase this delta onto that text.
- [`background-turns` (planned) moves the turn into a background task that replays events to a returning chat] → No requirement overlaps. A candidate round emits only a tool event and no proposal event, so a replay shows no card for it. Whichever change is built second rebases its `turn.py` edits onto the other's.
- [A model rewrite of the summary can drop a detail] → The card shows Now and After with the changes marked, and undo restores the summary.
- [A user's corpus full of related thoughts raises p95, so real matches can fall under the candidate cut-off] → The floor in decision 5 caps how high the cut-off goes, and the measurement job checks recall with a realistic background.
- [Small local models may not follow the two-step protocol] → A second proposal is always shown, a part with neither `add_to` nor `new` becomes new, and layer 3 still offers the match.
- [Tokens: the seen-thoughts note on every turn, and up to 3 candidate summaries in a check round] → Both caps are config values. The end-to-end task records the prompt tokens of a turn with and without the note.
- [A decision reversed a year later gets merged into the old one] → The tool description tells the model to say in the summary what changed and when, and it may keep a reversed decision new. The Now/After view shows it.
- [The baseline is measured in a user's request after a store] → It reads at most 2,000 pairs of stored vectors, with no provider call; if it fails, it is logged and the old baseline stays.

## Migration Plan

1. One Alembic migration after `explore`'s (`8a4d6f2b9c13`): create `thought_additions`; add `similarity_p95`, `similarity_p99`, and `baseline_thoughts` to `search_indexes`. No backfill: baselines are measured on the next rebuild or on growth, and cold users use the fallback. Downgrade drops both.
2. Backend first. A frontend without the new fields shows an addition part as a normal card; confirm then gets `mode` missing, which defaults to `"new"`.
3. Rollback: downgrade and deploy the previous build. Thoughts keep what additions wrote; only the additions list and undo go.
