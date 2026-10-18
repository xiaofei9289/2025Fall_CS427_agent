import json

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment
from minisweagent.memory.history import estimate_tokens


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
    # File tools restrict paths to the environment workspace, so run inside tmp_path
    agent = DefaultAgent(model, LocalEnvironment(cwd=str(tmp_path)))
    obs = agent.get_observation({"content": model._content})
    assert target.exists()
    assert obs["returncode"] == 0

    # 2) Read file via tool
    read_payload = json.dumps({"name": "read_file", "args": {"path": str(target)}})
    model2 = DummyModel(f"""```tool\n{read_payload}\n```""")
    agent2 = DefaultAgent(model2, LocalEnvironment(cwd=str(tmp_path)))
    obs2 = agent2.get_observation({"content": model2._content})
    assert obs2["returncode"] == 0
    assert obs2["output"] == "hello"


def test_token_limit_sends_fitted_view_and_keeps_full_transcript(tmp_path):
    model = DummyModel("```bash\necho ok\n```")
    seen = {}

    def query(messages):
        seen["messages"] = messages
        model.n_calls += 1
        return {"content": model._content}

    model.query = query
    agent = DefaultAgent(
        model,
        LocalEnvironment(cwd=str(tmp_path)),
        context_token_limit=80,
        history_policy="compress",
    )
    agent.messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "TASK-KEEP"},
        {"role": "assistant", "content": "```bash\necho old\n```"},
        {"role": "user", "content": "DROPME " + ("x" * 500)},
        {"role": "assistant", "content": "```bash\necho new\n```"},
        {"role": "user", "content": "y" * 200},
    ]
    agent.query()
    assert estimate_tokens(seen["messages"]) <= 80
    assert any(message["content"] == "TASK-KEEP" for message in seen["messages"])
    assert any("DROPME" in message["content"] for message in agent.messages)
