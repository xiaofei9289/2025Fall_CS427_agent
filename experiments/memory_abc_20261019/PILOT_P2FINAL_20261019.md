# A/B/C p2final pilot — 2026-10-19

Status: **valid run, but the C treatment was mostly inactive; do not treat C−B as a retrieval result.**

- Source digest: `d31ee30917a7` (main `581c51c`)
- Tags: `a_pilot_p2final`, `b_pilot_p2final`, `c_pilot_p2final`
- 10 pilot tasks, 2 workers, all arms generation + official grading
- Report: [comparison_pilot_p2final.md](comparison_pilot_p2final.md) / `.json`

## Results

| Arm | Policy | Resolved | Empty | Cost | Calls | Summary calls | Search calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A | window | **9/10** | 1 | $0.3046 | 1156 | 0 | 0 |
| B | summary | 7/10 | 1 | $0.5413 | 538 | 404 | 0 |
| C | summary_search | 7/10 | 0 | $0.6526 | 635 | 513 | **3** |

`valid=True`. C made only **3** `memory_search` calls; 7 tasks had none.

## Contrasts

| Contrast | Difference | 95% CI | McNemar p |
| --- | ---: | --- | ---: |
| C−B (retrieval beyond summary) | **0.000** | [0.000, 0.000] | 1.000 |
| B−A (summary beyond window) | **−0.200** | [−0.600, +0.200] | 0.625 |
| C−A (whole memory package) | **−0.200** | [−0.600, +0.200] | 0.625 |

## Findings

1. **C did not exercise retrieval in most tasks.** The pre-write/pre-submit gate
   only blocked `replace`/`write_file` and bash submissions containing
   `COMPLETE_TASK`; models that edited via other bash commands, recovered a
   patch at the step limit, or never attempted a write bypassed it.
2. **C ≈ B.** C−B is exactly zero; C's 3 searches did not change any task
   outcome. C also carries the tool description/instruction cost and 30
   retrieval tokens, so it is not a clean win.
3. **A (window) was best in this run** at 9/10; B/C both 7/10. B−A and C−A are
   −0.2 with wide intervals; one run cannot establish a memory effect, but this
   is not evidence for summary/search.
4. `matplotlib-20826` made 0 search in C and was `LimitsExceeded` in B/C; A
   passed it. The 400-step cap was kept for all arms.

## Conclusion

This run is valid but **does not answer the retrieval question**. Before another
A/B/C comparison, the C gate must force retrieval in every task that edits or
submits, including bash edits, or the analysis must restrict the contrast to
tasks with `search_calls > 0`. The next run should also be treated as a new
round; do not pool it with earlier p2c–p2h smokes.
