"""Audit one SWE-bench run without combining separate reruns or changing evidence."""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)

SIGNALS = {
    "path_error": r"Path must be within|outside (?:the )?(?:workspace|repo)|Access denied",
    "tool_argument_error": r"Unknown tool:|Invalid tool payload|Missing .*parameter|Invalid regex|Error: .*required",
    "environment_error": r"command not found|ModuleNotFoundError:|No module named|Permission denied",
    "test_failure": r"\b\d+ failed\b|\bFAILED [\w./-]+::|AssertionError:",
    "action_format_error": r"Please always provide EXACTLY ONE action|Invalid tool payload",
}


def trajectory_signals(messages: list[dict]) -> dict:
    """Collect observed symptoms, not inferred root causes, with message references."""
    evidence = defaultdict(list)
    counts = Counter()
    for index, message in enumerate(messages[2:], start=2):
        if message.get("role") != "user":
            continue
        text = message.get("content", "")
        for name, pattern in SIGNALS.items():
            match = re.search(pattern, text, re.I)
            if match:
                counts[name] += 1
                if len(evidence[name]) < 2:
                    evidence[name].append(
                        {"message_index": index, "excerpt": text[max(0, match.start() - 30) : match.end() + 160]}
                    )
    return {"counts": dict(counts), "evidence": dict(evidence)}


def audit_run(run_dir: Path, evaluation_dir: Path | None = None) -> dict:
    """Join predictions, trajectories, and grading reports by instance ID."""
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
    expected = set(manifest["instance_ids"]) if manifest is not None else set()
    predictions = defaultdict(list)
    trajectories = defaultdict(list)
    evaluations = defaultdict(list)
    for path in sorted(run_dir.glob("*preds.json")):
        data = json.loads(path.read_text())
        for row in data.values() if isinstance(data, dict) else data:
            predictions[row["instance_id"]].append((str(path), row))
    for path in sorted(run_dir.rglob("*.traj.json")):
        data = json.loads(path.read_text())
        trajectories[data.get("instance_id", path.parent.name)].append((str(path), data))
    for path in sorted((evaluation_dir or run_dir).glob("*.json")):
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or "submitted_ids" not in data or "resolved_ids" not in data:
            continue
        for instance_id in data["submitted_ids"]:
            status = "incomplete"
            for field, label in (
                ("completed_ids", "unresolved"),
                ("empty_patch_ids", "empty_patch"),
                ("error_ids", "evaluation_error"),
                ("resolved_ids", "resolved"),
            ):
                if instance_id in data.get(field, []):
                    status = label
            evaluations[instance_id].append((str(path), status))

    tasks = []
    for instance_id in sorted(expected | predictions.keys() | trajectories.keys() | evaluations.keys()):
        preds, trajs, evals = predictions[instance_id], trajectories[instance_id], evaluations[instance_id]
        issues = []
        for name, records in (("prediction", preds), ("trajectory", trajs), ("evaluation", evals)):
            if not records:
                issues.append(f"missing_{name}")
            elif len(records) > 1:
                issues.append(f"duplicate_{name}")
        pred = preds[0][1] if len(preds) == 1 else None
        traj = trajs[0][1] if len(trajs) == 1 else None
        if manifest is not None:
            if instance_id not in expected:
                issues.append("unexpected_instance")
            if traj is not None and traj.get("run_id") != manifest["run_id"]:
                issues.append("run_id_mismatch")
        info = traj.get("info", {}) if traj is not None else {}
        patch = pred.get("model_patch", "") if pred is not None else None
        submission = info.get("submission")
        if patch is not None and submission is not None and patch.strip() != submission.strip():
            issues.append("patch_mismatch")
        if patch and not patch.lstrip().startswith("diff --git "):
            issues.append("invalid_prediction_patch")
        status = evals[0][1] if len(evals) == 1 else "unknown"
        if patch is not None and (
            (status == "empty_patch" and patch.strip()) or (status == "resolved" and not patch.strip())
        ):
            issues.append("evaluation_patch_conflict")
        exit_status = info.get("exit_status")
        category = "unresolved_requires_review"
        if status == "resolved":
            category = "resolved"
        elif status == "unknown":
            category = "ungraded"
        elif exit_status == "LimitsExceeded" or info.get("agent_exit_status") == "LimitsExceeded":
            category = "budget_exhausted"
        elif status == "evaluation_error":
            category = "evaluation_error"
        elif patch is not None and not patch.strip():
            category = "empty_submission"
        elif "invalid_prediction_patch" in issues:
            category = "invalid_submission"
        config = info.get("config", {})
        stats = info.get("model_stats", {})
        messages = traj.get("messages", []) if traj is not None else []
        usage = [
            m["extra"]["response"]["usage"] for m in messages if m.get("extra", {}).get("response", {}).get("usage")
        ]
        tasks.append(
            {
                "instance_id": instance_id,
                "evaluation_status": status,
                "failure_category": category,
                "issues": issues,
                "trace_matches_prediction": traj is not None
                and pred is not None
                and not {"patch_mismatch", "run_id_mismatch"}.intersection(issues),
                "sources": {
                    "prediction": [p for p, _ in preds],
                    "trajectory": [p for p, _ in trajs],
                    "evaluation": [p for p, _ in evals],
                },
                "exit_status": exit_status,
                "agent_exit_status": info.get("agent_exit_status", exit_status),
                "budget": info.get("budget"),
                "patch_chars": len(patch) if patch is not None else None,
                "api_calls": stats.get("api_calls"),
                "cost": stats.get("instance_cost"),
                "total_tokens": sum(u.get("total_tokens", 0) or 0 for u in usage) if usage else None,
                "model": config.get("model", {}).get("model_name"),
                "step_limit": config.get("agent", {}).get("step_limit"),
                "cost_limit": config.get("agent", {}).get("cost_limit"),
                "memory_enabled": config.get("agent", {}).get("enable_memory"),
                "signals": trajectory_signals(messages),
            }
        )
    graded = [t for t in tasks if t["evaluation_status"] != "unknown"]
    resolved = sum(t["evaluation_status"] == "resolved" for t in graded)
    return {
        "run_dir": str(run_dir),
        "run_id": manifest["run_id"] if manifest is not None else None,
        "evaluation_dir": str(evaluation_dir or run_dir),
        "summary": {
            "tasks": len(tasks),
            "predictions": sum(map(len, predictions.values())),
            "trajectories": sum(map(len, trajectories.values())),
            "graded_tasks": len(graded),
            "resolved": resolved,
            "resolve_rate": resolved / len(graded) if graded else None,
            "issues": dict(Counter(issue for t in tasks for issue in t["issues"])),
            "failure_categories": dict(Counter(t["failure_category"] for t in tasks)),
            "step_limits": dict(Counter(str(t["step_limit"]) for t in tasks if t["sources"]["trajectory"])),
            "memory_enabled": dict(Counter(str(t["memory_enabled"]) for t in tasks if t["sources"]["trajectory"])),
        },
        "tasks": tasks,
    }


def render_report(audit: dict) -> str:
    summary = audit["summary"]
    lines = [
        "# SWE-bench run audit",
        "",
        f"Run: `{audit['run_dir']}`",
        "",
        f"Predictions: {summary['predictions']}; trajectories: {summary['trajectories']}; "
        f"graded tasks: {summary['graded_tasks']}; resolved: {summary['resolved']}.",
        "",
        "The grading reports define outcomes. Trajectory symptoms are review leads, not proven root causes. "
        "Metrics from mismatched or missing trajectories cannot explain the submitted patch's outcome.",
        "",
        f"Integrity issues: `{json.dumps(summary['issues'], sort_keys=True)}`",
        "",
        f"Step limits: `{json.dumps(summary['step_limits'], sort_keys=True)}`",
        "",
        f"Memory: `{json.dumps(summary['memory_enabled'], sort_keys=True)}`",
        "",
        "| Task | Grading | Category | Integrity issues | Observed symptoms |",
        "|---|---|---|---|---|",
    ]
    for task in audit["tasks"]:
        lines.append(
            f"| {task['instance_id']} | {task['evaluation_status']} | {task['failure_category']} | "
            f"{', '.join(task['issues']) or '-'} | {', '.join(task['signals']['counts']) or '-'} |"
        )
    return "\n".join(lines) + "\n"


@app.command()
def main(
    run_dir: Path = typer.Option(..., exists=True, file_okay=False),
    output: Path = typer.Option(..., help="Directory for audit.json and report.md."),
    evaluation_dir: Path | None = typer.Option(None, exists=True, file_okay=False),
) -> None:
    audit = audit_run(run_dir, evaluation_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    (output / "report.md").write_text(render_report(audit))
    typer.echo(json.dumps(audit["summary"], indent=2))


if __name__ == "__main__":
    app()
