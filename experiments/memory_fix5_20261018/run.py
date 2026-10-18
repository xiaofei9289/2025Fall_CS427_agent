"""Generate fresh five-task memory controls and run the bundled official harness."""

import argparse
import copy
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


def report(study: Path) -> None:
    from minisweagent.run.extra.audit import audit_run

    manifests = {arm: json.loads((study / arm / "run_manifest.json").read_text()) for arm in ("off", "on")}
    controls = copy.deepcopy(manifests)
    for manifest in controls.values():
        manifest["config"]["agent"].pop("enable_memory")
    for field in ("config", "instance_ids", "tasks", "workers", "source", "python", "dependencies"):
        if controls["off"][field] != controls["on"][field]:
            raise ValueError(f"Experiment controls differ: {field}")

    result = {"matched_controls": True, "treatment": "history compression only; memory_search disabled in both arms",
              "source": manifests["off"]["source"], "arms": {}}
    lines = ["# Repaired memory: five-task official comparison", "",
             "Same model, tools, source, task order, response handling and budgets; only enable_memory differs.", "",
             "| Arm | Resolved | Empty patches | Evaluation errors | API calls | Cost (USD) |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for arm in ("off", "on"):
        audit = audit_run(study / arm, study / arm / "evaluation")
        rows = audit["tasks"]
        metrics = {
            "resolved": sum(row["evaluation_status"] == "resolved" for row in rows),
            "empty_patches": sum(row["evaluation_status"] == "empty_patch" for row in rows),
            "evaluation_errors": sum(row["evaluation_status"] == "evaluation_error" for row in rows),
            "api_calls": sum(row["api_calls"] or 0 for row in rows),
            "cost_usd": sum(row["cost"] or 0 for row in rows),
        }
        result["arms"][arm] = {"metrics": metrics, "tasks": rows, "run_id": manifests[arm]["run_id"]}
        lines.append(f"| {arm} | {metrics['resolved']}/{len(rows)} | {metrics['empty_patches']} | "
                     f"{metrics['evaluation_errors']} | {metrics['api_calls']} | {metrics['cost_usd']:.6f} |")
    lines += ["", "This is a single five-task run. Empty patches count as unsolved; infrastructure errors leave grading incomplete.", ""]
    (study / "comparison.json").write_text(json.dumps(result, indent=2))
    (study / "comparison.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("generation", "grading"))
    args = parser.parse_args()
    if platform.system() != "Linux":
        raise SystemExit("Run inside Linux on the desktop; the editing Mac is not an evaluation host.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    task_ids = json.loads((study / "tasks.json").read_text())
    env = os.environ | {"PYTHONPATH": os.pathsep.join((str(root / "src"), str(root / "SWE-bench"))),
                        "MSWEA_GLOBAL_COST_LIMIT": "5", "MSWEA_SILENT_STARTUP": "1"}

    def execute(name: str, command: list[str], cwd: Path) -> None:
        print(f"Starting {name}", flush=True)
        started = time.monotonic()
        with (study / f"{name}.log").open("w") as log:
            process = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
        (study / f"{name}_execution.json").write_text(json.dumps({
            "exit_code": process.returncode, "wall_seconds": time.monotonic() - started, "command": command,
        }, indent=2))
        if process.returncode:
            raise RuntimeError(f"{name} failed; inspect {study / (name + '.log')}")
        print(f"Finished {name}", flush=True)

    incomplete = []
    for arm in ("off", "on"):
        if args.phase == "generation":
            execute(f"{arm}_generation", [sys.executable, "-m", "minisweagent.run.extra.swebench",
                    "--subset", "verified", "--split", "test", "--instance-ids", str(study / "tasks.json"),
                    "--config", str(study / f"{arm}.yaml"), "--output", str(study / arm), "--workers", "1"], root)
            predictions = json.loads((study / arm / "preds.json").read_text())
            trajectories = list((study / arm).rglob("*.traj.json"))
            if set(predictions) != set(task_ids) or len(trajectories) != len(task_ids):
                raise RuntimeError(f"Incomplete generation in {arm}")
            for path in trajectories:
                status = json.loads(path.read_text())["info"]["exit_status"]
                if status not in {"Submitted", "RecoveredPatch", "LimitsExceeded", "ModelResponseError"}:
                    raise RuntimeError(f"Generation error in {path}: {status}; grading was not started")
            continue
        output = study / arm / "evaluation"
        output.mkdir(parents=True, exist_ok=True)
        parameters = {
            "dataset_name": "princeton-nlp/SWE-bench_Verified", "split": "test", "instance_ids": task_ids,
            "predictions_path": str(study / arm / "preds.json"), "max_workers": 1, "force_rebuild": False,
            "cache_level": "instance", "clean": False, "open_file_limit": 4096,
            "run_id": f"memory-fix5-20261018-{arm}", "timeout": 300, "namespace": "swebench",
            "rewrite_reports": False, "modal": False,
        }
        (output / "parameters.json").write_text(json.dumps(parameters, indent=2))
        if not (output / "grading_summary.json").exists():
            script = ("from pathlib import Path\nfrom swebench.harness.run_evaluation import main\n"
                      f"report = main(**{parameters!r})\nPath(report).replace('grading_summary.json')\n")
            execute(f"{arm}_grading", [sys.executable, "-c", script], output)
        summary = json.loads((output / "grading_summary.json").read_text())
        if summary["completed_instances"] + summary.get("empty_patch_instances", 0) != len(task_ids) or summary.get("error_instances"):
            incomplete.append(arm)
    if args.phase == "grading":
        report(study)
        if incomplete:
            raise SystemExit(f"Official grading is incomplete: {', '.join(incomplete)}")


if __name__ == "__main__":
    main()
