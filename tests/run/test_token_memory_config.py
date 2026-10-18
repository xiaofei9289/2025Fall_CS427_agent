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
