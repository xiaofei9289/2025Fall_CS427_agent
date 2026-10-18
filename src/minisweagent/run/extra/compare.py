"""Compare frozen experiment arms without treating infrastructure errors as failures."""

import copy
import json
import re
from collections import Counter
from pathlib import Path

import typer

from minisweagent.run.extra.audit import audit_run

app = typer.Typer(add_completion=False)


def compare_runs(baseline: Path, retrieval: Path, treatment: str = "retrieval") -> dict:
    fields = {
        "retrieval": ("enabled_tools",),
        "finalization": ("finalization_step_reserve", "finalization_time_reserve", "finalization_cost_reserve"),
    }
    if treatment not in fields:
        raise ValueError(f"Unknown treatment: {treatment}")
    directories = {"baseline": baseline, treatment: retrieval}
    manifests = {name: json.loads((path / "run_manifest.json").read_text()) for name, path in directories.items()}
    controls = {}
    for name, manifest in manifests.items():
        control = copy.deepcopy(manifest)
        for field in fields[treatment]:
            control["config"]["agent"].pop(field, None)
        controls[name] = {key: control[key] for key in (
            "config", "instance_ids", "tasks", "workers", "source", "python", "dependencies",
        )}
    differences = [key for key in controls["baseline"] if controls["baseline"][key] != controls[treatment][key]]
    if differences:
        raise ValueError(f"Unmatched experiment controls: {', '.join(differences)}")
    tasks = {name: audit_run(path, path / "evaluation")["tasks"] for name, path in directories.items()}
    integrity = {name: {task["instance_id"]: task["issues"] for task in rows if task["issues"]}
                 for name, rows in tasks.items()}
    metrics = {}
    for name, rows in tasks.items():
        counter = Counter()
        for file in directories[name].rglob("*.traj.json"):
            trajectory = json.loads(file.read_text())
            for message in trajectory.get("messages", []):
                if message.get("role") == "assistant":
                    for tool in re.findall(r'"name"\s*:\s*"([^\"]+)"', message.get("content", "")):
                        counter[tool] += 1
        completed = [row for row in rows if row["evaluation_status"] in {"resolved", "unresolved"}]
        adjudicated = [row for row in rows if row["evaluation_status"] in {"resolved", "unresolved", "empty_patch"}]
        resolved = sum(row["evaluation_status"] == "resolved" for row in rows)
        metrics[name] = {
            "tasks": len(rows), "completed_tests": len(completed), "resolved": resolved,
            "empty_patches": sum(row["evaluation_status"] == "empty_patch" for row in rows),
            "evaluation_errors": sum(row["evaluation_status"] == "evaluation_error" for row in rows),
            "resolve_rate": resolved / len(rows) if len(adjudicated) == len(rows) and rows else None,
            "api_calls": sum(row["api_calls"] or 0 for row in rows),
            "cost_usd": sum(row["cost"] or 0 for row in rows),
            "total_tokens": sum(row["total_tokens"] or 0 for row in rows),
            "tool_requests": dict(counter),
        }
        execution = directories[name].parent / f"{name}_execution.json"
        if execution.exists():
            metrics[name]["wall_seconds"] = json.loads(execution.read_text())["wall_seconds"]
    by_id = {name: {row["instance_id"]: row for row in rows} for name, rows in tasks.items()}
    pairs = [{"instance_id": task_id, **{name: by_id[name][task_id]["evaluation_status"] for name in directories}}
             for task_id in manifests["baseline"]["instance_ids"]]
    return {
        "treatment": treatment,
        "matched_controls": True, "run_ids": {name: manifest["run_id"] for name, manifest in manifests.items()},
        "source": manifests["baseline"]["source"], "metrics": metrics, "pairs": pairs,
        "integrity_issues": integrity,
        "interpretation": "A small single-run pilot. " + (
            "Availability of retrieval tools is the treatment; tool requests do not prove useful retrieval. "
            if treatment == "retrieval" else
            "Finalization reserves are the treatment; both arms keep the same tools and hard budgets. "
        ) + "Sequential provider caching may affect cost. No population-level or causal improvement claim.",
    }


def render_comparison(comparison: dict) -> str:
    treatment = comparison.get("treatment", "retrieval")
    lines = [f"# Baseline / {treatment} controlled pilot", "", comparison["interpretation"], "",
             "Empty patches count as unsolved tasks in the resolve rate. Infrastructure errors and missing grades leave it pending.", "",
             "| Arm | Completed official tests | Empty patches | Resolved | Rate | API calls | Cost (USD) | Tokens |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, values in comparison["metrics"].items():
        rate = f"{values['resolve_rate']:.0%}" if values["resolve_rate"] is not None else "Pending / incomplete"
        lines.append(f"| {name} | {values['completed_tests']}/{values['tasks']} | {values['empty_patches']} | {values['resolved']} | "
                     f"{rate} | {values['api_calls']} | {values['cost_usd']:.6f} | {values['total_tokens']} |")
    lines += ["", f"| Instance | Baseline | {treatment.title()} |", "| --- | --- | --- |"]
    for pair in comparison["pairs"]:
        lines.append(f"| {pair['instance_id']} | {pair['baseline']} | {pair[treatment]} |")
    lines += ["", f"Integrity issues: `{json.dumps(comparison['integrity_issues'], sort_keys=True)}`", "",
              "Run IDs and the frozen source fingerprint are in comparison.json. "
              "Per-instance patches, trajectories, and official test logs remain in each arm.", ""]
    return "\n".join(lines)


@app.command()
def main(baseline: Path, retrieval: Path, output: Path, treatment: str = "retrieval"):
    output.mkdir(parents=True, exist_ok=True)
    comparison = compare_runs(baseline, retrieval, treatment)
    (output / "comparison.json").write_text(json.dumps(comparison, indent=2, ensure_ascii=False))
    (output / "comparison.md").write_text(render_comparison(comparison))
    print(output / "comparison.md")


if __name__ == "__main__":
    app()
