# DeepSeek 50-task memory comparison

Same model, tools, source, task order and budgets; only enable_memory (40-message budget) differs.
Workers: baseline 4, on 2.

| Arm | Resolved | Empty patches | Evaluation errors | API calls | Cost (USD) |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline | 42/50 | 0 | 0 | 1203 | 0.287565 |
| on | 40/50 | 0 | 0 | 1734 | 2.024742 |

Empty patches count as unsolved; infrastructure errors leave grading incomplete.
