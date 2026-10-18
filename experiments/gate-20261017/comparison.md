# Baseline / retrieval controlled pilot

A small single-run pilot. Availability of retrieval tools is the treatment; tool requests do not prove useful retrieval. Sequential provider caching may affect cost. No population-level or causal improvement claim.

Empty patches count as unsolved tasks in the resolve rate. Infrastructure errors and missing grades leave it pending.

| Arm | Completed official tests | Empty patches | Resolved | Rate | API calls | Cost (USD) | Tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 5/5 | 0 | 4 | 80% | 76 | 0.011305 | 574377 |
| retrieval | 4/5 | 1 | 3 | 60% | 106 | 0.021072 | 1351588 |

| Instance | Baseline | Retrieval |
| --- | --- | --- |
| django__django-11333 | resolved | resolved |
| django__django-11532 | unresolved | unresolved |
| django__django-14855 | resolved | resolved |
| django__django-15315 | resolved | resolved |
| matplotlib__matplotlib-20826 | resolved | empty_patch |

Integrity issues: `{"baseline": {}, "retrieval": {}}`

Run IDs and the frozen source fingerprint are in comparison.json. Per-instance patches, trajectories, and official test logs remain in each arm.
