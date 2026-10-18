from pathlib import Path

import yaml

STUDY = Path(__file__).resolve().parents[2] / "experiments" / "deepseek_token_memory_20261018"


def test_token_memory_configs_share_every_control_except_the_treatment():
    off = yaml.safe_load((STUDY / "off.yaml").read_text())
    on = yaml.safe_load((STUDY / "on.yaml").read_text())
    assert off["agent"].pop("history_policy") == "truncate"
    assert on["agent"].pop("history_policy") == "compress"
    assert off["agent"]["context_token_limit"] == on["agent"]["context_token_limit"] == 8000
    assert "memory_search" not in off["agent"]["enabled_tools"]
    on["agent"]["enabled_tools"].remove("memory_search")
    assert off == on


def test_summary_only_arm_differs_from_the_search_arm_only_by_the_tool():
    """The optional third arm isolates the summary from the retrieval tool."""
    on = yaml.safe_load((STUDY / "on.yaml").read_text())
    summary = yaml.safe_load((STUDY / "on_summary_only.yaml").read_text())
    assert summary["agent"]["history_policy"] == "compress"
    assert summary["agent"]["context_token_limit"] == on["agent"]["context_token_limit"]
    assert "memory_search" not in summary["agent"]["enabled_tools"]
    summary["agent"]["enabled_tools"].append("memory_search")
    assert summary == on
