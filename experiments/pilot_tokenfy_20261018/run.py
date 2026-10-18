"""Desktop Linux only: run and grade the three-model TokenFy five-task pilot.

Each arm runs the fixed five-task set with the same budget pilot limits
(50 steps, $1, 300 seconds) as pilot_20261017, differing only in the model.
API keys are read from TOKENFY_KEY_<ARM> by the caller's environment.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ARMS = ("claude_opus_5", "gpt_5_6_sol", "gemini_3_8_flash")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["generation", "grading"])
    parser.add_argument("--arms", nargs="*", default=list(ARMS))
    parser.add_argument("--tag", default="", help="Suffix appended to arm directories, logs, and run ids (e.g. _r2), keeping earlier runs intact")
    args = parser.parse_args()
    if platform.system() != "Linux":
        raise SystemExit("Run inside Linux on the desktop; execution on the editing Mac is disabled.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    task_ids = json.loads((study / "tasks.json").read_text())
    incomplete = []

    def execute(arm: str, name: str, command: list[str], cwd: Path) -> None:
        environment = os.environ | {
            "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root / "SWE-bench"))),
            "MSWEA_MODEL_API_KEY": os.environ[f"TOKENFY_KEY_{arm.upper()}"],
            "LITELLM_MODEL_REGISTRY_PATH": str(study / "tokenfy_model_registry.json"),
            "MSWEA_GLOBAL_COST_LIMIT": "10", "MSWEA_SILENT_STARTUP": "1",
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

    for arm in args.arms:
        directory = arm + args.tag
        if args.phase == "generation":
            execute(arm, directory, [
                sys.executable, "-m", "minisweagent.run.extra.swebench", "--subset", "verified", "--split", "test",
                "--instance-ids", str(study / "tasks.json"), "--config", str(study / f"{arm}.yaml"),
                "--output", str(study / directory), "--workers", "1",
            ], root)
            predictions = json.loads((study / directory / "preds.json").read_text())
            trajectories = list((study / directory).rglob("*.traj.json"))
            if set(predictions) != set(task_ids) or len(trajectories) != len(task_ids):
                raise RuntimeError(f"Incomplete generation in {arm}")
            for trajectory in trajectories:
                status = json.loads(trajectory.read_text())["info"]["exit_status"]
                if status not in {"Submitted", "RecoveredPatch", "LimitsExceeded"}:
                    raise RuntimeError(f"Generation error in {trajectory}: {status}")
        else:
            # The exporter records exception messages as model_patch; blank those
            # (they are never valid diffs) before official grading, keeping the
            # untouched originals as preds.json.
            predictions = json.loads((study / directory / "preds.json").read_text())
            sanitized = {
                task: row | {"model_patch": row["model_patch"] if row["model_patch"].startswith("diff --git ") else ""}
                for task, row in predictions.items()
            }
            (study / directory / "preds.empty_on_errors.json").write_text(json.dumps(sanitized, indent=2))
            output = study / directory / "evaluation"
            output.mkdir(parents=True, exist_ok=True)
            parameters = {
                "dataset_name": "princeton-nlp/SWE-bench_Verified", "split": "test", "instance_ids": task_ids,
                "predictions_path": str(study / directory / "preds.empty_on_errors.json"), "max_workers": 1,
                "force_rebuild": False, "cache_level": "instance", "clean": False, "open_file_limit": 4096,
                "run_id": f"pilot-tokenfy-20261018{args.tag}-{arm}",
                "timeout": 300, "namespace": "swebench",
                "rewrite_reports": False, "modal": False,
            }
            (output / "parameters.json").write_text(json.dumps(parameters, indent=2))
            script = (
                "from pathlib import Path\nfrom swebench.harness.run_evaluation import main\n"
                f"report = main(**{parameters!r})\nPath(report).replace('grading_summary.json')\n"
            )
            if not (output / "grading_summary.json").exists():
                execute(arm, f"{directory}_grading", [sys.executable, "-c", script], output)
            else:
                print(f"Preserving existing {directory} grading report", flush=True)
            summary = json.loads((output / "grading_summary.json").read_text())
            if summary["completed_instances"] + summary.get("empty_patch_instances", 0) != len(task_ids) or summary.get("error_instances"):
                incomplete.append(arm)
    if args.phase != "generation":
        if incomplete:
            raise SystemExit(f"Official grading contains errors or missing results: {', '.join(incomplete)}")
        print("All arms graded cleanly", flush=True)


if __name__ == "__main__":
    main()