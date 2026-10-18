import json

import pytest

from minisweagent.run.extra.compare import compare_runs


def create_arm(path, *, error=False, empty=False):
    path.mkdir()
    manifest = {
        "run_id": path.name, "config": {"agent": {"step_limit": 50, "enabled_tools": [path.name]}},
        "instance_ids": ["org__repo-1"], "tasks": [], "workers": 1, "source": {"sha256": "abc"},
        "python": "3.11", "dependencies": {},
    }
    (path / "run_manifest.json").write_text(json.dumps(manifest))
    (path / "preds.json").write_text(json.dumps({"org__repo-1": {
        "instance_id": "org__repo-1", "model_patch": "" if empty else "diff --git a/a b/a",
    }}))
    task = path / "org__repo-1"
    task.mkdir()
    (task / "org__repo-1.traj.json").write_text(json.dumps({
        "run_id": path.name, "messages": [], "info": {
            "submission": "" if empty else "diff --git a/a b/a", "model_stats": {"api_calls": 2, "instance_cost": 0.02},
        },
    }))
    evaluation = path / "evaluation"
    evaluation.mkdir()
    (evaluation / "grading_summary.json").write_text(json.dumps({
        "submitted_ids": ["org__repo-1"], "completed_ids": [] if error or empty else ["org__repo-1"],
        "resolved_ids": [] if error or empty else ["org__repo-1"], "error_ids": ["org__repo-1"] if error else [],
        "empty_patch_ids": ["org__repo-1"] if empty else [],
    }))


def test_matched_comparison_and_infrastructure_error(tmp_path):
    baseline, retrieval = tmp_path / "baseline", tmp_path / "retrieval"
    create_arm(baseline)
    create_arm(retrieval, error=True)
    comparison = compare_runs(baseline, retrieval)
    assert comparison["metrics"]["baseline"]["resolve_rate"] == 1
    assert comparison["metrics"]["retrieval"]["resolve_rate"] is None
    assert comparison["metrics"]["retrieval"]["evaluation_errors"] == 1
    assert comparison["metrics"]["baseline"]["api_calls"] == 2
    assert comparison["integrity_issues"] == {"baseline": {}, "retrieval": {}}
    manifest_path = retrieval / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["config"]["agent"]["step_limit"] = 100
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="config"):
        compare_runs(baseline, retrieval)


def test_empty_submission_is_a_finished_unsolved_task(tmp_path):
    baseline, retrieval = tmp_path / "baseline", tmp_path / "retrieval"
    create_arm(baseline)
    create_arm(retrieval, empty=True)
    comparison = compare_runs(baseline, retrieval)
    metrics = comparison["metrics"]["retrieval"]
    assert metrics["resolve_rate"] == 0
    assert metrics["completed_tests"] == 0
    assert metrics["empty_patches"] == 1
    assert metrics["evaluation_errors"] == 0
    assert comparison["pairs"][0]["retrieval"] == "empty_patch"
    assert comparison["integrity_issues"] == {"baseline": {}, "retrieval": {}}


def test_finalization_ablation_keeps_tools_and_hard_budgets_matched(tmp_path):
    baseline, treatment = tmp_path / "baseline", tmp_path / "finalization"
    for path in (baseline, treatment):
        create_arm(path)
        manifest_path = path / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["config"]["agent"]["enabled_tools"] = ["code_search"]
        manifest["config"]["agent"]["finalization_step_reserve"] = 5 if path == treatment else 0
        manifest_path.write_text(json.dumps(manifest))
    comparison = compare_runs(baseline, treatment, "finalization")
    assert comparison["matched_controls"] is True and comparison["treatment"] == "finalization"
    assert set(comparison["metrics"]) == {"baseline", "finalization"}
    manifest_path = treatment / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["config"]["agent"]["enabled_tools"] = []
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="config"):
        compare_runs(baseline, treatment, "finalization")
