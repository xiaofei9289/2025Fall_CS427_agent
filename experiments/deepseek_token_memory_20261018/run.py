"""Desktop Linux only: same token budget, truncate versus compress plus memory_search.

The DeepSeek API key is read from DEEPSEEK_API_KEY and never written to disk.
"""

import argparse
import copy
import json
import math
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path


def task_memory_stats(path: Path) -> dict[str, dict[str, int]]:
    """Per task: model calls, calls whose sent view was shortened, calls carrying a summary."""
    stats: dict[str, dict[str, int]] = {}
    for trajectory in path.rglob("*.traj.json"):
        data = json.loads(trajectory.read_text())
        task = data.get("instance_id") or trajectory.parent.name
        entry = stats.setdefault(task, {"calls": 0, "bound": 0, "summary": 0, "max_full": 0})
        for message in data.get("messages", []):
            memory = message.get("extra", {}).get("memory") or {}
            if "estimated_full_tokens" not in memory:
                continue
            entry["calls"] += 1
            entry["bound"] += int(memory["estimated_sent_tokens"] < memory["estimated_full_tokens"])
            entry["summary"] += int(bool(memory.get("evidence")))
            entry["max_full"] = max(entry["max_full"], memory["estimated_full_tokens"])
    return stats


def search_usage(path: Path) -> dict[str, int]:
    """Count memory_search actions and non-empty results; a tool that is never called cannot explain a gain."""
    calls = hits = 0
    for trajectory in path.rglob("*.traj.json"):
        messages = json.loads(trajectory.read_text()).get("messages", [])
        for index, message in enumerate(messages):
            if message.get("role") != "assistant":
                continue
            for block in re.findall(r"```tool\n(.*?)\n```", message.get("content") or "", re.S):
                try:
                    payload = json.loads(block)
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict) or payload.get("name") != "memory_search":
                    continue
                calls += 1
                observation = messages[index + 1].get("content", "") if index + 1 < len(messages) else ""
                hits += int("No matches" not in str(observation))
    return {"calls": calls, "hits": hits}


def estimator_calibration(path: Path) -> dict[str, float]:
    """Compare the shared character estimate with the provider's prompt token count.

    The 8000 cap is specified in estimated tokens; this ratio says how far that is
    from the provider's own count (code and Chinese both tokenize worse than chars/4).
    """
    ratios = []
    for trajectory in path.rglob("*.traj.json"):
        for message in json.loads(trajectory.read_text()).get("messages", []):
            memory = message.get("extra", {}).get("memory") or {}
            usage = message.get("extra", {}).get("response", {}).get("usage") or {}
            estimated = memory.get("estimated_sent_tokens")
            actual = usage.get("prompt_tokens")
            if estimated and actual:
                ratios.append(actual / estimated)
    if not ratios:
        return {"samples": 0, "median_ratio": None}
    ratios.sort()
    return {"samples": len(ratios), "median_ratio": round(ratios[len(ratios) // 2], 3)}


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value for b discordant pairs in one direction and c in the other."""
    total = b + c
    if not total:
        return 1.0
    tail = sum(math.comb(total, i) for i in range(min(b, c) + 1)) / 2**total
    return min(1.0, 2 * tail)


def paired_analysis(
    tasks: list[str],
    off_rows: dict[str, dict],
    arm_rows: dict[str, dict],
    off_memory: dict[str, dict],
    arm_memory: dict[str, dict],
) -> dict:
    """Outcome switches plus the never-bound subset, which must not differ under a shared budget."""
    gained = lost = 0
    unbound = 0
    mismatches = []
    for task in tasks:
        off_resolved = off_rows[task]["evaluation_status"] == "resolved"
        arm_resolved = arm_rows[task]["evaluation_status"] == "resolved"
        gained += int(arm_resolved and not off_resolved)
        lost += int(off_resolved and not arm_resolved)
        never_bound = off_memory.get(task, {}).get("bound", 0) == 0 and arm_memory.get(task, {}).get("bound", 0) == 0
        if never_bound:
            unbound += 1
            if off_resolved != arm_resolved:
                mismatches.append(task)
    return {
        "gained": gained,
        "lost": lost,
        "mcnemar_exact_p": round(mcnemar_exact(gained, lost), 4),
        "never_bound_tasks": unbound,
        "never_bound_mismatches": mismatches,
    }


def report(study: Path) -> None:
    from minisweagent.run.extra.audit import audit_run

    found = [path.name for path in study.iterdir() if (path / "run_manifest.json").is_file()]
    if not {"off", "on"} <= set(found):
        raise ValueError("the off and on arms must be generated before comparing")
    arms = ["off", "on"] + sorted(name for name in found if name not in {"off", "on"})
    paths = {arm: study / arm for arm in arms}
    manifests = {arm: json.loads((paths[arm] / "run_manifest.json").read_text()) for arm in arms}
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
    for arm in arms:
        for field in ("config", "instance_ids", "tasks", "workers", "source", "python", "dependencies"):
            if controls["off"][field] != controls[arm][field]:
                raise ValueError(f"Experiment controls differ for arm {arm}: {field}")

    audits = {arm: audit_run(paths[arm], paths[arm] / "evaluation") for arm in arms}
    rows = {arm: {row["instance_id"]: row for row in audits[arm]["tasks"]} for arm in arms}
    memory = {arm: task_memory_stats(paths[arm]) for arm in arms}
    search = {arm: search_usage(paths[arm]) for arm in arms}
    calibration = {arm: estimator_calibration(paths[arm]) for arm in arms}
    tasks = sorted(set(rows["off"]) | set(rows["on"]))

    limit = off_agent["context_token_limit"]
    result = {
        "matched_controls": True,
        "source": manifests["off"]["source"],
        "arms": {},
        "paired": {},
        "estimator": calibration,
        "treatment": (
            f"shared {limit}-token prompt budget and task pinning; the compress arm keeps an evidence summary "
            "and can retrieve the omitted text"
        ),
    }
    lines = [
        "# DeepSeek token-budget memory comparison",
        "",
        f"Same model, tools except memory_search, source, tasks, budgets and workers. Prompt budget: {limit} estimated tokens.",
        "Both arms keep the system prompt and the task. Off drops the oldest remaining messages; on keeps a short",
        "evidence note and can call memory_search to reopen what was dropped.",
        "",
        "| Arm | Resolved | Empty patches | Eval errors | Calls at budget | Calls with summary | memory_search calls (hits) | API calls | Cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm in arms:
        task_rows = audits[arm]["tasks"]
        stats = memory[arm].values()
        metrics = {
            "resolved": sum(row["evaluation_status"] == "resolved" for row in task_rows),
            "empty_patches": sum(row["evaluation_status"] == "empty_patch" for row in task_rows),
            "evaluation_errors": sum(row["evaluation_status"] == "evaluation_error" for row in task_rows),
            "api_calls": sum(row["api_calls"] or 0 for row in task_rows),
            "cost_usd": sum(row["cost"] or 0 for row in task_rows),
            "calls_at_budget": sum(entry["bound"] for entry in stats),
            "calls_with_summary": sum(entry["summary"] for entry in memory[arm].values()),
            "tasks_with_summary": sum(entry["summary"] > 0 for entry in memory[arm].values()),
            "model_calls_with_memory_stats": sum(entry["calls"] for entry in stats),
            "memory_search_calls": search[arm]["calls"],
            "memory_search_hits": search[arm]["hits"],
        }
        result["arms"][arm] = {"metrics": metrics, "tasks": task_rows, "run_id": manifests[arm]["run_id"]}
        lines.append(
            f"| {arm} | {metrics['resolved']}/{len(task_rows)} | {metrics['empty_patches']} | "
            f"{metrics['evaluation_errors']} | {metrics['calls_at_budget']}/{metrics['model_calls_with_memory_stats']} | "
            f"{metrics['calls_with_summary']} ({metrics['tasks_with_summary']} tasks) | "
            f"{metrics['memory_search_calls']} ({metrics['memory_search_hits']}) | "
            f"{metrics['api_calls']} | {metrics['cost_usd']:.6f} |"
        )

    lines += [
        "",
        "Empty patches count as unsolved. Calls at budget are model calls whose sent view was shorter than the full transcript.",
        "Calls with summary are model calls that carried a [memory] note.",
        "",
        "| Pair | Gained (fail to pass) | Lost (pass to fail) | McNemar exact p | Never-bound tasks | Mismatches there |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for arm in arms:
        if arm == "off":
            continue
        paired = paired_analysis(tasks, rows["off"], rows[arm], memory["off"], memory[arm])
        result["paired"][arm] = paired
        lines.append(
            f"| off to {arm} | {paired['gained']} | {paired['lost']} | {paired['mcnemar_exact_p']} | "
            f"{paired['never_bound_tasks']} | {', '.join(paired['never_bound_mismatches']) or '-'} |"
        )
    calibration_text = ", ".join(
        f"{arm} {entry['median_ratio'] if entry['median_ratio'] is not None else 'n/a'} (n={entry['samples']})"
        for arm, entry in calibration.items()
    )
    lines += [
        "",
        "Estimator calibration (actual prompt tokens / estimated sent tokens): " + calibration_text + ".",
        "The 8000 cap is specified in estimated tokens; a ratio above 1 means the real prompt was larger.",
        "Never-bound tasks are the placebo: no call in either arm reached the budget, so the two arms sent the",
        "same history and must not differ. A mismatch there is provider nondeterminism, not memory.",
        "The paired p-value is exact and unadjusted; with one run per arm, report it next to the discordant counts.",
        "",
    ]
    (study / "comparison.json").write_text(json.dumps(result, indent=2))
    (study / "comparison.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["generation", "grading", "compare"])
    parser.add_argument("--arm", default="both", help="'both', 'all' (every <arm>.yaml), or one arm name")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if platform.system() != "Linux":
        raise SystemExit("Run inside Linux on the desktop; execution on the editing Mac is disabled.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    task_ids = json.loads((study / "tasks.json").read_text())
    if args.arm == "both":
        arms = ("off", "on")
    elif args.arm == "all":
        arms = tuple(sorted(path.stem for path in study.glob("*.yaml")))
    else:
        arms = (args.arm,)
    for arm in arms:
        if not (study / f"{arm}.yaml").is_file():
            raise SystemExit(f"Unknown arm {arm!r}: {study / (arm + '.yaml')} is missing")

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
