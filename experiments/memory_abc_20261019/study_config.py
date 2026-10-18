"""Loading and validating the A/B/C study configuration.

The three arms share one base YAML.  Each arm file may set exactly one field,
``agent.memory_policy``; this module rejects any other difference.  That keeps
"same source, model, prompt, ordinary tools, task set, and budget" a structural
property rather than a convention.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

STUDY = Path(__file__).resolve().parent
CONFIG_DIR = STUDY / "configs"
ARM_POLICY = {"a": "window", "b": "summary", "c": "summary_search"}
ARMS = tuple(ARM_POLICY)


class ConfigError(ValueError):
    """The arm configuration violates the pre-registered controls."""


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` into a copy of ``base``."""
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _only_treatment(overlay: dict[str, Any], arm: str) -> None:
    if set(overlay) != {"agent"}:
        raise ConfigError(f"{arm}.yaml may only override agent; got {sorted(overlay)}")
    agent = overlay["agent"]
    if set(agent) != {"memory_policy"}:
        raise ConfigError(
            f"{arm}.yaml may only set agent.memory_policy; got {sorted(agent)}"
        )
    if agent["memory_policy"] != ARM_POLICY[arm]:
        raise ConfigError(f"{arm}.yaml must set memory_policy={ARM_POLICY[arm]!r}")


def load_arm(arm: str) -> dict[str, Any]:
    """Return the fully merged config for one arm, with structural validation."""
    if arm not in ARM_POLICY:
        raise ConfigError(f"unknown arm {arm!r}; choose from {ARMS}")
    base = yaml.safe_load((CONFIG_DIR / "base.yaml").read_text())
    overlay = yaml.safe_load((CONFIG_DIR / f"{arm}.yaml").read_text())
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        raise ConfigError("config files must contain mappings")
    _only_treatment(overlay, arm)
    merged = deep_merge(base, overlay)

    agent = merged.get("agent", {})
    required = {
        "system_template",
        "instance_template",
        "step_limit",
        "cost_limit",
        "enabled_tools",
        "memory_total_tokens",
        "memory_summary_tokens",
        "memory_retrieval_tokens",
        "memory_policy",
    }
    missing = required - set(agent)
    if missing:
        raise ConfigError(f"agent config missing: {sorted(missing)}")
    if agent["memory_total_tokens"] != 8000:
        raise ConfigError("memory_total_tokens must be the pre-registered 8000")
    if agent["memory_summary_tokens"] != 1000:
        raise ConfigError("memory_summary_tokens must be the pre-registered 1000")
    if agent["memory_retrieval_tokens"] != 1500:
        raise ConfigError("memory_retrieval_tokens must be the pre-registered 1500")
    if "memory_search" in agent["enabled_tools"]:
        raise ConfigError("memory_search is installed by the C policy, not by enabled_tools")
    if merged.get("model", {}).get("model_name") != "deepseek/deepseek-chat":
        raise ConfigError("the pre-registered model is deepseek/deepseek-chat")
    return merged


def normalized_controls(config: dict[str, Any]) -> dict[str, Any]:
    """Return a copy without the treatment field, for equality checks."""
    controls = copy.deepcopy(config)
    controls["agent"].pop("memory_policy", None)
    controls["agent"].pop("memory_trace_path", None)
    return controls


def study_digest() -> str:
    """Hash the study's own code and configs, not just the library source."""
    files = [
        STUDY / "run.py",
        STUDY / "analysis.py",
        STUDY / "study_config.py",
        STUDY / "desktop.py",
        STUDY / "tasks.json",
        STUDY / "pilot.json",
    ]
    files += sorted((CONFIG_DIR).glob("*.yaml"))
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.name.encode() + b"\0" + file.read_bytes() + b"\0")
    return digest.hexdigest()


def load_tasks(*, pilot: bool = False) -> list[str]:
    name = "pilot.json" if pilot else "tasks.json"
    tasks = json.loads((STUDY / name).read_text())
    if not isinstance(tasks, list) or not all(isinstance(task, str) for task in tasks):
        raise ConfigError(f"{name} must be a JSON list of instance ids")
    if len(tasks) != len(set(tasks)):
        raise ConfigError(f"{name} contains duplicates")
    if pilot:
        full = json.loads((STUDY / "tasks.json").read_text())
        if tasks != full[: len(tasks)]:
            raise ConfigError("pilot.json must be the prefix of tasks.json")
    return tasks
