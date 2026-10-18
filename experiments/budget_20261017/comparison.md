# Baseline / finalization controlled pilot

A small single-run pilot. Finalization reserves are the treatment; both arms keep the same tools and hard budgets. Sequential provider caching may affect cost. No population-level or causal improvement claim.

Empty patches count as unsolved tasks in the resolve rate. Infrastructure errors and missing grades leave it pending.

| Arm | Completed official tests | Empty patches | Resolved | Rate | API calls | Cost (USD) | Tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 4/5 | 0 | 3 | Pending / incomplete | 104 | 0.023544 | 1325203 |
| finalization | 5/5 | 0 | 5 | 100% | 109 | 0.020375 | 1321371 |

| Instance | Baseline | Finalization |
| --- | --- | --- |
| django__django-11333 | resolved | resolved |
| django__django-11532 | evaluation_error | resolved |
| django__django-14855 | resolved | resolved |
| django__django-15315 | resolved | resolved |
| matplotlib__matplotlib-20826 | unresolved | resolved |

Integrity issues: `{"baseline": {}, "finalization": {}}`

Run IDs and the frozen source fingerprint are in comparison.json. Per-instance patches, trajectories, and official test logs remain in each arm.
