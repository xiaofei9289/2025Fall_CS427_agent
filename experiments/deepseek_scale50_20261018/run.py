"""Desktop Linux only: generation and official grading of the 50-task DeepSeek scale run.

Same per-task budget as pilot_20261017 (50 steps, $1, 300 seconds) on the fixed
verified50 task set. The DeepSeek API key is read from DEEPSEEK_API_KEY in the
caller's environment and never written to disk.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["generation", "grading"])
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--tag", default="", help="Suffix appended to the output directory and run id, keeping earlier attempts intact")
    args = parser.parse_args()
    if platform.system() != "Linux":
        raise SystemExit("Run inside Linux on the desktop; execution on the editing Mac is disabled.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    task_ids = json.loads((study / "tasks.json").read_text())
    output_dir = study / ("baseline" + args.tag)

    def execute(name: str, command: list[str], cwd: Path) -> None:
        environment = os.environ | {
            "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root / "SWE-bench"))),
            "MSWEA_MODEL_API_KEY": os.environ["DEEPSEEK_API_KEY"],
            "MSWEA_GLOBAL_COST_LIMIT": os.environ.get("MSWEA_GLOBAL_COST_LIMIT", "10"),
            "MSWEA_SILENT_STARTUP": "1",
        }
        started = time.monotonic()
        print(f"Starting {name}", flush=True)
        with (study / f"{name}.log").open("w", encoding="utf-8") as log:
            process = subprocess.run(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT)
        (study / f"{name}_execution.json").write_text(json.dumps({
            "exit_code": process.returncode, "wall_seconds": time.monotonic() - started, "command": command,
        }, indent=2))
        if process.returncode:
            print((study / f"{name}.log").read_text(encoding="utf-8", errors="replace")[-5000:], flush=True)
            raise RuntimeError(f"{name} failed; inspect {study / (name + '.log')}")
        print(f"Finished {name}", flush=True)

    if args.phase == "generation":
        execute("generation", [
            sys.executable, "-m", "minisweagent.run.extra.swebench", "--subset", "verified", "--split", "test",
            "--instance-ids", str(study / "tasks.json"), "--config", str(study / "baseline.yaml"),
            "--output", str(output_dir), "--workers", str(args.workers),
        ], root)
        predictions = json.loads((output_dir / "preds.json").read_text())
        trajectories = list(output_dir.rglob("*.traj.json"))
        if set(predictions) != set(task_ids) or len(trajectories) != len(task_ids):
            raise RuntimeError("Incomplete generation")
        for trajectory in trajectories:
            status = json.loads(trajectory.read_text())["info"]["exit_status"]
            if status not in {"Submitted", "RecoveredPatch", "LimitsExceeded"}:
                raise RuntimeError(f"Generation error in {trajectory}: {status}")
    else:
        predictions = json.loads((output_dir / "preds.json").read_text())
        sanitized = {
            task: row | {"model_patch": row["model_patch"] if row["model_patch"].startswith("diff --git ") else ""}
            for task, row in predictions.items()
        }
        (output_dir / "preds.empty_on_errors.json").write_text(json.dumps(sanitized, indent=2))
        output = output_dir / "evaluation"
        output.mkdir(parents=True, exist_ok=True)
        parameters = {
            "dataset_name": "princeton-nlp/SWE-bench_Verified", "split": "test", "instance_ids": task_ids,
            "predictions_path": str(output_dir / "preds.empty_on_errors.json"), "max_workers": args.workers,
            "force_rebuild": False, "cache_level": "instance", "clean": False, "open_file_limit": 4096,
            "run_id": f"deepseek-scale50-20261018{args.tag}",
            "timeout": 300, "namespace": "swebench",
            "rewrite_reports": False, "modal": False,
        }
        (output / "parameters.json").write_text(json.dumps(parameters, indent=2))
        script = (
            "from pathlib import Path\nfrom swebench.harness.run_evaluation import main\n"
            f"report = main(**{parameters!r})\nPath(report).replace('grading_summary.json')\n"
        )
        execute("grading", [sys.executable, "-c", script], output)
        summary = json.loads((output / "grading_summary.json").read_text())
        if summary["completed_instances"] + summary.get("empty_patch_instances", 0) != len(task_ids) or summary.get("error_instances"):
            raise SystemExit(f"Official grading contains errors or missing results: {summary['error_ids']}")


if __name__ == "__main__":
    main()