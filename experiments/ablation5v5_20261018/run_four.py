"""Run the four-arm retrieval/tool ablation (one round) inside the Linux container."""

import argparse
import subprocess
import sys
from pathlib import Path

STUDY = Path(__file__).resolve().parent
ARMS = {
    "baseline_tool": "configs/baseline.yaml",
    "brief_tool": "configs/brief_only.yaml",
    "retrieval_tool": "configs/retrieval.yaml",
    "gate_tool": "configs/retrieval_gate.yaml",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=("all", *ARMS), default="all")
    parser.add_argument("--tasks", default="tasks10.json")
    parser.add_argument("--suffix", default="")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    selected = list(ARMS) if args.arm == "all" else [args.arm]
    for arm in selected:
        tag = arm + args.suffix
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
                ARMS[arm],
                "--tag",
                tag,
                "--tasks",
                args.tasks,
                "--workers",
                str(args.workers),
            ]
            result = subprocess.run(command, cwd=STUDY)
            if result.returncode:
                raise SystemExit(f"ABLATION_FAILED at {tag} {phase}")
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    main()
