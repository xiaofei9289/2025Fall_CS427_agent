import pytest

from minisweagent.run.extra.localization_eval import evaluate


def test_metrics_include_misses_and_multifile_gold_without_using_gold_in_query(tmp_path):
    (tmp_path / "token.py").write_text("def refresh_token(token):\n    return token\n")
    (tmp_path / "date.py").write_text("def parse_date(value):\n    return value\n")
    cases = [
        {"instance_id": "hit", "repo": ".", "issue": "refresh_token", "gold_files": ["token.py", "date.py"]},
        {"instance_id": "miss", "repo": ".", "issue": "unfindableqzx", "gold_files": ["token.py"]},
    ]
    result = evaluate(cases, tmp_path, k=1)
    for method in result["methods"].values():
        assert method == {"recall_at_k": 0.25, "hit_at_k": 0.5, "reciprocal_rank": 0.5}
    assert [row["top_files"] for row in result["tasks"][2:]] == [[], []]
    assert len(result["index_stats"]) == 1
    with pytest.raises(ValueError, match="No gold files"):
        evaluate([{**cases[0], "gold_files": []}], tmp_path)
