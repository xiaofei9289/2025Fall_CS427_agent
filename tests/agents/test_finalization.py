import json
import subprocess

import pytest

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models.test_models import DeterministicModel
from minisweagent.run.extra.swebench import finalize_submission
from minisweagent.run.utils.save import save_traj


def test_model_response_error_recovers_patch_without_exporting_diagnostic():
    from unittest.mock import Mock

    patch = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new\n"
    env = Mock()
    env.execute.return_value = {"output": patch, "returncode": 0}
    result, status = finalize_submission("Provider returned 3 consecutive empty responses.", env, "ModelResponseError")
    assert (result, status) == (patch, "RecoveredPatch")
    env.execute.return_value = {"output": "", "returncode": 0}
    assert finalize_submission("Provider returned content_filter.", env, "ModelResponseError") == ("", "ModelResponseError")


def test_finalization_notice_and_hard_limit_are_saved(tmp_path):
    agent = DefaultAgent(
        DeterministicModel(outputs=["```bash\necho inspecting\n```"] * 3, cost_per_call=0.01),
        LocalEnvironment(cwd=str(tmp_path)), step_limit=3, finalization_step_reserve=2,
    )
    status, message = agent.run("Fix the issue")
    assert status == "LimitsExceeded" and "steps" in message
    assert agent.model.n_calls == 3
    notices = [i for i, row in enumerate(agent.messages) if row["content"].startswith("FINALIZATION:")]
    assert len(notices) == 1
    assert sum(row["role"] == "assistant" for row in agent.messages[:notices[0]]) == 1
    path = tmp_path / "trajectory.json"
    save_traj(agent, path, exit_status=status, result=message, print_path=False)
    budget = json.loads(path.read_text())["info"]["budget"]
    assert budget["phase"] == "finalizing" and budget["limit_reason"] == "steps"
    assert budget["remaining_steps"] == 0


@pytest.mark.parametrize(("dimension", "options"), [
    ("cost", {"cost_limit": 0.03, "finalization_cost_reserve": 0.03}),
    ("seconds", {"time_limit": 300, "finalization_time_reserve": 300}),
])
def test_cost_and_time_reserves_do_not_add_model_calls(dimension, options):
    agent = DefaultAgent(
        DeterministicModel(outputs=["```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"], cost_per_call=0.01),
        LocalEnvironment(), **options,
    )
    assert agent.run("Finish")[0] == "Submitted"
    assert agent.model.n_calls == 1
    assert sum(row["content"].startswith("FINALIZATION:") for row in agent.messages) == 1
    assert agent.budget_state()["limit_reason"] == ""
    assert agent.budget_state()[f"remaining_{dimension}"] > 0


def test_budget_stop_recovers_applicable_patch_and_keeps_empty_patch_empty(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    source = package / "app.py"
    source.write_text("value = 1\n")
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.org",
                    "commit", "-m", "fixture"], check=True, capture_output=True)
    env = LocalEnvironment(cwd=str(tmp_path))
    empty, status = finalize_submission("Budget exhausted: steps", env, "LimitsExceeded")
    assert empty == "" and status == "LimitsExceeded"
    agent = DefaultAgent(
        DeterministicModel(outputs=["```bash\nprintf 'value = 2\\n' > pkg/app.py\n```"], cost_per_call=0.01),
        env, step_limit=1, finalization_step_reserve=1,
    )
    status, message = agent.run("Change value to 2")
    patch, recovered_status = finalize_submission(message, env, status)
    assert status == "LimitsExceeded" and recovered_status == "RecoveredPatch"
    assert "+value = 2" in patch and "Budget exhausted" not in patch
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "--", "pkg/app.py"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "apply", "--check", "-"], input=patch, text=True, check=True)
