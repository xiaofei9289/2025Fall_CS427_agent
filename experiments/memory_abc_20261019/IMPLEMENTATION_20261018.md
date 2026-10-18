# Implementation notes — 2026-10-18

This note records the changes made after the first 10-task pilot.  The
pre-registered design in [DESIGN.md](DESIGN.md) is unchanged; the fixes make the
implementation match the design's invalidation claims.

## Evidence invalidation fixes

The summary used to be built only from the turns that were no longer in view.
That misses a write in the **retained window**: the read is summarized, the
write is visible, and the summary still calls the read "confirmed".  The policy
now passes the retained turns to `build_evidence_summary(..., later_segments=...)`;
later writes remove the summarized read, add a compact "superseded by later
edits" line, and mark any summarized test pass as "before a later change; not
verification".  A later test failure has the same effect.

Three smaller leaks are fixed at the same time:

- `cat file && sed -i ... file` was classified as a read because the read check
  ran first.  Writes are now checked first; a mixed command records the write and
  only keeps reads of files it did not modify.
- Re-reading a path now moves it to the end of the bounded read list, so the
  latest read and its source step are the ones retained.  Before, a re-read kept
  the path's original insertion position and could be dropped.
- Passing tests are no longer "other executed actions".  They have their own
  section and survive trimming longer than reads/actions.  A pass before a later
  edit (or a later test failure) is shown as an earlier run, not as verification.
- Redirects to logs/temp files (`*.log`, `*.out`, `/tmp/...`) are not treated as
  source edits, so `pytest ... > /tmp/pytest.log` still counts as verification.

## New report metrics

`analysis.py` now replays every task offline through its own policy.  No model or
environment calls are made.

| Metric | Definition |
| --- | --- |
| `estimated_prompt_tokens` | Sum of the per-call estimated view totals in `memory_trace.jsonl` |
| `actual_prompt_tokens` | Sum of provider `usage.prompt_tokens` from the trajectory |
| `repeat_reads` | Successful read of a path whose previous read happened with no intervening write |
| `recovery_reads` | A repeat read where the previous read was not fully visible in the prompt |
| `lost_recovery_reads` | Recovery read where the previous read was not visible at all (not even summarized) |
| `lost_read_exposures` | Current reads absent from the prompt at a later read, summed over calls |

These are deterministic proxies, not causal error labels.  `replay_errors` counts
trajectories that could not be parsed and is reported rather than hidden.

## What is deliberately not wired in

`full.yaml` defines an optional no-compression arm (`memory_policy:
full`).  It is **not** part of the A/B/C report and `run.py --arm all` does not
run it.  A clean no-compression comparison needs its own study/tags so the
pre-registered A/B/C block is not changed after the pilot.  The policy sends the
full transcript and records `budget_enforced=false`; the analysis helper ignores
over-8000 prompts for that policy, but the A/B/C report itself deliberately does
not include the arm.

## Known limits (next, not P0)

- Reads are keyed by path.  Two `refined_read_file` calls on different line
  ranges of the same file collapse to the latest one; a symbol/range key would
  preserve both.
- `read_many_files` is counted by the replay but remains a generic action in the
  summary.  `find_definition`/`find_references` results are not promoted to a
  symbol section.  A task-aware or symbol-aware ledger is the natural next arm;
  it should be pre-registered separately rather than slipped into B.

## Remaining work

1. Rerun the 10-task pilot and require `memory_search` usage > 0 before treating
   C-B as a retrieval effect.
2. Run the clean no-compression arm as a separate product comparison, not inside
   the A/B/C pre-registration.
3. Only then spend the formal 50-task × 3-arm × 2-round budget.
