# Prompt probes (tasks 12.1 to 12.5)

The probes ran on 2026-09-24 against `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` on Nebius, at temperature 0.3, `max_tokens` 8192, and no reasoning effort sent. The script is `backend/scripts/probe_prompt.py`, and its data sets are in `backend/scripts/probe_data/`. It builds each request with the app's own `build_context`, `plan_compaction`, and `compaction_request`, and runs tool calls the way a chat turn does.

```
cd backend
uv run python -m scripts.probe_prompt tools --runs 2 --report out.md
```

## Results

| Task | Probe | Baseline | Tuned | Check |
|---|---|---|---|---|
| 12.1, 12.2 | Tool choice, 43 labelled messages | 93% and 95% | 98% and 95% | ≥ 90% over two runs, no tool on a greeting or an unfinished message: **pass** |
| 12.3 | Topic change, unrelated message | 4 of 10 offered | 19 of 20 offered | ≥ 8 of 10: **pass** |
| 12.3 | Topic change, related message | 10 of 10 not offered | 20 of 20 not offered | ≥ 8 of 10: **pass** |
| 12.4 | Repeat proposals, 10 discussions × 3 more messages | 2 of 10 | 0 of 10 | ≤ 1 of 10: **pass** |
| 12.5 | `/compact`, 5 conversations, 33 checklist items | 5 items missing, one summary in German | 0 missing over two runs | every item survives: **pass** |

No greeting or unfinished message called a tool in any run. The median first round took 3 to 6 s.

## What changed

1. **The held-proposal note comes after the latest message** (`build_context`). Before the history, the model offered the held proposal on 4 of 10 unrelated messages. With a reworded note in the same place, it offered on 0 of 10.
2. **The turn removes the held-proposal note once it proposes** (`drop_held_note` in `turn.py`). With the note at the end, the model offered the held proposal, then offered it again every round until `tool_loop_limit` (7 of 10 unrelated messages). A change to the tool result text alone did not stop this. This loop would also have reached the real chat.
3. **The note asks the model to decide on the topic first**: "Before you answer, decide whether the user's latest message is still about this proposal's topic."
4. **The system prompt proposes a to-do or an idea at once, and waits for a conclusion in a discussion.** It also proposes each conclusion once. The first wording ("do not propose while the user is still explaining") dropped ideas to 4 of 12, and this wording fixed it.
5. **The proposal tool result tells the model to answer the latest message**, and to use one short sentence only when that message held nothing but the proposal. Before, it always asked for one short sentence, which fits a to-do but not an answer to a new topic.
6. **The `/compact` prompt names what to keep**: one line on the subject, then decisions with dates, places, and amounts, then every person, place, product, or book by name, then open questions. It writes in the language of the conversation's messages. The old prompt said "in the user's language", and the model wrote a Berlin marathon summary in German.

## Files

- `12.1-baseline-tools.md`: the prompt as built, before tuning
- `12.2-tools-tuned.md`: the tuned prompt, two runs
- `12.3-topic-baseline.md`, `12.3-topic-tuned.md`
- `12.4-repeat-baseline.md`, `12.4-repeat-tuned.md`
- `12.5-compact-baseline.md`, `12.5-compact-tuned.md`: each summary is in the report

The 12.5 baseline used stricter checklist patterns than the tuned run. The tuned run allows "4 h 15", "15 Mar", and quartz and oak on separate lines. The German summary and the dropped names (Marco, Utrecht) were real losses.

The repeat probe counts every proposal after the held one, because the continuation messages reach no new conclusion.
