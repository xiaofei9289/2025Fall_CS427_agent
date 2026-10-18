# A/B/C memory experiment

A clean implementation of the pre-registered comparison in [DESIGN.md](DESIGN.md):

- **A (`window`)**: system + task + newest complete turns that fit.
- **B (`summary`)**: the same window plus a bounded deterministic evidence summary of dropped turns.
- **C (`summary_search`)**: B's prompt policy plus `memory_search` over this run's transcript and a C-only instruction to call it when earlier evidence is no longer visible.

All arms share one 8000 estimated-token prompt budget, one task set, one model, one prompt, the same ordinary tools, 400 steps, and $10 per task. The summary is capped at 1000; a single retrieval result is capped at 1500. The summary and retrieval results are inside the 8000, not extra.

## Why this is clean

- The only field that differs between arm configs is `agent.memory_policy`; the loader rejects any other override.
- `memory_search` is installed by the C policy, not by `enabled_tools`, so A/B cannot accidentally expose it.
- History is kept as complete action/observation turns, never individual messages; A cannot produce an observation without its action.
- The task is pinned in every view; if it cannot fit, the agent fails loudly instead of silently losing the goal.
- Every view is written to `memory_trace.jsonl`: token accounting, sent/dropped indices, summary text, task presence, retrieval tokens. The report audits budget compliance rather than trusting the agent.
- The summary is deterministic and pure: B and C summarize the same dropped turns identically, and a replay yields the same summary. It is not a second model call. See [DESIGN.md](DESIGN.md) §6 for why this is the deliberate choice for a clean C−B comparison.
- The first 10-task pilot found that C never called `memory_search`; see [PILOT_20261018.md](PILOT_20261018.md). The next pilot must show search usage before C−B is treated as a retrieval effect.
- A C-only p2c smoke on the integrated source repeated the zero-search result and exposed a fatal oversized-action budget case; see [PILOT_P2C_20261018.md](PILOT_P2C_20261018.md). The action is now clipped, and C has an explicit call-when-needed instruction; rerun the smoke before the full p2.
- Invalidation now covers writes in the retained window, mixed read/write bash commands, re-read recency, and test passes invalidated by a later change; see [implementation notes](IMPLEMENTATION_20261018.md).
- `comparison.md` includes offline mechanism metrics: mean estimated/actual prompt tokens, repeat reads, recovery re-reads, and lost read exposures. These are proxies, not causal error labels.
- `full.yaml` is an optional no-compression arm for a **separate** product comparison. It is not part of the A/B/C report.

## Run

The desktop launcher freezes `src`, verifies its digest, and runs inside the existing Linux container.

```powershell
# pilot: first 10 tasks, all three arms, then grading and report
python experiments/memory_abc_20261019/desktop.py all --arm all --pilot --workers 2

# formal: 50 tasks, one round at a time
python experiments/memory_abc_20261019/desktop.py all --arm all --round r1 --workers 2
python experiments/memory_abc_20261019/desktop.py all --arm all --round r2 --workers 2

# compare a round (tags are a_r1, b_r1, c_r1)
python experiments/memory_abc_20261019/desktop.py compare --round r1
# descriptive pool over two complete rounds
python experiments/memory_abc_20261019/desktop.py compare --rounds r1,r2

# if only B and C are affordable, C-B is still the primary contrast
python experiments/memory_abc_20261019/desktop.py all --arm b
python experiments/memory_abc_20261019/desktop.py all --arm c
python experiments/memory_abc_20261019/desktop.py compare --arms b,c
```

Inside the Linux container:

```bash
python experiments/memory_abc_20261019/run.py generation --arm a
python experiments/memory_abc_20261019/run.py grading --arm a
python experiments/memory_abc_20261019/run.py compare
```

Outputs are `experiments/memory_abc_20261019/<tag>/` with `preds.json`, per-task trajectories, `memory_trace.jsonl`, and `evaluation/`. `comparison.json` and `comparison.md` are written at the study root.

## Read the report

- **C−B is primary.** It is the only contrast that isolates history search from the summary policy.
- `valid` must be true. A false value means a budget violation, a missing trace/grade, an unexpected agent exit, or mismatched controls; do not average an invalid run.
- `Bound tasks` are tasks where at least one arm dropped/clipped history or C called the search tool. `Never-bound` is the placebo: exact for A/B, a soft check for C because C always carries the tool description even when it never searches. A mismatch means provider nondeterminism, not memory.
- A single run is directional. Repeat with `--round` before claiming an effect; the design pre-registers at least two rounds and preferably three. `--rounds` writes a task-cluster descriptive pool without treating task-runs as independent.
- All tasks are listed. Do not select only the runs where C's search happened to help.

## Tests

```bash
MSWEA_SILENT_STARTUP=1 .venv/bin/python -m pytest -q \
  tests/memory/abc \
  tests/run/test_memory_abc_config.py \
  tests/run/test_memory_abc_analysis.py
```

The suite covers estimator exactness, task pinning, turn integrity, summary content and caps, retrieval boundary and cap, agent integration with a scripted model, config uniqueness, and the paired report (including C−B and invalid-run handling).
