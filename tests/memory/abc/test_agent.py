from __future__ import annotations

import json
from types import SimpleNamespace

from minisweagent.memory.abc.agent import MemoryAgent, MemoryAgentConfig
from minisweagent.memory.abc.budget import estimate_tokens


class FakeModel:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []
        self.cost = 0.0
        self.n_calls = 0
        self.config = SimpleNamespace(model_name="fake")

    def query(self, messages, **kwargs):
        self.calls.append([dict(message) for message in messages])
        self.n_calls += 1
        self.cost += 0.001
        content = self.responses.pop(0) if self.responses else "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"
        return {
            "content": content,
            "extra": {"response": {"usage": {"prompt_tokens": estimate_tokens(messages)}}},
        }

    def get_template_vars(self):
        return {}


class FakeEnv:
    config = SimpleNamespace(cwd="/testbed", timeout=60)

    def __init__(self, output_chars=700):
        self.output_chars = output_chars
        self.commands: list[str] = []

    def execute(self, command, cwd=""):
        self.commands.append(command)
        if "COMPLETE_TASK" in command:
            return {"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n", "returncode": 0}
        return {"output": "OBSERVATION " + "x" * self.output_chars, "returncode": 0}

    def get_template_vars(self):
        return {}


def responses(turns=8):
    return [f"```bash\ncat src/file{index}.py\n```" for index in range(turns)]


def config(tmp_path, policy="window", total=1200, summary=300, retrieval=200):
    return MemoryAgentConfig(
        system_template="SYSTEM PROMPT",
        instance_template="TASK: {{task}}",
        action_observation_template="{{output.output}}",
        step_limit=20,
        cost_limit=10.0,
        enabled_tools=[],
        memory_policy=policy,
        memory_total_tokens=total,
        memory_summary_tokens=summary,
        memory_retrieval_tokens=retrieval,
        memory_trace_path=str(tmp_path / "memory_trace.jsonl"),
    )


def read_trace(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_window_agent_keeps_task_and_has_no_summary(tmp_path):
    model = FakeModel(responses())
    agent = MemoryAgent(model, FakeEnv(), **config(tmp_path, "window").__dict__)
    status, _ = agent.run("fix the parser")
    assert status == "Submitted"
    assert model.calls
    for call in model.calls:
        assert any("TASK: fix the parser" in message["content"] for message in call)
        assert estimate_tokens(call) <= 1200
    trace = read_trace(tmp_path / "memory_trace.jsonl")
    assert trace
    assert all(record["task_present"] for record in trace)
    assert all(record["summary_tokens"] == 0 for record in trace)
    assert all(not record["summary_present"] for record in trace)


def test_summary_agent_adds_a_bounded_summary(tmp_path):
    model = FakeModel(responses())
    agent = MemoryAgent(model, FakeEnv(), **config(tmp_path, "summary").__dict__)
    status, _ = agent.run("fix the parser")
    assert status == "Submitted"
    summaries = [
        message["content"]
        for call in model.calls
        for message in call
        if message["content"].startswith("[memory]")
    ]
    assert summaries
    assert all(len(summary) > 0 for summary in summaries)
    trace = read_trace(tmp_path / "memory_trace.jsonl")
    assert any(record["summary_present"] for record in trace)
    assert all(record["summary_tokens"] <= 300 for record in trace)
    for call in model.calls:
        assert any("TASK: fix the parser" in message["content"] for message in call)
        assert estimate_tokens(call) <= 1200


def test_search_agent_has_the_tool_and_a_bounded_result(tmp_path):
    responses_with_search = responses(turns=4) + [
        '```tool\n{"name": "memory_search", "args": {"query": "OBSERVATION", "mode": "full", "limit": 1}}\n```'
    ] + responses(turns=2)
    model = FakeModel(responses_with_search)
    agent = MemoryAgent(model, FakeEnv(), **config(tmp_path, "summary_search", retrieval=120).__dict__)
    status, _ = agent.run("fix the parser")
    assert status == "Submitted"
    assert "memory_search" in agent.tools
    assert any(spec["name"] == "memory_search" for spec in agent.extra_template_vars["tool_specs"])
    trace = read_trace(tmp_path / "memory_trace.jsonl")
    assert any(record["retrieval_tokens"] > 0 for record in trace)
    assert all(record["retrieval_tokens"] <= 120 for record in trace)
    # The search choice is one model call/step, like any other action.
    search_calls = [call for call in model.calls if any("memory_search" in m["content"] for m in call)]
    assert search_calls


def test_window_and_summary_have_no_search_tool(tmp_path):
    for policy in ("window", "summary"):
        agent = MemoryAgent(FakeModel([]), FakeEnv(), **config(tmp_path, policy).__dict__)
        assert "memory_search" not in agent.tools
        assert all(spec["name"] != "memory_search" for spec in agent.extra_template_vars["tool_specs"])


def test_budget_error_is_reported_not_hidden(tmp_path):
    model = FakeModel([])
    settings = config(tmp_path, "window", total=500, summary=100, retrieval=100)
    settings.instance_template = "TASK: " + "T" * 4000
    agent = MemoryAgent(model, FakeEnv(), **settings.__dict__)
    status, message = agent.run("unused")
    assert status == "MemoryBudgetError"
    assert "budget" in message.lower()


def test_full_agent_does_not_enforce_the_prompt_budget(tmp_path):
    model = FakeModel(responses())
    agent = MemoryAgent(model, FakeEnv(), **config(tmp_path, "full", total=200, summary=50, retrieval=50).__dict__)
    status, _ = agent.run("fix the parser")
    assert status == "Submitted"
    trace = read_trace(tmp_path / "memory_trace.jsonl")
    assert trace
    assert all(record["budget_enforced"] is False for record in trace)
    assert any(record["budget"] > 200 for record in trace)
    assert all(record["task_present"] for record in trace)
