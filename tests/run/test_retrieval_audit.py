import json
from pathlib import Path

from minisweagent.run.extra.retrieval_audit import audit, audit_trajectory, classify


def trajectory(*, search_path="src/a.py", read=False, submission="diff --git a/src/a.py b/src/a.py\n", instance="t1"):
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "issue"},
        {
            "role": "assistant",
            "content": 'THOUGHT: search\n\n```tool\n{"name": "code_search", "args": {"query": "refresh token"}}\n```',
        },
        {
            "role": "user",
            "content": '<returncode>0</returncode>\n<output>'
            + json.dumps({"matches": [{"path": search_path}, {"path": "src/other.py"}]})
            + "</output>",
        },
    ]
    if read:
        messages.extend(
            [
                {"role": "assistant", "content": '```tool\n{"name": "read_file", "args": {"path": "src/a.py"}}\n```'},
                {"role": "user", "content": "file content"},
            ]
        )
    messages.extend(
        [
            {
                "role": "assistant",
                "content": "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && git diff HEAD\n```",
            },
            {"role": "user", "content": "submitted"},
        ]
    )
    return {
        "instance_id": instance,
        "messages": messages,
        "info": {"exit_status": "Submitted", "submission": submission, "model_stats": {"api_calls": 4, "instance_cost": 0.1}},
    }


def test_audit_trajectory_resolved_path() -> None:
    result = audit_trajectory(trajectory(read=True), gold_files={"src/a.py"}, resolved=True)
    assert result["gold_rank"] == 1
    assert result["gold_in_top_k"] is True
    assert result["read_gold"] is True
    assert result["edited_gold"] is True
    assert result["classification"] == "resolved"
    assert result["first_search_query"] == "refresh token"


def test_audit_trajectory_distinguishes_miss_and_not_read() -> None:
    miss = audit_trajectory(trajectory(search_path="src/other.py"), gold_files={"src/a.py"}, resolved=False)
    assert miss["gold_rank"] is None
    assert miss["classification"] == "retrieval_miss"

    not_read = audit_trajectory(trajectory(read=False), gold_files={"src/a.py"}, resolved=False)
    assert not_read["gold_rank"] == 1
    assert not_read["read_gold"] is False
    assert not_read["classification"] == "retrieved_not_read"


def test_audit_trajectory_read_but_not_edited() -> None:
    result = audit_trajectory(
        trajectory(read=True, submission=""),
        gold_files={"src/a.py"},
        resolved=False,
    )
    assert result["read_gold"] is True
    assert result["edited_gold"] is False
    assert result["classification"] == "read_not_edited"


def test_audit_directory_and_markdown(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    task_dir = run_dir / "t1"
    task_dir.mkdir(parents=True)
    (task_dir / "t1.traj.json").write_text(json.dumps(trajectory(read=True, instance="t1")))
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([{"instance_id": "t1", "gold_files": ["src/a.py"]}]))
    grading = tmp_path / "grading.json"
    grading.write_text(json.dumps({"resolved_ids": ["t1"]}))
    result = audit(run_dir, cases_path=cases, grading_path=grading, k=10)
    assert result["summary"]["tasks"] == 1
    assert result["summary"]["resolved"] == 1
    assert result["summary"]["gold_in_top_k"] == 1
    assert result["tasks"][0]["classification"] == "resolved"


def test_classify_no_search_and_no_gold() -> None:
    assert classify(resolved=False, first_search=None, gold_rank=None, read_gold=False, edited_gold=False, has_gold=True) == "no_search"
    assert classify(resolved=False, first_search=None, gold_rank=None, read_gold=False, edited_gold=False, has_gold=False) == "no_gold"
