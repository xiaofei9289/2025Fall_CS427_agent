"""Run the four-arm retrieval/tool ablation (one round) inside the Linux container."""

import subprocess
import sys
from pathlib import Path

STUDY = Path(__file__).resolve().parent
ARMS = {
    "baseline_tool": "configs4/baseline.yaml",
    "brief_tool": "configs4/brief_only.yaml",
    "retrieval_tool": "configs4/retrieval.yaml",
    "gate_tool": "configs4/retrieval_gate.yaml",
}


def main() -> None:
    for tag, config in ARMS.items():
        if (STUDY / tag / "evaluation" / "grading_summary.json").is_file():
            print(f"=== SKIP {tag} (already graded) ===", flush=True)
            continue
        print(f"=== ARM {tag} ===", flush=True)
        for phase in ("generation", "grading"):
            command = [
                sys.executable,
                str(STUDY / "run.py"),
                phase,
                "--config",
                config,
                "--tag",
                tag,
                "--tasks",
                "tasks10.json",
                "--workers",
                "2",
            ]
            result = subprocess.run(command, cwd=STUDY)
            if result.returncode:
                raise SystemExit(f"ABLATION_FAILED at {tag} {phase}")
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    main()
