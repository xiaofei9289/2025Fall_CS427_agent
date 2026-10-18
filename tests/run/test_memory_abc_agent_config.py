from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

# Register the ordinary tools used by the real config.
import minisweagent.tools.basic  # noqa: F401
import minisweagent.tools.find_definition  # noqa: F401
import minisweagent.tools.read  # noqa: F401
import minisweagent.tools.read_many  # noqa: F401
import minisweagent.tools.replace  # noqa: F401
import minisweagent.tools.search  # noqa: F401
from minisweagent.memory.abc import MemoryAgent
from minisweagent.memory.abc.budget import estimate_tokens

STUDY = Path(__file__).resolve().parents[2] / "experiments" / "memory_abc_20261019"
SPEC = importlib.util.spec_from_file_location("memory_abc_study_config_agent", STUDY / "study_config.py")
assert SPEC and SPEC.loader
study_config = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = study_config
SPEC.loader.exec_module(study_config)

TASK = "UNIQUE_TASK_MARKER " + ("Fix the parser regression. " * 50)


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.cost = 0.0
        self.n_calls = 0
        self.config = SimpleNamespace(model_name="fake")

    def query(self, messages, **kwargs):
        self.calls.append([dict(message) for message in messages])
        self.n_calls += 1
        self.cost += 0.001
        content = self.responses.pop(0) if self.responses else "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"
        return {"content": content, "extra": {"response": {"usage": {"prompt_tokens": estimate_tokens(messages)}}}}

    def get_template_vars(self):
        return {}


class FakeEnv:
    config = SimpleNamespace(cwd="/testbed", timeout=60)

    def execute(self, command, cwd=""):
        if "COMPLETE_TASK" in command:
            return {"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", "returncode": 0}
        return {"output": "OBSERVATION " + "x" * 1000, "returncode": 0}

    def get_template_vars(self):
        return {}


def run_arm(tmp_path, arm):
    agent_config = dict(study_config.load_arm(arm)["agent"])
    agent_config["memory_trace_path"] = str(tmp_path / f"{arm}.jsonl")
    responses = [f"```bash\ncat src/file{index}.py\n```" for index in range(35)]
    if arm == "c":
        responses.insert(
            0,
            '```tool\n{"name": "memory_search", "args": {"query": "UNIQUE_TASK_MARKER"}}\n```',
        )
    model = FakeModel(responses)
    agent = MemoryAgent(model, FakeEnv(), **agent_config)
    status, _ = agent.run(TASK)
    assert status == "Submitted"
    return agent, model


def test_real_configs_produce_valid_views(tmp_path):
    for arm in ("a", "b", "c"):
        agent, model = run_arm(tmp_path, arm)
        assert model.calls
        for call in model.calls:
            assert estimate_tokens(call) <= 8000
            assert any("UNIQUE_TASK_MARKER" in message["content"] for message in call)
            for index, message in enumerate(call):
                if message["role"] == "user" and not message["content"].startswith("[memory]"):
                    if "UNIQUE_TASK_MARKER" in message["content"]:
                        continue
                    assert index > 0 and call[index - 1]["role"] == "assistant"
        assert any(spec["name"] == "memory_search" for spec in agent.extra_template_vars["tool_specs"]) == (arm == "c")
        summaries = [
            message["content"]
            for call in model.calls
            for message in call
            if message["content"].startswith("[memory]")
        ]
        assert bool(summaries) == (arm != "a"), f"summary presence wrong for {arm}"
        trace = [line for line in (tmp_path / f"{arm}.jsonl").read_text().splitlines() if line]
        assert trace
