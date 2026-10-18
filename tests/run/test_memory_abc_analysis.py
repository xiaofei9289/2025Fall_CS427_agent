from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

STUDY = Path(__file__).resolve().parents[2] / "experiments" / "memory_abc_20261019"
SPEC = importlib.util.spec_from_file_location("memory_abc_analysis", STUDY / "analysis.py")
assert SPEC and SPEC.loader
analysis = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analysis
SPEC.loader.exec_module(analysis)

TASKS = ["t1", "t2", "t3", "t4", "t5"]
POLICIES = {"a": "window", "b": "summary", "c": "summary_search"}


def write_manifest(arm_dir: Path, arm: str, tasks=TASKS):
    manifest = {
        "run_id": arm,
        "created_at": "2026-01-01T00:00:00",
        "config": {
            "agent": {
                "memory_policy": POLICIES[arm],
                "memory_total_tokens": 8000,
                "memory_summary_tokens": 1000,
                "memory_retrieval_tokens": 1500,
                "step_limit": 400,
                "cost_limit": 10.0,
                "enabled_tools": ["read_file"],
            },
            "model": {"model_name": "deepseek/deepseek-chat"},
        },
        "instance_ids": list(tasks),
        "tasks": [{"instance_id": task} for task in tasks],
        "workers": 1,
        "source": {"sha256": "same-source"},
        "python": "3.11",
        "dependencies": {},
    }
    (arm_dir / "run_manifest.json").write_text(json.dumps(manifest))


def write_task(arm_dir: Path, arm: str, task: str, *, resolved: bool, dropped: int = 0, budget: int = 1000, search: bool = False, retrieval: int = 0):
    task_dir = arm_dir / task
    task_dir.mkdir(parents=True)
    records = [
        {
            "step": 1,
            "policy": POLICIES[arm],
            "budget": budget,
            "summary_tokens": 0,
            "retrieval_tokens": retrieval,
            "dropped_messages": dropped,
            "sent_messages": 3,
            "full_messages": 3 + dropped,
            "summary_present": False,
            "summary_text": "",
            "task_present": True,
            "clipped": False,
        }
    ]
    (task_dir / "memory_trace.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")
    messages = []
    messages.append(
        {
            "role": "assistant",
            "content": "action",
            "extra": {
                "memory": {"step": 1},
                "response": {"usage": {"prompt_tokens": 1200}},
            },
        }
    )
    if search:
        messages.append({"role": "assistant", "content": '```tool\n{"name": "memory_search", "args": {"query": "x"}}\n```'})
    trajectory = {
        "instance_id": task,
        "info": {"model_stats": {"instance_cost": 0.01, "api_calls": 2}, "exit_status": "Submitted"},
        "messages": messages,
    }
    (task_dir / f"{task}.traj.json").write_text(json.dumps(trajectory))


def make_study(root: Path, outcomes, *, violation: bool = False):
    study = root
    study.mkdir()
    (study / "pilot.json").write_text(json.dumps(["t1"]))
    (study / "tasks.json").write_text(json.dumps(TASKS))
    resolved = {arm: [task for task, marks in outcomes.items() if marks[arm]] for arm in POLICIES}
    for arm in POLICIES:
        arm_dir = study / arm
        arm_dir.mkdir()
        write_manifest(arm_dir, arm)
        evaluation = arm_dir / "evaluation"
        evaluation.mkdir()
        (evaluation / "grading_summary.json").write_text(
            json.dumps(
                {
                    "resolved_ids": resolved[arm],
                    "completed_ids": TASKS,
                    "empty_patch_ids": [],
                    "error_ids": [],
                }
            )
        )
        for task in TASKS:
            write_task(
                arm_dir,
                arm,
                task,
                resolved=outcomes[task][arm],
                dropped=3 if task in {"t2", "t3", "t4"} else 0,
                budget=9000 if violation and arm == "c" and task == "t4" else 1000,
                search=arm == "c" and task == "t4",
                retrieval=100 if arm == "c" and task == "t4" else 0,
            )
    return study


def test_report_has_c_minus_b_primary_and_all_tasks(tmp_path):
    outcomes = {
        "t1": {"a": True, "b": True, "c": True},
        "t2": {"a": True, "b": False, "c": False},
        "t3": {"a": False, "b": True, "c": True},
        "t4": {"a": False, "b": False, "c": True},
        "t5": {"a": False, "b": False, "c": False},
    }
    study = make_study(tmp_path / "study", outcomes)
    report = analysis.build_report(study)
    assert report["valid"] is True
    assert report["arms"]["c"]["resolved"] == 3
    assert report["estimator"]["a"]["samples"] == 5
    assert report["estimator"]["a"]["median_ratio"] == 1.2
    assert "C-B (history search beyond the same summary)" in report["contrasts"]
    contrast = report["contrasts"]["C-B (history search beyond the same summary)"][
        "all_tasks"
    ]
    assert contrast["gained"] == 1
    assert contrast["lost"] == 0
    assert set(report["per_task"]) == set(TASKS)
    assert (study / "comparison.md").is_file()
    markdown = (study / "comparison.md").read_text()
    assert "C-B" in markdown
    assert "t5" in markdown


def test_bc_only_report_keeps_c_minus_b_primary(tmp_path):
    outcomes = {
        "t1": {"a": True, "b": True, "c": True},
        "t2": {"a": True, "b": False, "c": False},
        "t3": {"a": False, "b": True, "c": True},
        "t4": {"a": False, "b": False, "c": True},
        "t5": {"a": False, "b": False, "c": False},
    }
    study = make_study(tmp_path / "study", outcomes)
    report = analysis.build_report(study, {"b": "b", "c": "c"})
    assert set(report["arms"]) == {"b", "c"}
    assert list(report["contrasts"]) == ["C-B (history search beyond the same summary)"]
    assert (study / "comparison.md").is_file()


def test_budget_violation_invalidates_the_report(tmp_path):
    outcomes = {
        "t1": {"a": True, "b": True, "c": True},
        "t2": {"a": True, "b": False, "c": False},
        "t3": {"a": False, "b": True, "c": True},
        "t4": {"a": False, "b": False, "c": True},
        "t5": {"a": False, "b": False, "c": False},
    }
    study = make_study(tmp_path / "study", outcomes, violation=True)
    report = analysis.build_report(study)
    assert report["valid"] is False
    assert report["arms"]["c"]["budget_violations"] == 1
    assert "total_over_budget" in report["per_task"]["t4"]["c"]["violations"]


def test_missing_grading_makes_the_report_invalid(tmp_path):
    outcomes = {
        "t1": {"a": True, "b": True, "c": True},
        "t2": {"a": True, "b": False, "c": False},
        "t3": {"a": False, "b": True, "c": True},
        "t4": {"a": False, "b": False, "c": True},
        "t5": {"a": False, "b": False, "c": False},
    }
    study = make_study(tmp_path / "study", outcomes)
    (study / "a" / "evaluation" / "grading_summary.json").unlink()
    report = analysis.build_report(study)
    assert report["valid"] is False


def test_multi_round_report_pools_task_rates(tmp_path):
    study = tmp_path / "multi"
    study.mkdir()
    (study / "pilot.json").write_text(json.dumps(["t1"]))
    (study / "tasks.json").write_text(json.dumps(TASKS))
    round_outcomes = {
        "r1": {
            "t1": {"a": True, "b": True, "c": True},
            "t2": {"a": True, "b": False, "c": False},
            "t3": {"a": False, "b": True, "c": True},
            "t4": {"a": False, "b": False, "c": True},
            "t5": {"a": False, "b": False, "c": False},
        },
        "r2": {
            "t1": {"a": True, "b": True, "c": True},
            "t2": {"a": True, "b": False, "c": False},
            "t3": {"a": False, "b": True, "c": True},
            "t4": {"a": False, "b": False, "c": False},
            "t5": {"a": False, "b": False, "c": False},
        },
    }
    for suffix, outcomes in round_outcomes.items():
        resolved = {arm: [task for task, marks in outcomes.items() if marks[arm]] for arm in POLICIES}
        for arm in POLICIES:
            arm_dir = study / f"{arm}_{suffix}"
            arm_dir.mkdir()
            write_manifest(arm_dir, arm)
            evaluation = arm_dir / "evaluation"
            evaluation.mkdir()
            (evaluation / "grading_summary.json").write_text(
                json.dumps(
                    {
                        "resolved_ids": resolved[arm],
                        "completed_ids": TASKS,
                        "empty_patch_ids": [],
                        "error_ids": [],
                    }
                )
            )
            for task in TASKS:
                write_task(arm_dir, arm, task, resolved=outcomes[task][arm], dropped=3 if task in {"t2", "t3", "t4"} else 0)
    multi = analysis.build_multi_report(study, ["r1", "r2"])
    assert multi["tasks"] == len(TASKS)
    assert multi["valid"] is True
    contrast = next(item for item in multi["contrasts"] if item["contrast"].startswith("C-B"))
    assert contrast["pooled_difference"] == 0.1  # +1 task in r1, 0 in r2, over 5 tasks
    assert (study / "comparison_all_rounds.md").is_file()
    assert (study / "comparison_r1.md").is_file()
    assert (study / "comparison_r2.md").is_file()
