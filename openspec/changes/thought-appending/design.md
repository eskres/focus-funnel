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

**Layer 2, the model decides.** If any part has candidates, no proposal is written. The tool result lists the candidates with their refs, filing dates, tags, and summaries, and asks the model to call `propose_thought` again, giving each new part `add_to` or `new: true`. For a part with the category `task`, the result adds: "A repeated task is usually a new task." The candidates are stored as `details.similar` on that tool message, so they get refs. A candidate round writes no proposal, so it does not set `Turn._proposed`; the one-proposal-per-turn rule still refuses any call after a proposal is written. A second `propose_thought` in the same turn skips layer 2. It runs layer 1 again only to find layer 3's strong match, because the model may reorder or rewrite the parts; that is one more embedding call, and no more model calls. The existing round limit bounds this; the check adds at most one round. In the last round the limit allows, no round is left for that call, so layer 2 is skipped there: the proposal is written at once, with layer 3's strong match, and the user still gets a card.

**Layer 3, the user decides.** When the written proposal has a new, non-task part whose best candidate passed the *strong cut-off*, the part stores `similar`, and the card shows the hint. "Add to it instead" turns the card into an addition card on the client; the confirm then sends `add_to`. The server accepts it because the candidate is in the conversation's seen list. Two parts of one proposal never add to one thought: a thought several parts match strongly is named on the closest part only, and the confirm refuses an addition to a thought another part of the proposal was saved to (409 `proposal_part_saved`).

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

### 13. `apply_update()` takes the loaded thought (decided during task 1.2, 2026-11-05)

`apply_update(session, user, thought, ...)` takes the `Thought` row the caller loaded, not its id, so confirm-add and undo can lock the row (`SELECT ... FOR UPDATE`), compare its `updated_at`, and change that same row in one transaction. It checks the fields, re-indexes what changed, and flushes; it never commits. `update_thought()` keeps its signature: it loads the thought with `get_thought()` (404 for a missing or foreign one), calls `apply_update()`, commits, and refreshes.

**Alternatives:** pass the id and load inside (rejected: a second load could miss the caller's lock and the version it checked).

### 14. Raw text blocks in detail (decided during task 1.3, 2026-11-05)

The rule from decision 8 lives in `app/chat/raw_text.py` as pure functions: `added_texts()` picks the messages, `extend_raw_text()` appends and fits, and `split_blocks()`/`join_blocks()` read and write the blocks. Details decision 8 left open:

- The messages are the user's messages with a position in `[max(from_position, held_to + 1), to_position]` of the proposal, where `held_to` is the highest `to_position` the thought already holds from this conversation (its origin proposal and its additions there), or none. This fits the spec's "that the proposal covers and that the thought does not already hold" and decision 8's "after the last one this thought already holds". Messages go through `text_for_model()`, as a proposal's raw text does; empty ones are skipped.
- No raw text is an empty first block. The raw text then starts with the separator, without the blank lines before it, because the store strips the raw text.
- The marker line follows the first block, before the oldest separator kept: `<first>\n\n--- earlier additions left out ---\n\n--- added ... ---`. A marker already in the raw text stays, once.
- A first block over 10,000 characters is cut to 10,000 including the `…`. The newest block, when it alone does not fit, keeps its end, after a `…`, so the result is exactly 20,000.

**Alternatives:** keep blocks in a JSON column (rejected: the raw text is what search and the detail view read, and a second copy would drift).

### 15. Refs in detail (decided during task 2.1, 2026-11-05)

Refs live in `app/chat/refs.py`. Details decision 2 left open:

- **Order within the rows.** Rows are taken by position. Within one position: a tool message's `details.sources`, then its `details.similar`, then the parts of the proposals there (in `list_proposals()` order, then by part index). For each part, its `add_to` and `similar.thought_id` count at the proposal's position.
- **A late confirm.** A part's `thought_id` is written when the user confirms, which can be long after the proposal. If it counted at the proposal's position, a thought first seen in a search between the proposal and the confirm would be renumbered. So confirm stamps the part with `seen_position`: the position after the conversation's last stored message, and the part's `thought_id` counts there. A part saved before this change has no stamp and counts at its proposal's position. The stamp is not sent to the chat. A confirm can land while a turn runs: its stamp is then the position of the turn's next stored row, whose sources and candidates count before it. So the refs a turn numbers new thoughts from, for the search and the check, leave out a part stamped at or after that position; it is numbered after the row's thoughts, as every later load numbers it.
- **Another user's thought** can only be in a crafted row. It gets no number. The lookup is one query over every id the rows name: it reads the user's own thoughts in full and, for another user's, only that the row is not theirs (each column is a `CASE` on the owner), so a foreign id (skipped) and a deleted one (no row; it keeps its number) are told apart. An owner never changes, so a foreign id is skipped for good. The conversation answer takes its saved titles from the same lookup, so it still makes one `thoughts` query.
- **Search results.** The search tool text gives each result its ref (`1. T3 · Title · date · #tags`). The turn computes the refs from the stored rows before each search, and a result seen for the first time is numbered after every other, in the order of `details.sources`, so the next turn computes the same numbers. Without refs, the text is unchanged.
- **The note.** It is a system message just before the held-proposal note, listing ref, title, filing date, tags, category, and the summary cut at `filing.seen_summary_chars`, most recently seen first (by the last row that names the thought). Code defaults (3 and 1,500) apply when `chat.yaml` has no value. The context meter in the conversation answer counts it.
- **The offer.** The seen-thoughts note replaces `FILED_NOTE`, which is removed. After `OFFER_NOTE`, when the note lists any thought, one more paragraph says those thoughts are filed already and that new facts about one of them are an addition with `add_to`. In the offer, the note lists every thought this conversation saved or added to, past the `filing.seen_thoughts` cap, as `FILED_NOTE` listed every filed title.
- **The held note** names an addition's target as `Adds to: T1`, so a re-proposed held addition keeps its target. `drop_held_note()` finds the note by its first line.

**Alternatives:** number a foreign id but never list or resolve it (rejected: the task asks that it get no ref, and either way only a crafted row can hold one); a part's `thought_id` at its proposal's position (rejected: a late confirm renumbers later refs).

### 16. Resolving a ref when the proposal is written (decided during task 2.3, 2026-11-05)

`parse_proposal()` reads `add_to` (case and spaces are ignored: ` t2 ` is `T2`) and `new` (true, or the text "true"). Two parts with the same ref are a `ToolArgumentError`; an `add_to` that is not text is one too. Text that is not a ref is kept as it is, so it resolves to nothing. `ProposalPart.as_dict()` carries the ref as `add_to_ref`, and `new` is not stored.

`write_proposal()` resolves the refs, from the rows it already loads, only when a part has one. A ref naming the user's existing seen thought gives the stored part `add_to` (the id), `based_on` (the thought's `updated_at` in ISO form, so confirm compares it exactly and the client sends it back unchanged), and the thought's current title in place of the model's: an addition never changes the title, so the model's is dropped. Any other ref leaves a plain new part, and is logged. The proposal payload carries `add_to` and `based_on` on every part, null for a new thought, in the stream event and the conversation answer alike.

**Alternatives:** keep the model's title on the part for "File as new" (rejected: the spec says the model's title for an addition is ignored, and the card names the thought by its current title; the user can rename a card filed as new).

### 17. The similar-thought check in detail (decided during tasks 3.1 and 3.3, 2026-11-05)

The check lives in `app/chat/similar.py`; `search.py` gains `search_by_vector()`, which runs `rank()` with a vector the caller already has and with the check's own cut-off and limit (`rank()` takes optional `min_similarity` and `limit`). Details decision 4 left open:

- **What is embedded and matched.** A part's query is its head entry's text (`head_text(title, tags, summary)`), with no query instruction, so its similarities are on the scale of the baseline, which compares head entries. The words half matches title and tags only: with the whole summary as the query, the word-share rule is rarely reached.
- **No index, no key, no thoughts.** The check never creates an index. With no active index, or a provider error, it matches by words only, and a words-only candidate never counts as a strong match. It runs only on Postgres and only for a user who has thoughts, so it makes no embedding call otherwise.
- **Which parts.** A part whose `add_to` names a seen thought is not checked, and the thoughts such parts name are no other part's candidates. On the first call, a part with neither `add_to` nor `new: true` gets candidates for layer 2. Any part that is not an addition and not a `task` is checked for layer 3's strong match, on the first call and after a candidate round, so a part the model marks `new` at once can still get the hint.
- **The candidate round.** The tool result lists each part's candidates (ref, title, filing date, tags, category, summary cut at `filing.seen_summary_chars`) and asks for the call again; the tool event's summary is "Checked for similar thoughts". The tool message stores the candidates as `details.similar`, each `{id, title, created_at, tags}` like a source, kept apart from `details.sources` so the chat does not list them as an answer's sources. A candidate new to the conversation is numbered after every other ref in the listed order, which is the order the next turn computes from the stored rows.
- **The round after a candidate round is forced** to call `propose_thought` (the model still chooses `add_to` or `new` for each part), because only round 0 is forced otherwise, and a model answering in words would leave the user with no card. `tool_rounds` stays 3: a turn that searches, gets candidates, and proposes reaches the limit before its closing words. The proposal is shown and stored all the same; raising `tool_rounds` to 4 is the owner's call.
- **The offer** numbers its candidates in memory (`Refs.see()`), appends the candidate note as a system message for the second asked call, and resolves that call's refs with the same refs, so an `add_to` naming a candidate becomes an addition though no stored row names it yet.
- **`similar` on a stored part** is `{thought_id}`. The payload's title and filing date for it come with task 4.2.

**Alternatives:** embed the query with the search's query instruction (rejected: its similarities would not compare with the head-to-head baseline); store the candidates in `details.sources` (rejected: the chat would show them as the answer's sources).

### 18. The baseline in detail (decided during task 3.2, 2026-11-05)

The baseline lives in `app/thoughts/baseline.py`. Details decision 5 left open:

- **Pairs.** While the index's head entries make at most 2,000 pairs, every pair is compared, so the result is exact and repeatable. Past that, 2,000 random pairs of two different heads are drawn by row number (a pair can repeat). Postgres computes `percentile_cont(ARRAY[0.95, 0.99])` over `1 - (a.embedding <=> b.embedding)`, on `chunk = 0` rows only.
- **When.** `app/reembed.py` measures the new index right after the swap commits. After a store (`store_thought()` and confirm), once its commit is done, the active index is measured when the user has at least `min_thoughts` thoughts and the index has no baseline yet or the count reached 1.5 times `baseline_thoughts`; so an index that became active below the minimum gets its first baseline as the user grows. The minimum counts the index's head entries; `baseline_thoughts` records the user's thought count.
- **Failure.** The measurement runs in a savepoint and catches every error: it is logged, the old values stay, and the store has already committed.
- **Cut-offs.** Decision 5 is read literally: candidate = max(p95 + `candidate_margin`, search cut-off - `floor_delta`), strong = max(p99 + `strong_margin`, search cut-off - `floor_delta`); the floor guards the low side, as "never lower than" says, and the Risks line about the floor capping the cut-off means that. With no baseline, they are the floor and the search cut-off. Cut-offs over 1 are possible for a user whose thoughts are near copies of each other; meaning then finds nothing, and words still run.
- **`chat.yaml`.** `filing.similar` holds `candidate_margin`, `strong_margin`, `floor_delta`, and `min_thoughts`, each with a code default when the file has none.

**Alternatives:** an O(n²) self-join always (rejected: too slow for a large index); `TABLESAMPLE` (rejected: it samples pages, not pairs, and is not deterministic for the small case).

### 19. Confirm, payload, and undo in detail (decided during tasks 4.1 to 4.3, 2026-11-05)

The confirm, the additions list, and undo live in `app/thoughts/additions.py`. Details decisions 3, 7, and 9 left open:

- **The confirm body.** `ConfirmIn` gains `mode` (`"new"` by default, so an older client files as before), `add_to`, and `based_on`. The target is the body's `add_to`, else the part's own; the version is the body's `based_on`, else the part's. So the "Similar" hint, whose part has no `add_to` or `based_on`, sends the id and `updated_at` the payload gave it, and a card that got a 409 sends the version from the error. Versions are compared as datetimes, exactly.
- **Checks, in order.** An addition covers one part (a merge is 422). The target thought is locked (`SELECT ... FOR UPDATE`); missing or another user's is 404 with the file-as-new message. It must be a thought this conversation has seen (its refs, which include every part's `add_to` and `similar`), else 422: a crafted body cannot add to an unrelated thought. Then the version check, then the category with `keep` set to the thought's own. Nothing is written before these pass.
- **409 `thought_changed`** keeps `code` and `message` and adds `error.thought`: `{id, title, summary, tags, category, updated_at}`. `ApiError` gains an optional `extra` merged into the error object.
- **The raw text's `held_to`** counts the origin proposal and the additions from this conversation that are not undone: an undo restored the raw text, so those messages are no longer held.
- **No baseline** is measured after an addition: it adds no thought, so it cannot be due. The confirm answers `"Added."`.
- **The payload.** Each part gains `target` (for an addition: the thought's `title`, `summary`, `tags`, `category`, `created_at`, `updated_at`, or `{"deleted": true}`), `similar` (for the hint: the same fields and `thought_id`, or null once the match is gone, so taking the hint needs no extra request), and `added` and `undone` (from the `thought_additions` row of that proposal and thought, so a reloaded card says "Added to" or "Addition undone"). The conversation answer takes the thoughts from its refs lookup, which already names every id the parts hold, and reads the proposals' additions in one more query, skipped when no part is saved. The stream event and the offer use `part_lookup()`: one query for the thoughts, at most one for the additions. `saved_titles()` is gone.
- **The additions list** is one join (`thought_additions` → `proposals` → `conversations`), newest first by `added_at`. A deleted conversation cascades to its proposals and their additions, so they drop out of the list.
- **Undo** locks the thought, then refuses with 404 an addition that is not this thought's (or the user's), and with 409 `thought_changed` one that is not the newest not undone (an undone one included) or a thought whose `updated_at` moved past `after_updated_at`. It restores every field in `before`, title included (unchanged by an addition, and any rename since already refuses the undo), sets `undone_at`, commits, and answers the thought as `GET` does. Every undo moves `updated_at`, so the addition before it always fails the version check: in practice one undo step, as the non-goals say, and the sheet offers undo only when the newest addition is not undone.

**Alternatives:** let the hint's confirm read the version on the server (rejected: it would skip the check that the user saw the current summary); the stored part's `based_on` only (rejected: after a 409 the card could never confirm against the new version).

### 20. The measurement job in detail (decided during task 5.1, 2026-11-05)

The job is `app/evals/similar_thoughts.py`, and the test set is `backend/evals/similar_thoughts.yaml`. Decision 6 left these details open:

- **The in-memory index.** Every filed thought of a case and every background thought makes up the corpus. Each corpus thought, and each case's later thought (the query), is embedded once as its head entry (`check_query()`, with no query instruction, as the check embeds a part). The baseline is computed in Python, as the SQL of decision 18 computes it: every pair up to 2,000, past that 2,000 random pairs of different heads from a fixed seed so a run repeats, and `percentile_cont` interpolation. The cut-offs come from the app's own `cutoffs()` and `chat.yaml`. So no database is needed.
- **Meaning only.** The words half of the check does not depend on the model and needs Postgres full-text search, so the job leaves it out. Recall is therefore a lower bound, and false offers are exact, because a match by words only never gets the hint.
- **The rates.** Recall is the share of pairs whose filed thought is among the later thought's candidates: past the candidate cut-off, best first, at most three. A false offer is a near-miss whose best candidate, whichever thought it is, passes the strong cut-off. As in the app, a task never gets the hint, so near-misses whose later thought is a task are left out of that rate. Repeated tasks therefore count only in the model's choice.
- **Layer 2** (with `--chat-model`). For each case with candidates, the model sees the system prompt, the later thought's summary as the user's words, its first `propose_thought` call, and the candidate note from `candidates_note()`. The call is forced to `propose_thought`, as the round after a candidate round is. It is right when it adds to the filed thought for a pair, and when it files as new for a near-miss. That rate is reported with no target, because decision 6 gives none.
- **Exit status.** 0 when both targets are met, 1 when one is missed, and 2 when the job cannot run (no key, an unknown provider, a malformed test set, a provider error). The provider, model, and dimensions default to the app's embedding settings.

**Alternatives:** a scratch Postgres database as in `scripts/search_eval.py` (rejected: the operator would need a database, and only the words half would gain); counting a repeated task's strong match as a false offer (rejected: the app never shows it).

### 21. The addition card and the sheet in detail (decided during tasks 6.1 to 6.3, 2026-11-05)

The diff is `lib/word-diff.ts`; the card is in `proposal-card.tsx`; the list and undo are in `thought-sheet.tsx`. Details decisions 9 and 12 left open:

- **The diff.** Words are compared without the spaces around them, and punctuation belongs to its word (`lock` and `lock.` differ). The shared start and end are trimmed before the longest-common-subsequence table, which is one typed array. A moved word is removed in one place and added in the other. Two different 4,000-character summaries take about 15 ms.
- **Marks and editing.** A textarea cannot show marks, so "Now" shows the current summary with the removed words marked, and "After" is the editable textarea with the same text below it, the added words marked. Both follow each keystroke.
- **Taking the hint.** The model wrote the new idea on its own, but an addition's summary is the thought's whole new summary (decision 3). So "Add to it instead" starts "After" as the match's summary, a blank line, then the card's summary. Tags are the match's, then the card's. The category is the card's, else the match's. The version sent is the payload's `similar.updated_at`. "File as new" then restores the card as proposed. For the model's own addition, "File as new" keeps the user's edits, with the thought's title in the title field, because decision 16 dropped the model's title.
- **Refusals.** A 404 marks the target gone: the card says so and offers only "File as new". A 409 replaces the Now column, the title, and the version with `error.thought`, and keeps the user's text and the server's message. The client's `ApiError` gains `details` (the error object's other keys), and `thought_changed` maps to `ThoughtChangedError`.
- **Merge** is hidden while any part has `add_to` or a card took the hint.
- **Saved states.** A card says "Added to:" for `added`, or after an add in this page, and "Addition undone:" for `undone`. An undo in the sheet announces `thought-changed` with `undone` set to the addition's proposal id, so that card changes at once.
- **The sheet.** It lists the additions under "Added to from", each linked like the origin. "Undo last addition" shows only when the newest addition is not undone (decision 19). It asks in the confirmation dialog the delete uses, with its button labelled "Undo". A 409 shows the server's reason in that dialog, and nothing changes.

**Alternatives:** an overlay of marks over the textarea (rejected: fragile with wrapping and scrolling, for no gain over a preview); the hint's "After" as the card's summary alone (rejected: confirming it would replace the thought's summary with the new idea and drop what it held).

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
