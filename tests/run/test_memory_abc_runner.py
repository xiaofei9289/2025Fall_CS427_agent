from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

STUDY = Path(__file__).resolve().parents[2] / "experiments" / "memory_abc_20261019"
sys.path.insert(0, str(STUDY))
SPEC = importlib.util.spec_from_file_location("memory_abc_run", STUDY / "run.py")
assert SPEC and SPEC.loader
run = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = run
SPEC.loader.exec_module(run)

DIFF = "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"


class FakeModel:
    def __init__(self):
        self.responses = [
            "```bash\ncat src/app.py\n```",
            "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && git diff HEAD\n```",
        ]
        self.cost = 0.0
        self.n_calls = 0
        self.config = {"model_name": "fake"}

    def query(self, messages, **kwargs):
        self.n_calls += 1
        self.cost += 0.001
        return {"content": self.responses.pop(0), "extra": {"response": {"usage": {"prompt_tokens": 100}}}}

    def get_template_vars(self):
        return {}


class FakeEnv:
    def __init__(self):
        self.config = {"cwd": "/testbed"}
        self.cleaned = False

    def execute(self, command, cwd=""):
        if "COMPLETE_TASK" in command:
            return {"output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n" + DIFF, "returncode": 0}
        return {"output": "source code", "returncode": 0}

    def get_template_vars(self):
        return {}

    def cleanup(self):
        self.cleaned = True


def test_process_instance_writes_predictions_trajectory_and_trace(tmp_path, monkeypatch):
    env = FakeEnv()
    model = FakeModel()
    monkeypatch.setattr(run, "get_model", lambda **kwargs: model)
    monkeypatch.setattr(run, "get_sb_environment", lambda config, instance: env)
    instance = {
        "instance_id": "django__django-15315",
        "problem_statement": "fix the parser",
        "repo": "django/django",
        "base_commit": "abc",
        "version": "1",
    }
    output = tmp_path / "a"
    run.process_instance(instance, output, run.load_arm("a"), "run-id")
    predictions = json.loads((output / "preds.json").read_text())
    assert predictions[instance["instance_id"]]["model_patch"].startswith("diff --git ")
    trajectory = json.loads((output / instance["instance_id"] / f"{instance['instance_id']}.traj.json").read_text())
    assert trajectory["info"]["exit_status"] == "Submitted"
    assert trajectory["info"]["agent_exit_status"] == "Submitted"
    trace = (output / instance["instance_id"] / "memory_trace.jsonl").read_text().splitlines()
    assert trace
    assert env.cleaned is True
