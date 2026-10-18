"""Desktop Linux only: memory-on arm of the 50-task DeepSeek scale comparison.

The memory-off baseline is the sibling experiment deepseek_scale50_20261018.
The DeepSeek API key is read from DEEPSEEK_API_KEY in the caller's environment
and never written to disk.
"""

import argparse
import copy
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

BASELINE = Path(__file__).resolve().parent.parent / "deepseek_scale50_20261018" / "baseline_r2"


def report(study: Path) -> None:
    from minisweagent.run.extra.audit import audit_run

    paths = {"baseline": BASELINE, "on": study / "on"}
    manifests = {arm: json.loads((path / "run_manifest.json").read_text()) for arm, path in paths.items()}
    controls = copy.deepcopy(manifests)
    for manifest in controls.values():
        manifest["config"]["agent"].pop("enable_memory")
        manifest["config"]["agent"].pop("memory_max_messages", None)
    for field in ("config", "instance_ids", "tasks", "source", "python", "dependencies"):
        if controls["baseline"][field] != controls["on"][field]:
            raise ValueError(f"Experiment controls differ: {field}")

    result = {"matched_controls": True,
              "treatment": "history compression only; memory_search disabled in both arms",
              "source": manifests["baseline"]["source"], "arms": {}}
    lines = ["# DeepSeek 50-task memory comparison", "",
             "Same model, tools, source, task order and budgets; only enable_memory (40-message budget) differs.",
             f"Workers: baseline {manifests['baseline']['workers']}, on {manifests['on']['workers']}.", "",
             "| Arm | Resolved | Empty patches | Evaluation errors | API calls | Cost (USD) |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for arm, path in paths.items():
        audit = audit_run(path, path / "evaluation")
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
    lines += ["", "Empty patches count as unsolved; infrastructure errors leave grading incomplete.", ""]
    (study / "comparison.json").write_text(json.dumps(result, indent=2))
    (study / "comparison.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["generation", "grading", "compare"])
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if platform.system() != "Linux":
        raise SystemExit("Run inside Linux on the desktop; execution on the editing Mac is disabled.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    task_ids = json.loads((study / "tasks.json").read_text())

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
            "--instance-ids", str(study / "tasks.json"), "--config", str(study / "on.yaml"),
            "--output", str(study / "on"), "--workers", str(args.workers),
        ], root)
        predictions = json.loads((study / "on" / "preds.json").read_text())
        trajectories = list((study / "on").rglob("*.traj.json"))
        if set(predictions) != set(task_ids) or len(trajectories) != len(task_ids):
            raise RuntimeError("Incomplete generation")
        for trajectory in trajectories:
            status = json.loads(trajectory.read_text())["info"]["exit_status"]
            if status not in {"Submitted", "RecoveredPatch", "LimitsExceeded"}:
                raise RuntimeError(f"Generation error in {trajectory}: {status}")
    elif args.phase == "grading":
        predictions = json.loads((study / "on" / "preds.json").read_text())
        sanitized = {
            task: row | {"model_patch": row["model_patch"] if row["model_patch"].startswith("diff --git ") else ""}
            for task, row in predictions.items()
        }
        (study / "on" / "preds.empty_on_errors.json").write_text(json.dumps(sanitized, indent=2))
        output = study / "on" / "evaluation"
        output.mkdir(parents=True, exist_ok=True)
        parameters = {
            "dataset_name": "princeton-nlp/SWE-bench_Verified", "split": "test", "instance_ids": task_ids,
            "predictions_path": str(study / "on" / "preds.empty_on_errors.json"), "max_workers": args.workers,
            "force_rebuild": False, "cache_level": "instance", "clean": False, "open_file_limit": 4096,
            "run_id": "deepseek-scale50-memory-on-20261018",
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
    else:
        report(study)


if __name__ == "__main__":
    main()
