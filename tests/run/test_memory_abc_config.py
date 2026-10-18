from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

STUDY = Path(__file__).resolve().parents[2] / "experiments" / "memory_abc_20261019"
SPEC = importlib.util.spec_from_file_location("memory_abc_study_config", STUDY / "study_config.py")
assert SPEC and SPEC.loader
study_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = study_config
SPEC.loader.exec_module(study_config)


def test_all_arms_share_every_control_but_the_policy():
    configs = {arm: study_config.load_arm(arm) for arm in study_config.ARMS}
    normalized = {arm: study_config.normalized_controls(config) for arm, config in configs.items()}
    assert normalized["a"] == normalized["b"] == normalized["c"]
    assert [configs[arm]["agent"]["memory_policy"] for arm in study_config.ARMS] == [
        "window",
        "summary",
        "summary_search",
    ]


def test_budget_and_tool_controls_are_frozen():
    for arm in study_config.ARMS:
        agent = study_config.load_arm(arm)["agent"]
        assert agent["memory_total_tokens"] == 8000
        assert agent["memory_summary_tokens"] == 1000
        assert agent["memory_retrieval_tokens"] == 1500
        assert agent["step_limit"] == 400
        assert agent["cost_limit"] == 10.0
        assert "memory_search" not in agent["enabled_tools"]
        assert "memory_search" not in agent["system_template"]
        assert "memory_search" not in agent["instance_template"]


def test_pilot_is_exactly_the_prefix_of_the_formal_task_set():
    formal = study_config.load_tasks()
    pilot = study_config.load_tasks(pilot=True)
    assert len(formal) == 50
    assert pilot == formal[:10]


def test_an_arm_overlay_cannot_change_anything_else():
    with pytest.raises(study_config.ConfigError):
        study_config._only_treatment({"agent": {"memory_policy": "window", "step_limit": 5}}, "a")
    with pytest.raises(study_config.ConfigError):
        study_config._only_treatment({"model": {"model_name": "other"}}, "a")
    with pytest.raises(study_config.ConfigError):
        study_config._only_treatment({"agent": {"memory_policy": "summary"}}, "a")


def test_unknown_arm_is_rejected():
    with pytest.raises(study_config.ConfigError):
        study_config.load_arm("d")
