"""Desktop Linux only: run and grade the previously authorized five-task budget pilot."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["generation", "grading", "normalized-grading"])
    args = parser.parse_args()
    if platform.system() != "Linux":
        raise SystemExit("Run inside Linux on the desktop; execution on the editing Mac is disabled.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    task_ids = json.loads((study / "tasks.json").read_text())
    environment = os.environ | {
        "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root / "SWE-bench"))),
        "MSWEA_GLOBAL_COST_LIMIT": "5", "MSWEA_SILENT_STARTUP": "1",
    }
    if args.phase == "normalized-grading":
        original_study = study
        study = study / "transport_normalized"
        study.mkdir(exist_ok=True)
        provenance = {"transform": "Append one LF to each nonempty patch lacking a terminal LF; no other patch changes",
                      "source": str(original_study), "changed_ids": {}}
        for arm in ("baseline", "finalization"):
            source, target = original_study / arm, study / arm
            target.mkdir(exist_ok=True)
            for name in ("run_manifest.json", "source.zip"):
                shutil.copy2(source / name, target / name)
            for path in source.rglob("*.traj.json"):
                destination = target / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
            predictions = json.loads((source / "preds.json").read_text())
            changed = []
            for task_id, row in predictions.items():
                if row["model_patch"] and not row["model_patch"].endswith("\n"):
                    row["model_patch"] += "\n"
                    changed.append(task_id)
            (target / "preds.json").write_text(json.dumps(predictions, indent=2))
            provenance["changed_ids"][arm] = changed
        (study / "normalization.json").write_text(json.dumps(provenance, indent=2))

    incomplete = []

    def execute(name: str, command: list[str], cwd: Path) -> None:
        started = time.monotonic()
        print(f"Starting {name}", flush=True)
        with (study / f"{name}.log").open("w") as log:
            process = subprocess.run(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT)
        (study / f"{name}_execution.json").write_text(json.dumps({
            "exit_code": process.returncode, "wall_seconds": time.monotonic() - started,
            "command": command,
        }, indent=2))
        if process.returncode:
            raise RuntimeError(f"{name} failed; inspect {study / (name + '.log')}")
        print(f"Finished {name}", flush=True)

    for arm in ("baseline", "finalization"):
        if args.phase == "generation":
            execute(arm, [
                sys.executable, "-m", "minisweagent.run.extra.swebench", "--subset", "verified", "--split", "test",
                "--instance-ids", str(study / "tasks.json"), "--config", str(study / f"{arm}.yaml"),
                "--output", str(study / arm), "--workers", "1",
            ], root)
            predictions = json.loads((study / arm / "preds.json").read_text())
            trajectories = list((study / arm).rglob("*.traj.json"))
            if set(predictions) != set(task_ids) or len(trajectories) != len(task_ids):
                raise RuntimeError(f"Incomplete generation in {arm}")
            for trajectory in trajectories:
                status = json.loads(trajectory.read_text())["info"]["exit_status"]
                if status not in {"Submitted", "RecoveredPatch", "LimitsExceeded"}:
                    raise RuntimeError(f"Generation error in {trajectory}: {status}")
        else:
            output = study / arm / "evaluation"
            output.mkdir(parents=True, exist_ok=True)
            parameters = {
                "dataset_name": "princeton-nlp/SWE-bench_Verified", "split": "test", "instance_ids": task_ids,
                "predictions_path": str(study / arm / "preds.json"), "max_workers": 1,
                "force_rebuild": False, "cache_level": "instance", "clean": False, "open_file_limit": 4096,
                "run_id": f"budget-20261017-{'lf-' if args.phase == 'normalized-grading' else ''}{arm}",
                "timeout": 300, "namespace": "swebench",
                "rewrite_reports": False, "modal": False,
            }
            (output / "parameters.json").write_text(json.dumps(parameters, indent=2))
            script = (
                "from pathlib import Path\nfrom swebench.harness.run_evaluation import main\n"
                f"report = main(**{parameters!r})\nPath(report).replace('grading_summary.json')\n"
            )
            if not (output / "grading_summary.json").exists():
                execute(f"{arm}_grading", [sys.executable, "-c", script], output)
            else:
                print(f"Preserving existing {arm} grading report", flush=True)
            summary = json.loads((output / "grading_summary.json").read_text())
            if summary["completed_instances"] + summary.get("empty_patch_instances", 0) != len(task_ids) or summary.get("error_instances"):
                incomplete.append(arm)
    if args.phase != "generation":
        from minisweagent.run.extra.compare import main as compare_main

        compare_main(study / "baseline", study / "finalization", study, treatment="finalization")
        if incomplete:
            raise SystemExit(f"Official grading contains errors or missing results: {', '.join(incomplete)}")


if __name__ == "__main__":
    main()
