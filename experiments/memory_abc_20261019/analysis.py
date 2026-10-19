"""Paired analysis and budget audit for the A/B/C memory study.

The report is deliberately conservative:

* C-B is the pre-registered primary contrast (does history search add anything
  beyond the same summary policy?);
* C-A and B-A are secondary;
* the never-overflow subset is a placebo: if its outcomes differ, the provider is
  not deterministic enough for a single-run causal claim;
* every task is listed, including failures;
* a budget violation (prompt > 8000, summary > 1000, retrieval > 1500, task
  missing) invalidates the arm rather than being averaged away.

No model calls are made here.  The module reads the generation and official
grading artifacts produced by ``run.py``.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from minisweagent.memory.abc.budget import DEFAULT_RETRIEVAL_TOKENS, DEFAULT_SUMMARY_TOKENS, DEFAULT_TOTAL_TOKENS
from minisweagent.memory.abc.policy import PolicyLimits, build_policy
from minisweagent.memory.abc.replay import replay_transcript
from minisweagent.memory.abc.stats import PairedResult, paired_result

_TOOL_RE = re.compile(r"```tool\n(.*?)\n```", re.DOTALL)
_DEFAULT_ARMS = {"a": "a", "b": "b", "c": "c"}
_POLICY = {"a": "window", "b": "summary", "c": "summary_search"}


@dataclass
class TaskMetrics:
    task: str
    resolved: bool
    status: str
    cost: float = 0.0
    api_calls: int = 0
    exit_status: str = ""
    agent_exit_status: str = ""
    calls: int = 0
    dropped_calls: int = 0
    clipped_calls: int = 0
    max_total: int = 0
    max_summary: int = 0
    max_retrieval: int = 0
    summary_calls: int = 0
    retrieval_calls: int = 0
    search_calls: int = 0
    prompt_tokens_est: int = 0
    prompt_tokens_actual: int = 0
    completion_tokens_actual: int = 0
    actual_prompt_samples: int = 0
    read_events: int = 0
    repeat_reads: int = 0
    recovery_reads: int = 0
    summary_recovery_reads: int = 0
    lost_recovery_reads: int = 0
    read_exposures: int = 0
    lost_read_exposures: int = 0
    replay_errors: int = 0
    violations: list[str] = field(default_factory=list)

    @property
    def truncated(self) -> bool:
        return self.dropped_calls > 0 or self.clipped_calls > 0


@dataclass
class ArmMetrics:
    arm: str
    tasks: int
    resolved: int
    empty_patches: int
    evaluation_errors: int
    cost: float
    api_calls: int
    dropped_calls: int
    clipped_calls: int
    summary_calls: int
    retrieval_calls: int
    search_calls: int
    violations: int
    prompt_tokens_est: int = 0
    prompt_tokens_actual: int = 0
    completion_tokens_actual: int = 0
    actual_prompt_samples: int = 0
    read_events: int = 0
    repeat_reads: int = 0
    recovery_reads: int = 0
    summary_recovery_reads: int = 0
    lost_recovery_reads: int = 0
    read_exposures: int = 0
    lost_read_exposures: int = 0
    replay_errors: int = 0
    source: str = ""
    policy: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "tasks": self.tasks,
            "resolved": self.resolved,
            "empty_patches": self.empty_patches,
            "evaluation_errors": self.evaluation_errors,
            "cost_usd": round(self.cost, 6),
            "api_calls": self.api_calls,
            "dropped_calls": self.dropped_calls,
            "clipped_calls": self.clipped_calls,
            "summary_calls": self.summary_calls,
            "retrieval_calls": self.retrieval_calls,
            "search_calls": self.search_calls,
            "budget_violations": self.violations,
            "source_sha256": self.source,
            "policy": self.policy,
            "estimated_prompt_tokens": self.prompt_tokens_est,
            "estimated_prompt_tokens_per_call": round(self.prompt_tokens_est / self.api_calls, 1)
            if self.api_calls
            else 0.0,
            "actual_prompt_tokens": self.prompt_tokens_actual,
            "actual_prompt_tokens_per_call": round(self.prompt_tokens_actual / self.actual_prompt_samples, 1)
            if self.actual_prompt_samples
            else None,
            "completion_tokens": self.completion_tokens_actual,
            "read_events": self.read_events,
            "repeat_reads": self.repeat_reads,
            "recovery_reads": self.recovery_reads,
            "summary_recovery_reads": self.summary_recovery_reads,
            "lost_recovery_reads": self.lost_recovery_reads,
            "read_exposures": self.read_exposures,
            "lost_read_exposures": self.lost_read_exposures,
            "lost_read_exposure_rate": round(self.lost_read_exposures / self.read_exposures, 3)
            if self.read_exposures
            else None,
            "replay_errors": self.replay_errors,
        }


@dataclass
class Contrast:
    name: str
    control: str
    treatment: str
    all_tasks: PairedResult
    bound_tasks: PairedResult | None
    never_bound: int
    placebo_mismatches: list[str]
    excluding_pilot: PairedResult | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "contrast": self.name,
            "control": self.control,
            "treatment": self.treatment,
            "all_tasks": self.all_tasks.as_dict(),
            "bound_tasks": self.bound_tasks.as_dict() if self.bound_tasks else None,
            "never_bound_tasks": self.never_bound,
            "placebo_mismatches": self.placebo_mismatches,
            "excluding_pilot": self.excluding_pilot.as_dict() if self.excluding_pilot else None,
        }


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _read_trace(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _search_calls(trajectory: Path) -> int:
    if not trajectory.is_file():
        return 0
    data = _load_json(trajectory)
    calls = 0
    for message in data.get("messages", []):
        if message.get("role") != "assistant":
            continue
        for block in _TOOL_RE.findall(message.get("content") or ""):
            try:
                payload = json.loads(block)
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict) and payload.get("name") == "memory_search":
                calls += 1
    return calls


def _policy_for_manifest(manifest: dict[str, Any]):
    """Build the arm's policy for offline replay; None if the manifest is unusable."""
    agent = manifest.get("config", {}).get("agent", {})
    try:
        return build_policy(
            str(agent.get("memory_policy", "")),
            PolicyLimits(
                total_tokens=int(agent.get("memory_total_tokens", DEFAULT_TOTAL_TOKENS)),
                summary_tokens=int(agent.get("memory_summary_tokens", DEFAULT_SUMMARY_TOKENS)),
                retrieval_tokens=int(agent.get("memory_retrieval_tokens", DEFAULT_RETRIEVAL_TOKENS)),
            ),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_arm_metrics(arm_dir: Path) -> tuple[dict[str, TaskMetrics], ArmMetrics]:
    """Read one arm's traces, trajectories, and official grading summary.

    In addition to outcome and budget metrics, every task is replayed offline
    through its own policy.  The replay supplies deterministic mechanism
    counters (read events, recovery re-reads, lost read exposures) without any
    model or environment call.
    """
    manifest = _load_json(arm_dir / "run_manifest.json")
    tasks = list(manifest["instance_ids"])
    grading_path = arm_dir / "evaluation" / "grading_summary.json"
    grading = _load_json(grading_path) if grading_path.is_file() else {}
    resolved_ids = set(grading.get("resolved_ids", []))
    empty_ids = set(grading.get("empty_patch_ids", []))
    error_ids = set(grading.get("error_ids", []))
    completed_ids = set(grading.get("completed_ids", []))
    policy = _policy_for_manifest(manifest)

    rows: dict[str, TaskMetrics] = {}
    for task in tasks:
        task_dir = arm_dir / task
        trace = _read_trace(task_dir / "memory_trace.jsonl")
        trajectory = task_dir / f"{task}.traj.json"
        trajectory_data: dict[str, Any] = {}
        if trajectory.is_file():
            trajectory_data = _load_json(trajectory)
        info = trajectory_data.get("info", {})
        stats = info.get("model_stats", {})
        outer_exit = str(info.get("exit_status") or "")
        agent_exit = str(info.get("agent_exit_status") or outer_exit)
        status = "resolved" if task in resolved_ids else "unresolved"
        if task in empty_ids:
            status = "empty_patch"
        if task in error_ids:
            status = "evaluation_error"
        if (not grading or task not in completed_ids) and task not in empty_ids and task not in error_ids:
            status = "missing"
        row = TaskMetrics(
            task=task,
            resolved=task in resolved_ids,
            status=status,
            cost=float(stats.get("instance_cost") or 0.0),
            api_calls=int(stats.get("api_calls") or 0),
            exit_status=outer_exit,
            agent_exit_status=agent_exit,
            calls=len(trace),
            search_calls=_search_calls(trajectory),
        )
        if not trace:
            row.violations.append("trace_missing")
        if not trajectory.is_file():
            row.violations.append("trajectory_missing")
        if row.agent_exit_status not in {"Submitted", "RecoveredPatch", "LimitsExceeded"}:
            row.violations.append(f"agent_exit:{row.agent_exit_status or 'unknown'}")
        for record in trace:
            row.dropped_calls += int(record.get("dropped_messages", 0) > 0)
            row.clipped_calls += int(bool(record.get("clipped")))
            row.max_total = max(row.max_total, int(record.get("budget", 0)))
            row.max_summary = max(row.max_summary, int(record.get("summary_tokens", 0)))
            row.max_retrieval = max(
                row.max_retrieval,
                int(record.get("max_retrieval_tokens", record.get("retrieval_tokens", 0))),
            )
            row.summary_calls += int(bool(record.get("summary_present")))
            row.retrieval_calls += int(int(record.get("retrieval_tokens", 0)) > 0)
            row.prompt_tokens_est += int(record.get("budget", 0))
            if not record.get("task_present", False):
                row.violations.append("task_missing")
            budget_enforced = bool(record.get("budget_enforced", True))
            if budget_enforced and int(record.get("budget", 0)) > DEFAULT_TOTAL_TOKENS:
                row.violations.append("total_over_budget")
            if int(record.get("summary_tokens", 0)) > DEFAULT_SUMMARY_TOKENS:
                row.violations.append("summary_over_budget")
            if int(record.get("max_retrieval_tokens", record.get("retrieval_tokens", 0))) > DEFAULT_RETRIEVAL_TOKENS:
                row.violations.append("retrieval_over_budget")

        for message in trajectory_data.get("messages", []):
            if message.get("role") != "assistant":
                continue
            usage = (message.get("extra") or {}).get("response", {}).get("usage") or {}
            prompt = int(usage.get("prompt_tokens") or 0)
            completion = int(usage.get("completion_tokens") or 0)
            if prompt:
                row.prompt_tokens_actual += prompt
                row.actual_prompt_samples += 1
            if completion:
                row.completion_tokens_actual += completion

        if policy is not None and trajectory_data:
            try:
                replay = replay_transcript(trajectory_data.get("messages", []), policy)
            except Exception:  # noqa: BLE001 - replay is diagnostic, not a run
                row.replay_errors += 1
            else:
                row.read_events = replay.read_events
                row.repeat_reads = replay.repeat_reads
                row.recovery_reads = replay.recovery_reads
                row.summary_recovery_reads = replay.summary_recovery_reads
                row.lost_recovery_reads = replay.lost_recovery_reads
                row.read_exposures = replay.read_exposures
                row.lost_read_exposures = replay.lost_read_exposures
                row.replay_errors += replay.view_errors

        row.violations = sorted(set(row.violations))
        rows[task] = row

    metrics = ArmMetrics(
        arm=arm_dir.name,
        tasks=len(tasks),
        resolved=sum(row.resolved for row in rows.values()),
        empty_patches=len(empty_ids),
        evaluation_errors=len(error_ids),
        cost=sum(row.cost for row in rows.values()),
        api_calls=sum(row.api_calls for row in rows.values()),
        dropped_calls=sum(row.dropped_calls for row in rows.values()),
        clipped_calls=sum(row.clipped_calls for row in rows.values()),
        summary_calls=sum(row.summary_calls for row in rows.values()),
        retrieval_calls=sum(row.retrieval_calls for row in rows.values()),
        search_calls=sum(row.search_calls for row in rows.values()),
        violations=sum(bool(row.violations) for row in rows.values()),
        prompt_tokens_est=sum(row.prompt_tokens_est for row in rows.values()),
        prompt_tokens_actual=sum(row.prompt_tokens_actual for row in rows.values()),
        completion_tokens_actual=sum(row.completion_tokens_actual for row in rows.values()),
        actual_prompt_samples=sum(row.actual_prompt_samples for row in rows.values()),
        read_events=sum(row.read_events for row in rows.values()),
        repeat_reads=sum(row.repeat_reads for row in rows.values()),
        recovery_reads=sum(row.recovery_reads for row in rows.values()),
        summary_recovery_reads=sum(row.summary_recovery_reads for row in rows.values()),
        lost_recovery_reads=sum(row.lost_recovery_reads for row in rows.values()),
        read_exposures=sum(row.read_exposures for row in rows.values()),
        lost_read_exposures=sum(row.lost_read_exposures for row in rows.values()),
        replay_errors=sum(row.replay_errors for row in rows.values()),
        source=str(manifest.get("source", {}).get("sha256", "")),
        policy=str(manifest.get("config", {}).get("agent", {}).get("memory_policy", "")),
    )
    return rows, metrics


def estimator_calibration(arm_dir: Path) -> dict[str, Any]:
    """Compare the shared estimate with the provider's prompt-token count."""
    ratios: list[float] = []
    max_actual = 0
    for trajectory in arm_dir.glob("*/*.traj.json"):
        data = _load_json(trajectory)
        trace = _read_trace(trajectory.parent / "memory_trace.jsonl")
        records = {int(record.get("step", 0)): record for record in trace}
        for message in data.get("messages", []):
            if message.get("role") != "assistant":
                continue
            extra = message.get("extra") or {}
            memory = extra.get("memory") or {}
            usage = (extra.get("response") or {}).get("usage") or {}
            actual = int(usage.get("prompt_tokens") or 0)
            record = records.get(int(memory.get("step", 0)))
            if not actual or record is None:
                continue
            estimated = int(record.get("budget") or 0)
            if estimated:
                ratios.append(actual / estimated)
                max_actual = max(max_actual, actual)
    if not ratios:
        return {"samples": 0, "median_ratio": None, "p90_ratio": None, "max_actual_prompt_tokens": 0}
    ratios.sort()
    return {
        "samples": len(ratios),
        "median_ratio": round(statistics.median(ratios), 3),
        "p90_ratio": round(ratios[int(0.9 * (len(ratios) - 1))], 3),
        "max_actual_prompt_tokens": max_actual,
    }


def _controls(manifest: dict[str, Any]) -> dict[str, Any]:
    controls = json.loads(json.dumps(manifest))
    controls["config"]["agent"].pop("memory_policy", None)
    controls["config"]["agent"].pop("memory_trace_path", None)
    for key in ("run_id", "created_at"):
        controls.pop(key, None)
    return controls


def _check_controls(manifests: dict[str, dict[str, Any]]) -> None:
    baseline = manifests[sorted(manifests)[0]]
    for arm, manifest in manifests.items():
        if arm not in _POLICY:
            raise ValueError(f"unknown arm {arm!r}")
        if _controls(manifest) != _controls(baseline):
            raise ValueError(f"arm {arm} does not share the pre-registered controls")
        if manifest["config"]["agent"].get("memory_policy") != _POLICY[arm]:
            raise ValueError(f"arm {arm} has the wrong memory_policy")


def _contrast(
    name: str,
    control: str,
    treatment: str,
    rows: dict[str, dict[str, TaskMetrics]],
    pilot: set[str],
) -> Contrast:
    control_outcomes = {task: row.resolved for task, row in rows[control].items()}
    treatment_outcomes = {task: row.resolved for task, row in rows[treatment].items()}
    all_result = paired_result(control_outcomes, treatment_outcomes)

    def active(arm: str, task: str) -> bool:
        row = rows[arm][task]
        return row.truncated or row.search_calls > 0

    bound = [
        task
        for task in control_outcomes
        if active(control, task) or active(treatment, task)
    ]
    bound_result = None
    if bound:
        bound_result = paired_result(
            {task: control_outcomes[task] for task in bound},
            {task: treatment_outcomes[task] for task in bound},
        )
    never_bound = [
        task
        for task in control_outcomes
        if not (active(control, task) or active(treatment, task))
    ]
    mismatches = [task for task in never_bound if control_outcomes[task] != treatment_outcomes[task]]

    formal = [task for task in control_outcomes if task not in pilot]
    excluding = None
    if formal:
        excluding = paired_result(
            {task: control_outcomes[task] for task in formal},
            {task: treatment_outcomes[task] for task in formal},
        )
    return Contrast(
        name=name,
        control=control,
        treatment=treatment,
        all_tasks=all_result,
        bound_tasks=bound_result,
        never_bound=len(never_bound),
        placebo_mismatches=mismatches,
        excluding_pilot=excluding,
    )


def build_report(study: Path, arms: dict[str, str] | None = None, *, suffix: str = "") -> dict[str, Any]:
    """Build the JSON report and write the markdown next to the study."""
    arms = dict(_DEFAULT_ARMS if arms is None else arms)
    if len(arms) < 2:
        raise ValueError("at least two arms are required")
    if not {"b", "c"} <= set(arms):
        raise ValueError("the primary C-B contrast requires both b and c")
    paths = {arm: study / tag for arm, tag in arms.items()}
    manifests = {arm: _load_json(paths[arm] / "run_manifest.json") for arm in arms}
    _check_controls(manifests)
    baseline_arm = sorted(arms)[0]
    rows: dict[str, dict[str, TaskMetrics]] = {}
    metrics: dict[str, ArmMetrics] = {}
    for arm in arms:
        rows[arm], metrics[arm] = load_arm_metrics(paths[arm])

    pilot_path = study / "pilot.json"
    pilot = set(_load_json(pilot_path)) if pilot_path.is_file() else set()

    calibration = {arm: estimator_calibration(paths[arm]) for arm in arms}
    contrasts = [_contrast("C-B (history search beyond the same summary)", "b", "c", rows, pilot)]
    if "a" in arms:
        contrasts += [
            _contrast("B-A (summary beyond the window)", "a", "b", rows, pilot),
            _contrast("C-A (the whole memory package)", "a", "c", rows, pilot),
        ]
    missing = any(row.status == "missing" for arm in rows for row in rows[arm].values())
    valid = (
        all(metric.violations == 0 for metric in metrics.values())
        and all(metric.evaluation_errors == 0 for metric in metrics.values())
        and not missing
    )
    retrieval_used = metrics["c"].search_calls > 0 if "c" in metrics else False
    no_search_tasks = (
        sorted(task for task, row in rows["c"].items() if row.search_calls == 0)
        if "c" in rows
        else []
    )

    report: dict[str, Any] = {
        "study": str(study),
        "source": manifests[baseline_arm].get("source"),
        "tasks": len(manifests[baseline_arm]["instance_ids"]),
        "pilot_tasks": sorted(pilot),
        "valid": valid,
        "retrieval_used": retrieval_used,
        "no_search_tasks": no_search_tasks,
        "arms": {arm: metrics[arm].as_dict() for arm in arms},
        "estimator": calibration,
        "contrasts": {contrast.name: contrast.as_dict() for contrast in contrasts},
        "per_task": {
            task: {
                arm: {
                    "resolved": rows[arm][task].resolved,
                    "status": rows[arm][task].status,
                    "exit_status": rows[arm][task].exit_status,
                    "agent_exit_status": rows[arm][task].agent_exit_status,
                    "cost": round(rows[arm][task].cost, 6),
                    "calls": rows[arm][task].calls,
                    "dropped_calls": rows[arm][task].dropped_calls,
                    "clipped_calls": rows[arm][task].clipped_calls,
                    "summary_calls": rows[arm][task].summary_calls,
                    "search_calls": rows[arm][task].search_calls,
                    "max_total": rows[arm][task].max_total,
                    "max_summary": rows[arm][task].max_summary,
                    "max_retrieval": rows[arm][task].max_retrieval,
                    "prompt_tokens_est": rows[arm][task].prompt_tokens_est,
                    "prompt_tokens_actual": rows[arm][task].prompt_tokens_actual,
                    "read_events": rows[arm][task].read_events,
                    "repeat_reads": rows[arm][task].repeat_reads,
                    "summary_recovery_reads": rows[arm][task].summary_recovery_reads,
                    "recovery_reads": rows[arm][task].recovery_reads,
                    "lost_recovery_reads": rows[arm][task].lost_recovery_reads,
                    "lost_read_exposures": rows[arm][task].lost_read_exposures,
                    "replay_errors": rows[arm][task].replay_errors,
                    "violations": rows[arm][task].violations,
                }
                for arm in arms
            }
            for task in manifests[baseline_arm]["instance_ids"]
        },
    }
    (study / f"comparison{suffix}.json").write_text(json.dumps(report, indent=2) + "\n")
    (study / f"comparison{suffix}.md").write_text(
        _render_markdown(report, rows, metrics, contrasts, pilot, arms, calibration)
    )
    return report


def _render_markdown(
    report: dict[str, Any],
    rows: dict[str, dict[str, TaskMetrics]],
    metrics: dict[str, ArmMetrics],
    contrasts: list[Contrast],
    pilot: set[str],
    arms: dict[str, str],
    calibration: dict[str, dict[str, Any]],
) -> str:
    lines = [
        "# A/B/C memory comparison",
        "",
        f"Tasks: {report['tasks']}; pilot (excluded from the secondary table): {len(pilot)}.",
        f"Valid: **{report['valid']}** (a false value means at least one arm broke the pre-registered budget).",
        "",
    ]
    if not report.get("retrieval_used", True):
        lines += [
            "> **Attribution warning:** the C arm made **0** memory_search calls. C-B cannot be",
            "> attributed to history retrieval; treat it as a tool-description/prompt effect or noise.",
            "",
        ]
    if report.get("no_search_tasks"):
        lines += [
            "> **C tasks without retrieval:** "
            + ", ".join(report["no_search_tasks"])
            + ". Their C-B contrast is not a retrieval test.",
            "",
        ]
    lines += [
        "## Arms",
        "",
        "| Arm | Policy | Resolved | Empty | Eval errors | Cost (USD) | API calls | Dropped calls | Clipped calls | Summary calls | Retrieval calls | Search tool calls | Violations |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    policy = {arm: metrics[arm].policy for arm in arms}
    for arm in arms:
        metric = metrics[arm]
        lines.append(
            f"| {arm} | {policy[arm]} | {metric.resolved}/{metric.tasks} | {metric.empty_patches} | "
            f"{metric.evaluation_errors} | {metric.cost:.6f} | {metric.api_calls} | {metric.dropped_calls} | "
            f"{metric.clipped_calls} | {metric.summary_calls} | {metric.retrieval_calls} | "
            f"{metric.search_calls} | {metric.violations} |"
        )

    lines += [
        "",
        "## Estimator calibration",
        "",
        "| Arm | Samples | Median actual/estimated | p90 | Max actual prompt |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for arm in arms:
        entry = calibration[arm]
        median = entry["median_ratio"] if entry["median_ratio"] is not None else "n/a"
        p90 = entry["p90_ratio"] if entry["p90_ratio"] is not None else "n/a"
        lines.append(
            f"| {arm} | {entry['samples']} | {median} | {p90} | {entry['max_actual_prompt_tokens']} |"
        )
    lines += [
        "",
        "## Mechanism metrics (offline replay)",
        "",
        "| Arm | Est. prompt tokens/call | Actual prompt tokens/call | Read events | Repeat reads | Recovery re-reads | Summary recovery | Lost recovery | Lost read exposures | Lost exposure rate | Replay errors |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm in arms:
        metric = metrics[arm]
        est_per_call = round(metric.prompt_tokens_est / metric.api_calls, 1) if metric.api_calls else "n/a"
        actual_per_call = (
            round(metric.prompt_tokens_actual / metric.actual_prompt_samples, 1)
            if metric.actual_prompt_samples
            else "n/a"
        )
        exposure_rate = (
            f"{metric.lost_read_exposures / metric.read_exposures:.3f}" if metric.read_exposures else "n/a"
        )
        lines.append(
            f"| {arm} | {est_per_call} | {actual_per_call} | {metric.read_events} | "
            f"{metric.repeat_reads} | {metric.recovery_reads} | {metric.summary_recovery_reads} | "
            f"{metric.lost_recovery_reads} | {metric.lost_read_exposures} | {exposure_rate} | "
            f"{metric.replay_errors} |"
        )
    lines += [
        "",
        "`Recovery re-reads` count a successful re-read of a path whose previous read was not fully visible",
        "in the prompt and where no write to that path intervened.  `Lost read exposures` count read",
        "observations that were current (no later write) but absent from the prompt at the next read.",
        "These are deterministic proxies from the transcript, not causal error labels; replay errors mean a",
        "trajectory could not be parsed and are reported rather than hidden.",
        "",
        "## Pre-registered contrast",
        "",
        "| Contrast | Gained | Lost | Difference | 95% CI | McNemar p | Bound tasks | Never-bound | Placebo mismatches |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for contrast in contrasts:
        result = contrast.all_tasks
        bound = contrast.bound_tasks
        lines.append(
            f"| {contrast.name} | {result.gained} | {result.lost} | {result.difference:+.3f} | "
            f"[{result.ci_low:+.3f}, {result.ci_high:+.3f}] | {result.p_value:.4f} | "
            f"{bound.tasks if bound else 0} | {contrast.never_bound} | "
            f"{', '.join(contrast.placebo_mismatches) or '-'} |"
        )
    lines += [
        "",
        "C-B is primary.  The interval is a task-level bootstrap percentile interval; with one run per arm it",
        "does not include run-to-run provider variance.  Repeats are reported separately.",
        "",
        "### Excluding the pilot tasks",
        "",
        "| Contrast | Gained | Lost | Difference | 95% CI | McNemar p | Tasks |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for contrast in contrasts:
        result = contrast.excluding_pilot
        if result is None:
            continue
        lines.append(
            f"| {contrast.name} | {result.gained} | {result.lost} | {result.difference:+.3f} | "
            f"[{result.ci_low:+.3f}, {result.ci_high:+.3f}] | {result.p_value:.4f} | {result.tasks} |"
        )
    lines += [
        "",
        "## Per-task results",
        "",
        "Tasks marked `*` are pilot tasks; they are excluded from the table above but shown here for completeness.",
        "Each cell is `arm=value`.",
        "",
        "| Task | Resolved | Dropped calls | Summary calls | Search calls | Max tokens | Repeat reads | Recovery re-reads | Violations |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for task in report["per_task"]:
        row = report["per_task"][task]
        resolved = " ".join(f"{arm}={'PASS' if row[arm]['resolved'] else 'fail'}" for arm in arms)
        dropped = " ".join(f"{arm}={row[arm]['dropped_calls']}" for arm in arms)
        summary = " ".join(f"{arm}={row[arm]['summary_calls']}" for arm in arms)
        search = " ".join(f"{arm}={row[arm]['search_calls']}" for arm in arms)
        totals = " ".join(f"{arm}={row[arm]['max_total']}" for arm in arms)
        repeats = " ".join(f"{arm}={row[arm]['repeat_reads']}" for arm in arms)
        recoveries = " ".join(f"{arm}={row[arm]['recovery_reads']}" for arm in arms)
        violations = sorted({v for arm in arms for v in row[arm]["violations"]})
        label = task + ("*" if task in pilot else "")
        lines.append(
            f"| {label} | {resolved} | {dropped} | {summary} | {search} | {totals} | {repeats} | "
            f"{recoveries} | {', '.join(violations) or '-'} |"
        )
    lines += [
        "",
        "All tasks are shown; no search-success case selection.  `Dropped` counts model calls whose view omitted",
        "at least one message; `Summary` counts calls that carried the evidence summary.  `Max tokens` is the",
        "estimated prompt total, not the provider count; the traces provide the per-call values.",
        "Never-bound is exact for A/B (same prompt).  For contrasts involving C it is a soft check: C still carries",
        "the memory_search tool description even when it makes no search call.",
        "",
    ]
    return "\n".join(lines)


def _bootstrap_mean_ci(values: list[float], *, bootstrap: int = 10_000, seed: int = 0) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    if len(values) == 1:
        return (values[0], values[0])
    import random

    rng = random.Random(seed)
    samples = []
    for _ in range(bootstrap):
        total = 0.0
        for _ in range(len(values)):
            total += values[rng.randrange(len(values))]
        samples.append(total / len(values))
    samples.sort()
    return (samples[int(0.025 * (len(samples) - 1))], samples[int(0.975 * (len(samples) - 1))])


def build_multi_report(study: Path, rounds: list[str]) -> dict[str, Any]:
    """Analyze several paired rounds and a task-level descriptive pool.

    Each round is a complete paired block and is written to its own
    ``comparison_<round>.md``.  The pool averages each task's outcome over the
    rounds and bootstraps over tasks; it is not a claim that task-runs are
    independent, and per-round exact McNemar p-values remain the primary test.
    """
    rounds = [round.strip() for round in rounds if round.strip()]
    if not rounds:
        raise ValueError("no rounds")
    reports = {
        name: build_report(
            study,
            {arm: f"{arm}_{name}" for arm in ("a", "b", "c")},
            suffix=f"_{name}",
        )
        for name in rounds
    }
    tasks = sorted(set.intersection(*(set(report["per_task"]) for report in reports.values())))
    rates = {
        arm: {task: statistics.mean(int(reports[name]["per_task"][task][arm]["resolved"]) for name in rounds) for task in tasks}
        for arm in ("a", "b", "c")
    }
    contrasts = []
    for name, control, treatment in (
        ("C-B (history search beyond the same summary)", "b", "c"),
        ("B-A (summary beyond the window)", "a", "b"),
        ("C-A (the whole memory package)", "a", "c"),
    ):
        differences = [rates[treatment][task] - rates[control][task] for task in tasks]
        mean = statistics.mean(differences) if differences else 0.0
        low, high = _bootstrap_mean_ci(differences)
        per_round = {
            round_name: reports[round_name]["contrasts"][name]["all_tasks"] for round_name in rounds
        }
        contrasts.append(
            {
                "contrast": name,
                "control": control,
                "treatment": treatment,
                "pooled_difference": round(mean, 4),
                "pooled_ci95_low": round(low, 4),
                "pooled_ci95_high": round(high, 4),
                "per_round": per_round,
            }
        )
    result = {
        "rounds": rounds,
        "valid": all(report["valid"] for report in reports.values()),
        "tasks": len(tasks),
        "arms": {arm: reports[rounds[0]]["arms"][arm] for arm in ("a", "b", "c")},
        "pooled_task_rates": rates,
        "contrasts": contrasts,
    }
    (study / "comparison_all_rounds.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = [
        "# A/B/C memory comparison across rounds",
        "",
        f"Rounds: {', '.join(rounds)}; tasks: {len(tasks)}; valid: **{result['valid']}**.",
        "",
        "| Contrast | Pooled difference | 95% CI | Per-round differences |",
        "| --- | ---: | --- | --- |",
    ]
    for contrast in contrasts:
        per_round = ", ".join(
            f"{round_name} {entry['difference']:+.3f}" for round_name, entry in contrast["per_round"].items()
        )
        lines.append(
            f"| {contrast['contrast']} | {contrast['pooled_difference']:+.3f} | "
            f"[{contrast['pooled_ci95_low']:+.3f}, {contrast['pooled_ci95_high']:+.3f}] | {per_round} |"
        )
    lines += [
        "",
        "The pool averages each task over rounds and bootstraps over tasks.  The interval is descriptive;",
        "the per-round exact McNemar p-values in each `comparison_<round>.md` remain the primary test.",
        "",
    ]
    (study / "comparison_all_rounds.md").write_text("\n".join(lines))
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", nargs="?", default=str(Path(__file__).resolve().parent))
    parser.add_argument("--a-tag", default="a")
    parser.add_argument("--b-tag", default="b")
    parser.add_argument("--c-tag", default="c")
    parser.add_argument("--arms", default="a,b,c", help="comma-separated arm keys, e.g. b,c")
    parser.add_argument("--rounds", default="", help="comma-separated round suffixes, e.g. r1,r2")
    args = parser.parse_args()
    if args.rounds:
        multi = build_multi_report(Path(args.study), args.rounds.split(","))
        print(f"valid={multi['valid']} tasks={multi['tasks']}")
        return
    requested = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    tags = {"a": args.a_tag, "b": args.b_tag, "c": args.c_tag}
    report = build_report(Path(args.study), {arm: tags[arm] for arm in requested})
    print(f"valid={report['valid']} resolved=" + ", ".join(
        f"{arm}={report['arms'][arm]['resolved']}/{report['arms'][arm]['tasks']}" for arm in ("a", "b", "c")
    ))


if __name__ == "__main__":
    main()
