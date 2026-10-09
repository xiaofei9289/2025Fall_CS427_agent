import json
from pathlib import Path

import pytest

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment


class DummyModel:
    def __init__(self, content: str):
        self._content = content
        self.cost = 0.0
        self.n_calls = 0
        self.config = None

    def query(self, messages):
        self.n_calls += 1
        return {"content": self._content}

    def get_template_vars(self):
        return {}


def test_agent_executes_tool_write_and_read(tmp_path, monkeypatch):
    # Ensure tools are registered
    import minisweagent.tools.basic  # noqa: F401

    target = tmp_path / "file.txt"

    # 1) Write file via tool
    write_payload = json.dumps({"name": "write_file", "args": {"path": str(target), "content": "hello"}})
    model = DummyModel(f"""```tool\n{write_payload}\n```""")
    agent = DefaultAgent(model, LocalEnvironment())
    obs = agent.get_observation({"content": model._content})
    assert target.exists()
    assert obs["returncode"] == 0

    # 2) Read file via tool
    read_payload = json.dumps({"name": "read_file", "args": {"path": str(target)}})
    model2 = DummyModel(f"""```tool\n{read_payload}\n```""")
    agent2 = DefaultAgent(model2, LocalEnvironment())
    obs2 = agent2.get_observation({"content": model2._content})
    assert obs2["returncode"] == 0
    assert obs2["output"] == "hello"

