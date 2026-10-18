# Retrieval experiment configs

All configs use `deepseek/deepseek-chat`, 400 steps, $10 per task, temperature 0, and the same
50-task list. They differ only in the retrieval treatment described below.

| Config | `repo_brief` | `retrieval_policy` | Retrieval tools | Intended comparison |
| --- | --- | --- | --- | --- |
| `baseline.yaml` | no | default (`gate`, but no gate tools are enabled) | `find_definition` only | control |
| `brief_only.yaml` | yes | `brief` | `find_definition` only | effect of the deterministic brief |
| `retrieval.yaml` | yes | `brief` | `code_search`, `repo_map`, `code_context`, `find_references` | brief + tools + retrieval-to-action prompt |
| `retrieval_gate.yaml` | no | `gate` | `code_search`, `repo_map` | legacy forced-first-search arm; reproduces `gate-20261017` |

The archived `pilot_20261017` and `gate-20261017` runs used the old `retrieval.yaml`, which was a
gate configuration. They remain historical evidence; do not mix them with the new brief arm.

`retrieval.yaml` is not a clean "tool availability" contrast: it also injects the brief and changes
the prompt to ask for a hypothesis, a minimal edit, and a focused test. Use `brief_only.yaml` to
separate the pre-task context from the tools. For a 2×2 estimate, compare:

- `baseline.yaml` vs `brief_only.yaml` (brief effect at fixed tools);
- `brief_only.yaml` vs `retrieval.yaml` (tools/action effect at fixed brief);
- `retrieval.yaml` vs `retrieval_gate.yaml` (gate effect at roughly fixed tools).

Run one round only after freezing source and config; use a new output directory per round. A single
50-task round has substantial variance: three same-config baseline runs were 37/40/42. Report paired
confidence intervals and do not treat a 1–2 task difference as causal.
