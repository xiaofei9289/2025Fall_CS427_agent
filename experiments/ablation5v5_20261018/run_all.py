"""Drive the full 5v5 ablation sequentially (baseline vs retrieval x rounds 1..5).

Runs inside one Linux container on the desktop; skips rounds whose grading
summary already exists, so a failed driver can simply be restarted. Prints
ALL_DONE on success and ABLATION_FAILED otherwise.
"""

import subprocess
import sys
from pathlib import Path

study = Path(__file__).resolve().parent
for arm in ("baseline", "retrieval"):
    for i in range(1, 6):
        tag = f"{arm}_r{i}"
        if (study / tag / "evaluation" / "grading_summary.json").is_file():
            print(f"=== SKIP {tag} (already graded) ===", flush=True)
            continue
        print(f"=== ROUND {tag} ===", flush=True)
        for phase in ("generation", "grading"):
            result = subprocess.run(
                [sys.executable, str(study / "run.py"), phase, "--config", f"{arm}.yaml",
                 "--tag", tag, "--workers", "4"], cwd=study)
            if result.returncode:
                print(f"ABLATION_FAILED at {tag} {phase}", flush=True)
                raise SystemExit(1)
print("ALL_DONE", flush=True)