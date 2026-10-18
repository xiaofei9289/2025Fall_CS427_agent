import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from minisweagent.service.api import ServiceSettings, create_app
from minisweagent.service.store import TaskStore

SUBMIT = "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"
FIX = '```tool\n' + json.dumps({"name": "write_file", "args": {
    "path": "app.py", "content": "def add(a, b):\n    return a + b\n",
}}) + '\n```'


def make_settings(root: Path, outputs: list[str], *, test_command: str = "", workers: int = 1) -> ServiceSettings:
    repo = root / "repos" / "fixture"
    repo.mkdir(parents=True)
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "test_add.py").write_text("from app import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.org",
                    "commit", "-m", "fixture"], check=True, capture_output=True)
    config = root / "service.yaml"
    config.write_text(yaml.safe_dump({
        "agent": {"step_limit": 10, "cost_limit": 1, "time_limit": 30},
        "model": {"model_name": "deterministic", "model_class": "deterministic", "outputs": outputs,
                  "cost_per_call": 0.01},
        "environment": {"environment_class": "local", "timeout": 10},
        "test_command": test_command or f"{shlex.quote(sys.executable)} -m pytest -q", "test_timeout": 15,
    }))
    return ServiceSettings(data_dir=root / "data", repo_root=root / "repos", config_path=config, workers=workers)


def create_task(client: TestClient, settings: ServiceSettings, **kwargs) -> dict:
    response = client.post("/tasks", json={"repo": str(settings.repo_root / "fixture"), "issue": "Fix add", **kwargs})
    assert response.status_code == 202, response.text
    return response.json()


def wait_task(client: TestClient, task_id: str, statuses: set[str]) -> dict:
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in statuses:
            return task
        time.sleep(0.05)
    pytest.fail(f"Task timed out: {task}")


def wait_for_action(settings: ServiceSettings, task_id: str) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if (settings.data_dir / task_id / "workspace" / "visits.txt").exists():
            return
        time.sleep(0.05)
    pytest.fail("Worker did not start the action")


def test_real_execution_persistence_and_events(tmp_path):
    settings = make_settings(tmp_path, [FIX, SUBMIT])
    with TestClient(create_app(settings)) as client:
        task = create_task(client, settings)
        task_id = task["id"]
        task = wait_task(client, task_id, {"succeeded", "failed", "interrupted"})
        assert task["status"] == "succeeded", task
        assert task["result"]["test_returncode"] == 0
        assert task["result"]["n_calls"] == 2
        assert task["result"]["cost"] == pytest.approx(0.02)
        assert "config" not in task
        assert "return a - b" in (settings.repo_root / "fixture" / "app.py").read_text()
        assert "return a + b" in client.get(f"/tasks/{task_id}/artifacts/patch.diff").text
        assert "1 passed" in client.get(f"/tasks/{task_id}/artifacts/verification.txt").text
        events = client.get(f"/tasks/{task_id}/events").json()
        assert {"queued", "started", "model", "action", "verification", "succeeded"} <= {e["kind"] for e in events}
        assert client.get(f"/tasks/{task_id}/events", params={"after": events[-1]["id"]}).json() == []
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/tasks/{task_id}").json()["status"] == "succeeded"
        assert len(client.get("/tasks").json()) == 1


def test_failed_verification_does_not_claim_success(tmp_path):
    settings = make_settings(tmp_path, [FIX, SUBMIT], test_command="exit 2")
    with TestClient(create_app(settings)) as client:
        task = create_task(client, settings)
        result = wait_task(client, task["id"], {"succeeded", "failed"})
        assert result["status"] == "failed" and result["result"]["test_returncode"] == 2
        assert client.get(f"/tasks/{task['id']}/artifacts/patch.diff").status_code == 200


def test_cancel_running_resume_checkpoint_without_replaying_action(tmp_path):
    settings = make_settings(tmp_path, ['```bash\necho once >> visits.txt && sleep 20\n```', FIX, SUBMIT])
    with TestClient(create_app(settings)) as client:
        task = create_task(client, settings)
        task_id = task["id"]
        wait_for_action(settings, task_id)
        assert client.post(f"/tasks/{task_id}/cancel").status_code == 200
        assert wait_task(client, task_id, {"cancelled"})["result"]["n_calls"] == 1
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = client.post(f"/tasks/{task_id}/resume")
            if response.status_code == 202:
                break
            time.sleep(0.05)
        assert response.status_code == 202, response.text
        result = wait_task(client, task_id, {"succeeded", "failed", "interrupted"})
        assert result["status"] == "succeeded", result
        assert result["result"]["n_calls"] == 3
        assert result["result"]["cost"] == pytest.approx(0.03)
        assert (settings.data_dir / task_id / "workspace" / "visits.txt").read_text() == "once\n"
        assert any(event["kind"] == "resumed" for event in client.get(f"/tasks/{task_id}/events").json())


def test_service_shutdown_interrupts_and_restart_can_resume(tmp_path):
    settings = make_settings(tmp_path, ['```bash\necho once >> visits.txt && sleep 20\n```', FIX, SUBMIT])
    config = yaml.safe_load(settings.config_path.read_text())
    config["agent"]["finalization_step_reserve"] = 10
    settings.config_path.write_text(yaml.safe_dump(config))
    with TestClient(create_app(settings)) as client:
        task_id = create_task(client, settings)["id"]
        wait_for_action(settings, task_id)
    assert TaskStore(settings.data_dir).get(task_id)["status"] == "interrupted"
    with TestClient(create_app(settings)) as client:
        assert client.post(f"/tasks/{task_id}/resume").status_code == 202
        task = wait_task(client, task_id, {"succeeded", "failed"})
        assert task["status"] == "succeeded" and task["result"]["n_calls"] == 3
        assert (settings.data_dir / task_id / "workspace" / "visits.txt").read_text() == "once\n"
        trajectory = client.get(f"/tasks/{task_id}/artifacts/trajectory.json").json()
        assert sum(row["content"].startswith("FINALIZATION:") for row in trajectory["messages"]) == 1
        assert task["result"]["budget"]["phase"] == "finalizing"


def test_budget_stop_preserves_candidate_and_verifies_it(tmp_path):
    settings = make_settings(tmp_path, [FIX])
    config = yaml.safe_load(settings.config_path.read_text())
    config["agent"].update(step_limit=1, finalization_step_reserve=1)
    settings.config_path.write_text(yaml.safe_dump(config))
    with TestClient(create_app(settings)) as client:
        task_id = create_task(client, settings)["id"]
        task = wait_task(client, task_id, {"succeeded", "failed"})
        assert task["status"] == "succeeded", task
        assert task["result"]["exit_status"] == "LimitsExceeded"
        assert task["result"]["submission_kind"] == "recovered"
        assert task["result"]["verification_status"] == "passed"
        assert task["result"]["budget"]["limit_reason"] == "steps"
        assert task["result"]["n_calls"] == 1
        assert "return a + b" in client.get(f"/tasks/{task_id}/artifacts/patch.diff").text
        kinds = [event["kind"] for event in client.get(f"/tasks/{task_id}/events").json()]
        assert kinds.index("budget") < kinds.index("candidate") < kinds.index("verification")


def test_candidate_is_downloadable_before_verification_times_out(tmp_path):
    script = "from pathlib import Path; import time; Path('visits.txt').write_text('verifying'); time.sleep(5)"
    settings = make_settings(tmp_path, [FIX, SUBMIT],
                             test_command=f"{shlex.quote(sys.executable)} -c {shlex.quote(script)}")
    config = yaml.safe_load(settings.config_path.read_text())
    config["test_timeout"] = 2
    settings.config_path.write_text(yaml.safe_dump(config))
    with TestClient(create_app(settings)) as client:
        task_id = create_task(client, settings)["id"]
        wait_for_action(settings, task_id)
        assert "return a + b" in client.get(f"/tasks/{task_id}/artifacts/patch.diff").text
        task = wait_task(client, task_id, {"succeeded", "failed"})
        assert task["status"] == "failed" and task["result"]["verification_status"] == "error"
        assert task["result"]["patch_chars"] > 0
        assert task["result"].get("test_returncode") is None


@pytest.mark.parametrize(("budget", "value"), [("step_limit", 1), ("cost_limit", 0.01)])
def test_resume_preserves_call_and_cost_limits(tmp_path, budget, value):
    settings = make_settings(tmp_path, ['```bash\necho once >> visits.txt && sleep 20\n```', FIX, SUBMIT],
                             test_command="exit 2")
    config = yaml.safe_load(settings.config_path.read_text())
    config["agent"][budget] = value
    settings.config_path.write_text(yaml.safe_dump(config))
    with TestClient(create_app(settings)) as client:
        task_id = create_task(client, settings)["id"]
        wait_for_action(settings, task_id)
    with TestClient(create_app(settings)) as client:
        assert client.post(f"/tasks/{task_id}/resume").status_code == 202
        task = wait_task(client, task_id, {"succeeded", "failed"})
        assert task["result"]["exit_status"] == "LimitsExceeded"
        assert task["result"]["n_calls"] == 1 and task["result"]["cost"] == pytest.approx(0.01)


def test_empty_patch_is_not_success(tmp_path):
    settings = make_settings(tmp_path, [SUBMIT], test_command="true")
    with TestClient(create_app(settings)) as client:
        task_id = create_task(client, settings)["id"]
        task = wait_task(client, task_id, {"succeeded", "failed"})
        assert task["status"] == "failed" and task["result"]["test_returncode"] == 0
        assert "empty" in task["error"]


def test_interruption_on_restart_and_queued_cancel(tmp_path):
    settings = make_settings(tmp_path, [FIX, SUBMIT])
    store = TaskStore(settings.data_dir)
    config = yaml.safe_load(settings.config_path.read_text())
    request = {"repo": str(settings.repo_root / "fixture"), "issue": "Fix add", "ref": "", "variant": "baseline"}
    interrupted = store.create(request, config)
    store.transition(interrupted["id"], ("queued",), "running")
    queued = store.create(request, config)
    application = create_app(settings)
    with TestClient(application) as client:
        # Create/cancel before starting the dispatcher to make this transition deterministic.
        assert client.get(f"/tasks/{interrupted['id']}").json()["status"] == "interrupted"
        assert client.post(f"/tasks/{interrupted['id']}/resume").status_code == 202
        assert wait_task(client, interrupted["id"], {"succeeded", "failed"})["status"] == "succeeded"
        assert wait_task(client, queued["id"], {"succeeded", "failed"})["status"] == "succeeded"
    application = create_app(settings)
    client = TestClient(application)
    cancelled = create_task(client, settings)
    assert client.post(f"/tasks/{cancelled['id']}/cancel").json()["status"] == "cancelled"
    assert not (settings.data_dir / cancelled["id"] / "workspace").exists()


def test_auth_and_repository_policy(tmp_path):
    settings = make_settings(tmp_path, [FIX, SUBMIT])
    settings.token = "test-token"
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 401
        client.headers["Authorization"] = "Bearer test-token"
        assert client.get("/health").status_code == 200
        for repo in ["/etc", "git@github.com:org/repo", "https://token@github.com/org/repo", "ext::sh dangerous"]:
            assert client.post("/tasks", json={"repo": repo, "issue": "fix"}).status_code == 422
        assert client.post("/tasks", json={"repo": str(settings.repo_root / "fixture"), "issue": "fix",
                                           "model": "untrusted"}).status_code == 422
        assert client.post("/tasks", json={"repo": str(settings.repo_root / "fixture"), "issue": "fix",
                                           "ref": "--help"}).status_code == 422


def test_parallel_tasks_use_separate_workspaces(tmp_path):
    settings = make_settings(tmp_path, [FIX, SUBMIT], workers=2)
    with TestClient(create_app(settings)) as client:
        first, second = create_task(client, settings), create_task(client, settings)
        for task in (first, second):
            assert wait_task(client, task["id"], {"succeeded", "failed"})["status"] == "succeeded"
        assert first["id"] != second["id"]
        assert (settings.data_dir / first["id"] / "workspace" / "app.py").read_text() == (
            settings.data_dir / second["id"] / "workspace" / "app.py"
        ).read_text()
        assert "return a - b" in (settings.repo_root / "fixture" / "app.py").read_text()
