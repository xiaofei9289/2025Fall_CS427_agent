import json

from minisweagent.run.extra.audit import audit_run, render_report


def test_audit_preserves_grading_and_exposes_missing_and_mismatched_evidence(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    patch = "diff --git a/a.py b/a.py\n"
    (run / "preds.json").write_text(
        json.dumps(
            {
                "fixed": {"instance_id": "fixed", "model_patch": patch},
                "empty": {"instance_id": "empty", "model_patch": ""},
                "missing": {"instance_id": "missing", "model_patch": patch},
            }
        )
    )
    (tmp_path / "grading.json").write_text(
        json.dumps(
            {
                "submitted_ids": ["fixed", "empty", "missing"],
                "resolved_ids": ["fixed"],
                "completed_ids": ["fixed", "missing"],
                "empty_patch_ids": ["empty"],
            }
        )
    )
    for name in ("fixed", "empty"):
        (run / f"{name}.traj.json").write_text(
            json.dumps(
                {
                    "instance_id": name,
                    "info": {
                        "submission": patch,
                        "exit_status": "LimitsExceeded" if name == "empty" else "Submitted",
                        "config": {"agent": {"step_limit": 50, "enable_memory": False}},
                    },
                    "messages": [
                        {"role": "system", "content": "Path must be within"},
                        {"role": "user", "content": "AssertionError:"},
                        {"role": "assistant", "content": "command not found"},
                        {"role": "user", "content": "Path must be within /testbed"},
                    ],
                }
            )
        )
    audit = audit_run(run, tmp_path)
    assert audit["summary"]["resolved"] == 1
    assert audit["summary"]["resolve_rate"] == 1 / 3
    assert audit["summary"]["issues"] == {"patch_mismatch": 1, "missing_trajectory": 1}
    rows = {row["instance_id"]: row for row in audit["tasks"]}
    assert rows["empty"]["failure_category"] == "budget_exhausted"
    assert rows["empty"]["trace_matches_prediction"] is False
    assert rows["empty"]["signals"]["counts"] == {"path_error": 1}
    assert rows["empty"]["signals"]["evidence"]["path_error"][0]["message_index"] == 3
    assert rows["missing"]["total_tokens"] is None
    assert "patch_mismatch" in render_report(audit)


def test_audit_does_not_treat_an_ungraded_submission_as_success(tmp_path):
    (tmp_path / "preds.json").write_text(
        json.dumps(
            [
                {"instance_id": "one", "model_patch": "diagnostic text"},
                {"instance_id": "two", "model_patch": ""},
            ]
        )
    )
    audit = audit_run(tmp_path)
    assert audit["summary"]["resolve_rate"] is None
    assert audit["summary"]["issues"] == {
        "missing_trajectory": 2,
        "missing_evaluation": 2,
        "invalid_prediction_patch": 1,
    }
    assert {row["failure_category"] for row in audit["tasks"]} == {"ungraded"}


def test_duplicate_records_are_reported_instead_of_silently_overwritten(tmp_path):
    prediction = {"instance_id": "same", "model_patch": ""}
    for name in ("a.preds.json", "b.preds.json"):
        (tmp_path / name).write_text(json.dumps([prediction]))
    audit = audit_run(tmp_path)
    assert audit["summary"]["predictions"] == 2
    assert audit["tasks"][0]["issues"] == ["duplicate_prediction", "missing_trajectory", "missing_evaluation"]


def test_recovered_candidate_retains_original_budget_stop(tmp_path):
    patch = "diff --git a/pkg/app.py b/pkg/app.py\n"
    (tmp_path / "preds.json").write_text(json.dumps([{"instance_id": "one", "model_patch": patch}]))
    (tmp_path / "one.traj.json").write_text(json.dumps({
        "instance_id": "one", "messages": [], "info": {
            "exit_status": "RecoveredPatch", "agent_exit_status": "LimitsExceeded", "submission": patch,
            "budget": {"phase": "finalizing", "limit_reason": "steps", "remaining_steps": 0},
        },
    }))
    (tmp_path / "grading.json").write_text(json.dumps({
        "submitted_ids": ["one"], "completed_ids": ["one"], "resolved_ids": [],
    }))
    task = audit_run(tmp_path)["tasks"][0]
    assert task["failure_category"] == "budget_exhausted"
    assert task["exit_status"] == "RecoveredPatch" and task["agent_exit_status"] == "LimitsExceeded"
    assert task["budget"]["limit_reason"] == "steps"
    assert task["trace_matches_prediction"] is True


def test_manifest_exposes_unstarted_tasks_and_foreign_trajectories(tmp_path):
    (tmp_path / "run_manifest.json").write_text(json.dumps({"run_id": "current", "instance_ids": ["one", "two"]}))
    (tmp_path / "preds.json").write_text(json.dumps([{"instance_id": "one", "model_patch": ""}]))
    (tmp_path / "one.traj.json").write_text(
        json.dumps(
            {
                "instance_id": "one",
                "run_id": "another-run",
                "info": {"submission": ""},
                "messages": [],
            }
        )
    )
    audit = audit_run(tmp_path)
    assert audit["run_id"] == "current"
    assert audit["summary"]["tasks"] == 2
    assert audit["tasks"][0]["trace_matches_prediction"] is False
    assert "run_id_mismatch" in audit["tasks"][0]["issues"]
    assert audit["tasks"][1]["issues"] == ["missing_prediction", "missing_trajectory", "missing_evaluation"]
