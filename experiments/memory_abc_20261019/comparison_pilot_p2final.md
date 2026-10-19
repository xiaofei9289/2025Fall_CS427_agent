# A/B/C memory comparison

Tasks: 10; pilot (excluded from the secondary table): 10.
Valid: **True** (a false value means at least one arm broke the pre-registered budget).

> **C tasks without retrieval:** django__django-11532, django__django-13089, django__django-14855, django__django-15987, matplotlib__matplotlib-20826, pytest-dev__pytest-7982, sympy__sympy-13615. Their C-B contrast is not a retrieval test.

## Arms

| Arm | Policy | Resolved | Empty | Eval errors | Cost (USD) | API calls | Dropped calls | Clipped calls | Summary calls | Retrieval calls | Search tool calls | Violations |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| a | window | 9/10 | 1 | 0 | 0.304649 | 1156 | 976 | 0 | 0 | 0 | 0 | 0 |
| b | summary | 7/10 | 1 | 0 | 0.541272 | 538 | 404 | 0 | 404 | 0 | 0 | 0 |
| c | summary_search | 7/10 | 0 | 0 | 0.652567 | 635 | 517 | 4 | 513 | 30 | 3 | 0 |

## Estimator calibration

| Arm | Samples | Median actual/estimated | p90 | Max actual prompt |
| --- | ---: | ---: | ---: | ---: |
| a | 1156 | 1.136 | 1.188 | 11373 |
| b | 538 | 1.082 | 1.114 | 9150 |
| c | 635 | 1.077 | 1.122 | 11224 |

## Mechanism metrics (offline replay)

| Arm | Est. prompt tokens/call | Actual prompt tokens/call | Read events | Repeat reads | Recovery re-reads | Summary recovery | Lost recovery | Lost read exposures | Lost exposure rate | Replay errors |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| a | 7359.2 | 8340.9 | 31 | 15 | 2 | 0 | 2 | 4 | 0.160 | 0 |
| b | 6895.2 | 7468.0 | 16 | 8 | 3 | 2 | 1 | 0 | 0.000 | 0 |
| c | 6855.3 | 7389.9 | 34 | 9 | 1 | 1 | 0 | 1 | 0.200 | 0 |

`Recovery re-reads` count a successful re-read of a path whose previous read was not fully visible
in the prompt and where no write to that path intervened.  `Lost read exposures` count read
observations that were current (no later write) but absent from the prompt at the next read.
These are deterministic proxies from the transcript, not causal error labels; replay errors mean a
trajectory could not be parsed and are reported rather than hidden.

## Pre-registered contrast

| Contrast | Gained | Lost | Difference | 95% CI | McNemar p | Bound tasks | Never-bound | Placebo mismatches |
| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- |
| C-B (history search beyond the same summary) | 0 | 0 | +0.000 | [+0.000, +0.000] | 1.0000 | 6 | 4 | - |
| B-A (summary beyond the window) | 1 | 3 | -0.200 | [-0.600, +0.200] | 0.6250 | 7 | 3 | - |
| C-A (the whole memory package) | 1 | 3 | -0.200 | [-0.600, +0.200] | 0.6250 | 8 | 2 | - |

C-B is primary.  The interval is a task-level bootstrap percentile interval; with one run per arm it
does not include run-to-run provider variance.  Repeats are reported separately.

### Excluding the pilot tasks

| Contrast | Gained | Lost | Difference | 95% CI | McNemar p | Tasks |
| --- | ---: | ---: | ---: | --- | ---: | ---: |

## Per-task results

Tasks marked `*` are pilot tasks; they are excluded from the table above but shown here for completeness.
Each cell is `arm=value`.

| Task | Resolved | Dropped calls | Summary calls | Search calls | Max tokens | Repeat reads | Recovery re-reads | Violations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| django__django-11333* | a=PASS b=PASS c=PASS | a=0 b=0 c=32 | a=0 b=0 c=31 | a=0 b=0 c=1 | a=5985 b=6364 c=7999 | a=0 b=0 c=0 | a=0 b=0 c=0 | - |
| django__django-11532* | a=PASS b=fail c=fail | a=0 b=10 c=65 | a=0 b=10 c=64 | a=0 b=0 c=0 | a=7774 b=7983 c=8000 | a=0 b=1 c=1 | a=0 b=0 c=0 | - |
| django__django-13089* | a=PASS b=fail c=fail | a=25 b=0 c=0 | a=0 b=0 c=0 | a=0 b=0 c=0 | a=7938 b=4348 c=4940 | a=0 b=0 c=0 | a=0 b=0 c=0 | - |
| django__django-14855* | a=fail b=PASS c=PASS | a=360 b=0 c=0 | a=0 b=0 c=0 | a=0 b=0 c=0 | a=7995 b=4841 c=3563 | a=0 b=0 c=0 | a=0 b=0 c=0 | - |
| django__django-15315* | a=PASS b=PASS c=PASS | a=14 b=0 c=27 | a=0 b=0 c=25 | a=0 b=0 c=1 | a=7972 b=5544 c=8000 | a=0 b=0 c=1 | a=0 b=0 c=1 | - |
| django__django-15987* | a=PASS b=PASS c=PASS | a=0 b=0 c=0 | a=0 b=0 c=0 | a=0 b=0 c=0 | a=2881 b=6843 c=6424 | a=0 b=0 c=0 | a=0 b=0 c=0 | - |
| matplotlib__matplotlib-20826* | a=PASS b=fail c=fail | a=157 b=382 c=357 | a=0 b=382 c=357 | a=0 b=0 c=0 | a=8000 b=8000 c=7998 | a=13 b=7 c=1 | a=2 b=3 c=0 | - |
| pytest-dev__pytest-7982* | a=PASS b=PASS c=PASS | a=0 b=0 c=0 | a=0 b=0 c=0 | a=0 b=0 c=0 | a=4333 b=2907 c=4451 | a=0 b=0 c=0 | a=0 b=0 c=0 | - |
| sphinx-doc__sphinx-8721* | a=PASS b=PASS c=PASS | a=367 b=0 c=3 | a=0 b=0 c=3 | a=0 b=0 c=1 | a=7999 b=6232 c=7903 | a=0 b=0 c=1 | a=0 b=0 c=0 | - |
| sympy__sympy-13615* | a=PASS b=PASS c=PASS | a=53 b=12 c=33 | a=0 b=12 c=33 | a=0 b=0 c=0 | a=7993 b=7992 c=7987 | a=2 b=0 c=5 | a=0 b=0 c=0 | - |

All tasks are shown; no search-success case selection.  `Dropped` counts model calls whose view omitted
at least one message; `Summary` counts calls that carried the evidence summary.  `Max tokens` is the
estimated prompt total, not the provider count; the traces provide the per-call values.
Never-bound is exact for A/B (same prompt).  For contrasts involving C it is a soft check: C still carries
the memory_search tool description even when it makes no search call.
