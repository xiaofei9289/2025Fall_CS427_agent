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
    assert set(result["methods"]) == {"file_bm25", "symbol_bm25", "context", "brief"}
    for method in result["methods"].values():
        assert method == {"recall_at_k": 0.25, "hit_at_k": 0.5, "reciprocal_rank": 0.5}
    assert [row["top_files"] for row in result["tasks"] if row["instance_id"] == "miss"] == [[], [], [], []]
    assert len(result["index_stats"]) == 1
    with pytest.raises(ValueError, match="No gold files"):
        evaluate([{**cases[0], "gold_files": []}], tmp_path)


def test_checkouts_root_overrides_case_repo_paths(tmp_path):
    checkout = tmp_path / "checkouts" / "case1"
    checkout.mkdir(parents=True)
    (checkout / "token.py").write_text("def refresh_token(token):\n    return token\n")
    cases = [{"instance_id": "case1", "repo": "missing", "issue": "refresh_token", "gold_files": ["token.py"]}]
    result = evaluate(cases, tmp_path, k=1, checkouts_root=tmp_path / "checkouts")
    assert result["checkouts_root"] == str(tmp_path / "checkouts")
    assert result["methods"]["file_bm25"]["hit_at_k"] == 1.0
