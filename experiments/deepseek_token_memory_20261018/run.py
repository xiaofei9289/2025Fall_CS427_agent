"""Desktop Linux only: same token budget, truncate versus compress plus memory_search.

The DeepSeek API key is read from DEEPSEEK_API_KEY and never written to disk.
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


def bound_calls(path: Path) -> tuple[int, int]:
    bound = calls = 0
    for trajectory in path.rglob("*.traj.json"):
        for message in json.loads(trajectory.read_text()).get("messages", []):
            memory = message.get("extra", {}).get("memory") or {}
            if "estimated_full_tokens" not in memory:
                continue
            calls += 1
            if memory["estimated_sent_tokens"] < memory["estimated_full_tokens"]:
                bound += 1
    return bound, calls


def report(study: Path) -> None:
    from minisweagent.run.extra.audit import audit_run

    paths = {"off": study / "off", "on": study / "on"}
    manifests = {arm: json.loads((path / "run_manifest.json").read_text()) for arm, path in paths.items()}
    off_agent = manifests["off"]["config"]["agent"]
    on_agent = manifests["on"]["config"]["agent"]
    if off_agent.get("history_policy") != "truncate" or on_agent.get("history_policy") != "compress":
        raise ValueError("history_policy is not truncate versus compress")
    if off_agent.get("context_token_limit") != on_agent.get("context_token_limit"):
        raise ValueError("context_token_limit differs")
    if "memory_search" in off_agent.get("enabled_tools", []) or "memory_search" not in on_agent.get(
        "enabled_tools", []
    ):
        raise ValueError("memory_search must be enabled only on the compress arm")
    controls = copy.deepcopy(manifests)
    for manifest in controls.values():
        agent = manifest["config"]["agent"]
        agent.pop("history_policy", None)
        agent["enabled_tools"] = [name for name in agent.get("enabled_tools", []) if name != "memory_search"]
    for field in ("config", "instance_ids", "tasks", "workers", "source", "python", "dependencies"):
        if controls["off"][field] != controls["on"][field]:
            raise ValueError(f"Experiment controls differ: {field}")

    limit = off_agent["context_token_limit"]
    result = {
        "matched_controls": True,
        "source": manifests["off"]["source"],
        "arms": {},
        "treatment": f"shared {limit}-token prompt budget; compress arm keeps the task and can search dropped history",
    }
    lines = [
        "# DeepSeek token-budget memory comparison",
        "",
        f"Same model, tools except memory_search, source, tasks, budgets and workers. Prompt budget: {limit} estimated tokens.",
        "Off drops the oldest messages. On keeps the task, a short evidence note, and can call memory_search.",
        "",
    ]
    lines += [
        "| Arm | Resolved | Empty patches | Evaluation errors | Calls at budget | API calls | Cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm, path in paths.items():
        audit = audit_run(path, path / "evaluation")
        rows = audit["tasks"]
        bound, calls = bound_calls(path)
        metrics = {
            "resolved": sum(row["evaluation_status"] == "resolved" for row in rows),
            "empty_patches": sum(row["evaluation_status"] == "empty_patch" for row in rows),
            "evaluation_errors": sum(row["evaluation_status"] == "evaluation_error" for row in rows),
            "api_calls": sum(row["api_calls"] or 0 for row in rows),
            "cost_usd": sum(row["cost"] or 0 for row in rows),
            "calls_at_budget": bound,
            "model_calls_with_memory_stats": calls,
        }
        result["arms"][arm] = {"metrics": metrics, "tasks": rows, "run_id": manifests[arm]["run_id"]}
        lines.append(
            f"| {arm} | {metrics['resolved']}/{len(rows)} | {metrics['empty_patches']} | "
            f"{metrics['evaluation_errors']} | {bound}/{calls} | {metrics['api_calls']} | {metrics['cost_usd']:.6f} |"
        )
    lines += [
        "",
        "Empty patches count as unsolved. Calls at budget are model calls whose sent view was shorter than the full transcript.",
        "",
    ]
    (study / "comparison.json").write_text(json.dumps(result, indent=2))
    (study / "comparison.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["generation", "grading", "compare"])
    parser.add_argument("--arm", choices=["off", "on", "both"], default="both")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if platform.system() != "Linux":
        raise SystemExit("Run inside Linux on the desktop; execution on the editing Mac is disabled.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    task_ids = json.loads((study / "tasks.json").read_text())
    arms = ("off", "on") if args.arm == "both" else (args.arm,)

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
        (study / f"{name}_execution.json").write_text(
            json.dumps(
                {
                    "exit_code": process.returncode,
                    "wall_seconds": time.monotonic() - started,
                    "command": command,
                },
                indent=2,
            )
        )
        if process.returncode:
            print((study / f"{name}.log").read_text(encoding="utf-8", errors="replace")[-5000:], flush=True)
            raise RuntimeError(f"{name} failed; inspect {study / (name + '.log')}")
        print(f"Finished {name}", flush=True)

    if args.phase == "compare":
        report(study)
        return
    for arm in arms:
        if args.phase == "generation":
            execute(
                f"{arm}_generation",
                [
                    sys.executable,
                    "-m",
                    "minisweagent.run.extra.swebench",
                    "--subset",
                    "verified",
                    "--split",
                    "test",
                    "--instance-ids",
                    str(study / "tasks.json"),
                    "--config",
                    str(study / f"{arm}.yaml"),
                    "--output",
                    str(study / arm),
                    "--workers",
                    str(args.workers),
                ],
                root,
            )
            predictions = json.loads((study / arm / "preds.json").read_text())
            trajectories = list((study / arm).rglob("*.traj.json"))
            if set(predictions) != set(task_ids) or len(trajectories) != len(task_ids):
                raise RuntimeError(f"Incomplete generation for {arm}")
            for trajectory in trajectories:
                status = json.loads(trajectory.read_text())["info"]["exit_status"]
                if status not in {"Submitted", "RecoveredPatch", "LimitsExceeded"}:
                    raise RuntimeError(f"Generation error in {trajectory}: {status}")
            continue
        predictions = json.loads((study / arm / "preds.json").read_text())
        sanitized = {
            task: row | {"model_patch": row["model_patch"] if row["model_patch"].startswith("diff --git ") else ""}
            for task, row in predictions.items()
        }
        (study / arm / "preds.empty_on_errors.json").write_text(json.dumps(sanitized, indent=2))
        output = study / arm / "evaluation"
        output.mkdir(parents=True, exist_ok=True)
        parameters = {
            "dataset_name": "princeton-nlp/SWE-bench_Verified",
            "split": "test",
            "instance_ids": task_ids,
            "predictions_path": str(study / arm / "preds.empty_on_errors.json"),
            "max_workers": args.workers,
            "force_rebuild": False,
            "cache_level": "instance",
            "clean": False,
            "open_file_limit": 4096,
            "run_id": f"deepseek-token-memory-{arm}-20261018",
            "timeout": 300,
            "namespace": "swebench",
            "rewrite_reports": False,
            "modal": False,
        }
        (output / "parameters.json").write_text(json.dumps(parameters, indent=2))
        script = (
            "from pathlib import Path\nfrom swebench.harness.run_evaluation import main\n"
            f"report = main(**{parameters!r})\nPath(report).replace('grading_summary.json')\n"
        )
        execute(f"{arm}_grading", [sys.executable, "-c", script], output)
        summary = json.loads((output / "grading_summary.json").read_text())
        if summary["completed_instances"] + summary.get("empty_patch_instances", 0) != len(task_ids) or summary.get(
            "error_instances"
        ):
            raise SystemExit(f"Official grading contains errors or missing results: {summary['error_ids']}")


if __name__ == "__main__":
    main()
