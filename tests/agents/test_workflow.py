import json
import shlex
import subprocess
import sys

import minisweagent.tools.basic  # noqa: F401
from minisweagent.agents.workflow import RepairAgent, RepairAgentConfig, RepairWorkflow
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models.test_models import DeterministicModel


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path, app="def add(a, b):\n    return a - b\n", test=True):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text(app)
    if test:
        (repo / "tests").mkdir()
        (repo / "tests" / "test_app.py").write_text(
            "from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
        )
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "base")
    return repo


def _tool(name, **args):
    return f"```tool\n{json.dumps({'name': name, 'args': args})}\n```"


def _submit():
    return "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && git diff HEAD\n```"


def _agent(repo, tmp_path, outputs, **options):
    config = {
        "workflow_enabled": True,
        "workflow_mode": "strict",
        "artifact_dir": str(tmp_path / "artifacts"),
        "step_limit": 10,
        "cost_limit": 0.0,
        **options,
    }
    return RepairAgent(
        DeterministicModel(outputs=outputs, cost_per_call=0.0),
        LocalEnvironment(cwd=str(repo)),
        **config,
    )


def test_failed_test_then_patch_then_passing_verification_is_recorded(tmp_path):
    repo = _repo(tmp_path)
    command = f"{sys.executable} -m pytest -q tests/test_app.py"
    run = _tool("run_tests", command=command)
    patch = _tool("write_file", path="app.py", content="def add(a, b):\n    return a + b\n")
    agent = _agent(repo, tmp_path, ["reproduce\n" + run, "patch\n" + patch, "verify\n" + run, _submit()])

    status, result = agent.run("Fix add")

    assert status == "Submitted"
    assert "+    return a + b" in result
    assert agent.workflow.state.baseline.status.value == "test_failed"
    assert agent.workflow.state.last_run.status.value == "passed"
    state = json.loads((tmp_path / "artifacts" / "repair_state.json").read_text())
    assert state["verification"]["status"] == "verified"
    assert state["phase"] == "done"
    lines = (tmp_path / "artifacts" / "verification.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["local_verification"]["status"] == "baseline_recorded"
    assert (tmp_path / "artifacts" / "repair_diff.patch").read_text().endswith("\n")


def test_strict_mode_blocks_then_fails_open_after_attempt_limit(tmp_path):
    repo = _repo(tmp_path, test=False)
    patch = _tool("write_file", path="app.py", content="value = 2\n")
    agent = _agent(repo, tmp_path, ["patch\n" + patch, _submit(), _submit(), _submit()], max_verify_attempts=2)

    status, result = agent.run("Change the value")

    assert status == "Submitted"
    assert "+value = 2" in result
    blocks = [
        m["content"]
        for m in agent.messages
        if m["role"] == "user" and "WORKFLOW: submission blocked" in m.get("content", "")
    ]
    assert len(blocks) == 2
    assert "inconclusive: no baseline test run" in blocks[0]
    summary = json.loads((tmp_path / "artifacts" / "run_summary.json").read_text())
    assert summary["verification"]["status"] == "inconclusive"
    assert agent.workflow.state.verify_attempts == 3


def test_empty_patch_blocks_once_then_allows(tmp_path):
    repo = _repo(tmp_path, test=False)
    env = LocalEnvironment(cwd=str(repo))
    workflow = RepairWorkflow(
        RepairAgentConfig(
            workflow_enabled=True,
            workflow_mode="strict",
            artifact_dir=str(tmp_path / "artifacts"),
            max_verify_attempts=1,
        )
    )
    workflow.begin(env)
    first = workflow.before_submit(env)
    second = workflow.before_submit(env)
    third = workflow.before_submit(env)

    assert first.allow is False and first.status == "empty_patch"
    assert second.allow is False
    assert third.allow is True
    assert "sanitized patch is empty" in first.message


def test_acceptance_command_runs_automatically_on_submit(tmp_path):
    repo = _repo(tmp_path)
    patch = _tool("write_file", path="app.py", content="def add(a, b):\n    return a + b\n")
    command = f"{shlex.quote(sys.executable)} -m pytest -q tests/test_app.py"
    agent = _agent(
        repo,
        tmp_path,
        ["patch\n" + patch, _submit()],
        acceptance_command=command,
        max_verify_attempts=1,
    )

    status, result = agent.run("Fix add")

    assert status == "Submitted"
    assert "+    return a + b" in result
    summary = json.loads((tmp_path / "artifacts" / "run_summary.json").read_text())
    assert summary["verification"]["status"] == "acceptance_passed"
    assert summary["exit_status"] == "Submitted"


def test_disabled_workflow_does_not_install_tool_or_write_artifacts(tmp_path):
    repo = _repo(tmp_path, test=False)
    agent = RepairAgent(
        DeterministicModel(outputs=["```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"]),
        LocalEnvironment(cwd=str(repo)),
        workflow_enabled=False,
        artifact_dir=str(tmp_path / "artifacts"),
    )
    status, _ = agent.run("Finish")
    assert status == "Submitted"
    assert "run_tests" not in agent.tools
    assert not (tmp_path / "artifacts").exists()


def test_run_tests_can_be_named_in_enabled_tools(tmp_path):
    repo = _repo(tmp_path, test=False)
    agent = _agent(
        repo,
        tmp_path,
        ["```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"],
        enabled_tools=["run_tests"],
        workflow_mode="advisory",
    )
    assert "run_tests" in agent.tools
    assert agent.config.enabled_tools == []


def test_run_tests_timeout_is_clamped_to_remaining_time(tmp_path):
    class Spy:
        name = "run_tests"
        description = "spy"
        parameters = {}
        args = None

        def __call__(self, args, env=None):
            self.args = args
            return {"output": "ok", "returncode": 0}

    repo = _repo(tmp_path, test=False)
    agent = RepairAgent(
        DeterministicModel(outputs=[]),
        LocalEnvironment(cwd=str(repo)),
        workflow_enabled=True,
        workflow_mode="advisory",
        artifact_dir=str(tmp_path / "artifacts"),
        time_limit=10,
    )
    spy = Spy()
    agent.tools["run_tests"] = spy
    agent.execute_action({"kind": "tool", "tool_name": "run_tests", "tool_args": {"command": "pytest", "timeout": 600}})
    assert spy.args is not None
    assert 1 <= spy.args["timeout"] <= 5


def test_submission_uses_canonical_diff_including_untracked_source(tmp_path):
    repo = _repo(tmp_path, test=False)
    patch = _tool("write_file", path="pkg/new.py", content="VALUE = 2\n")
    agent = _agent(repo, tmp_path, ["patch\n" + patch, _submit()], workflow_mode="advisory")

    status, result = agent.run("Add a module")

    assert status == "Submitted"
    assert "diff --git a/pkg/new.py b/pkg/new.py" in result
    assert "+VALUE = 2" in result
