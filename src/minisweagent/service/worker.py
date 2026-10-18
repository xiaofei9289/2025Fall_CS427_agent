"""One isolated workspace and checkpointed agent per worker process."""

import argparse
import fcntl
import json
import os
import signal
import subprocess
import time
from pathlib import Path

import minisweagent.tools.basic  # noqa: F401
import minisweagent.tools.code_search  # noqa: F401
import minisweagent.tools.find_definition  # noqa: F401
import minisweagent.tools.find_references  # noqa: F401
import minisweagent.tools.read  # noqa: F401
import minisweagent.tools.read_many  # noqa: F401
import minisweagent.tools.replace  # noqa: F401
import minisweagent.tools.search  # noqa: F401
from minisweagent.agents.default import DefaultAgent, NonTerminatingException, TerminatingException
from minisweagent.environments import get_environment
from minisweagent.models import get_model
from minisweagent.service.store import TaskStore


class WorkerStopped(BaseException):
    pass


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    temporary.replace(path)


def git(workspace: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(workspace), *args], check=True, capture_output=True, text=True, timeout=120
    ).stdout


def save_patch(workspace: Path, directory: Path) -> int:
    git(workspace, "add", "-N", "--", ".")
    patch = git(workspace, "diff", "HEAD")
    temporary = directory / "patch.tmp"
    temporary.write_text(patch)
    temporary.replace(directory / "patch.diff")
    return len(patch)


class TaskAgent(DefaultAgent):
    def __init__(self, *args, store: TaskStore, task_id: str, **kwargs):
        super().__init__(*args, **kwargs)
        # Mandatory first retrieval belongs to the benchmark; service tasks choose their own actions.
        self.retrieval_gate = set()
        self.store, self.task_id = store, task_id
        self.checkpoint = store.directory(task_id) / "checkpoint.json"
        self.parent = os.getppid()
        self.phase = "ready"
        self.pending = None
        self.exit_status = ""

    def active(self) -> None:
        if os.getppid() != self.parent or self.store.get(self.task_id)["status"] != "running":
            raise WorkerStopped()

    def save(self) -> None:
        write_json(self.checkpoint, {
            "messages": self.messages, "phase": self.phase, "pending": self.pending,
            "exit_status": self.exit_status, "n_calls": self.model.n_calls, "cost": self.model.cost,
            "budget": self.budget_state(),
        })

    def query(self) -> dict:
        self.active()
        self.check_budget()
        if self.budget_phase == "finalizing" and self.store.get(self.task_id)["stage"] != "finalizing":
            self.store.update(self.task_id, stage="finalizing")
            self.store.event(self.task_id, "budget", self.budget_state())
            self.save()
        started, cost = time.monotonic(), self.model.cost
        response = super().query()
        self.pending, self.phase = response, "pending"
        self.save()
        self.store.event(self.task_id, "model", {
            "step": self.model.n_calls, "seconds": time.monotonic() - started,
            "cost": self.model.cost - cost,
            "usage": response.get("extra", {}).get("response", {}).get("usage", {}),
        })
        task_result = self.store.get(self.task_id)["result"]
        self.store.update(self.task_id, result=task_result | {"n_calls": self.model.n_calls, "cost": self.model.cost})
        self.active()
        return response

    def execute_action(self, action: dict) -> dict:
        self.active()
        self.phase = "action_in_progress"
        self.save()
        started = time.monotonic()
        output = None
        try:
            if action["kind"] == "tool":
                tool = self.tools.get(action["tool_name"])
                try:
                    output = tool(action.get("tool_args", {}), self.env) if tool else {
                        "output": f"Unknown tool: {action['tool_name']}", "returncode": 127,
                    }
                except Exception as error:
                    output = {"output": f"Tool error: {error}", "returncode": 1}
                self.has_finished(output)
            else:
                output = super().execute_action(action)
        finally:
            self.store.event(self.task_id, "action", {
                "step": self.model.n_calls, "kind": action["kind"],
                "tool": action.get("tool_name"), "seconds": time.monotonic() - started,
                "returncode": output.get("returncode") if output is not None else None,
                "output_chars": len(output.get("output", "")) if output is not None else None,
            })
        self.active()
        return output

    def run(self, task: str, **kwargs) -> tuple[str, str]:
        self.started_at = time.monotonic()
        task = self._prepare_task(task)
        self.extra_template_vars |= {"task": task, **kwargs}
        if self.checkpoint.exists():
            checkpoint = json.loads(self.checkpoint.read_text())
            self.budget_phase = checkpoint.get("budget", {}).get("phase", "solving")
            self.limit_reason = checkpoint.get("budget", {}).get("limit_reason", "")
            self.messages = checkpoint["messages"]
            self.model.n_calls, self.model.cost = checkpoint["n_calls"], checkpoint["cost"]
            if hasattr(self.model, "current_index"):
                self.model.current_index = self.model.n_calls - 1
            self.phase, self.pending = checkpoint["phase"], checkpoint["pending"]
            self.exit_status = checkpoint["exit_status"]
            if self.exit_status:
                return self.exit_status, "Resumed verification"
            if self.phase == "action_in_progress":
                self.add_message("user", "Execution was interrupted. The previous action may have partially run. "
                                 "Inspect the workspace before making further changes; do not blindly repeat it.")
                self.phase, self.pending = "ready", None
            self.store.event(self.task_id, "resumed", {"n_calls": self.model.n_calls, "cost": self.model.cost})
        else:
            self.add_message("system", self.render_template(self.config.system_template))
            self.add_message("user", self.render_template(self.config.instance_template))
        self.save()
        while True:
            try:
                self.get_observation(self.pending if self.pending is not None else self.query())
            except NonTerminatingException as error:
                self.add_message("user", str(error))
            except TerminatingException as error:
                self.exit_status = type(error).__name__
                self.pending, self.phase = None, "finished"
                self.save()
                return self.exit_status, str(error)
            self.pending, self.phase = None, "ready"
            self.save()


def run_task(store: TaskStore, task_id: str) -> None:
    task = store.get(task_id)
    directory = store.directory(task_id)
    workspace = directory / "workspace"
    environment = agent = None
    result = task["result"].copy()
    result["verification_status"] = "not_run"
    started = time.monotonic()
    status, error = "failed", None

    def stop(_signal, _frame):
        raise WorkerStopped()

    signal.signal(signal.SIGTERM, stop)
    try:
        store.update(task_id, stage="preparing")
        if not workspace.exists():
            subprocess.run(["git", "clone", "--no-local", "--", task["request"]["repo"], str(workspace)],
                           capture_output=True, check=True, timeout=120)
            if task["request"].get("ref"):
                git(workspace, "checkout", "--detach", task["request"]["ref"])
            (workspace / ".git" / "info" / "exclude").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n")
            result["base_commit"] = git(workspace, "rev-parse", "HEAD").strip()
            store.update(task_id, result=result)
        config = task["config"]
        environment_config = config["environment"].copy()
        if environment_config["environment_class"] == "docker":
            source = workspace
            if volume := config.get("workspace_volume"):
                mountpoint = subprocess.check_output([
                    environment_config.get("executable", "docker"), "volume", "inspect", volume,
                    "--format", "{{.Mountpoint}}",
                ], text=True).strip()
                source = Path(mountpoint) / workspace.relative_to(store.root)
            environment_config["cwd"] = "/testbed"
            environment_config["run_args"] = [*environment_config.get("run_args", ["--rm"]),
                                              "--mount", f"type=bind,source={source},target=/testbed"]
        else:
            environment_config["cwd"] = str(workspace)
        environment = get_environment(environment_config)
        if container_id := getattr(environment, "container_id", None):
            result["container_id"] = container_id
            store.update(task_id, result=result)
        agent = TaskAgent(get_model(config=config["model"]), environment, store=store,
                          task_id=task_id, **config["agent"])
        store.update(task_id, stage="solving")
        result["exit_status"], _ = agent.run(task["request"]["issue"])
        result.update(n_calls=agent.model.n_calls, cost=agent.model.cost, budget=agent.budget_state())
        result["submission_kind"] = "agent" if result["exit_status"] == "Submitted" else "recovered"
        agent.active()
        store.update(task_id, stage="exporting")
        result["patch_chars"] = save_patch(workspace, directory)
        store.update(task_id, result=result)
        store.event(task_id, "candidate", {"patch_chars": result["patch_chars"],
                                           "submission_kind": result["submission_kind"]})
        result["verification_status"] = "running"
        store.update(task_id, stage="verifying", result=result)
        verification_started = time.monotonic()
        verification = environment.execute(config["test_command"], timeout=config.get("test_timeout", 120))
        (directory / "verification.txt").write_text(verification["output"])
        result["test_returncode"] = verification["returncode"]
        result["test_command"] = config["test_command"]
        result["verification_status"] = "passed" if verification["returncode"] == 0 else "failed"
        store.event(task_id, "verification", {
            "returncode": verification["returncode"], "seconds": time.monotonic() - verification_started,
        })
        agent.active()
        status = "succeeded" if verification["returncode"] == 0 else "failed"
    except WorkerStopped:
        status = "cancelled" if store.get(task_id)["status"] == "cancelling" else "interrupted"
    except Exception as exception:
        error = f"{type(exception).__name__}: {exception}"
        store.event(task_id, "error", {"message": error})
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if agent is not None:
            agent.save()
            result.update(n_calls=agent.model.n_calls, cost=agent.model.cost, budget=agent.budget_state())
        if result["verification_status"] == "running":
            result["verification_status"] = "error" if status == "failed" else "interrupted"
        if (workspace / ".git").exists():
            result["patch_chars"] = save_patch(workspace, directory)
            if status == "succeeded" and not result["patch_chars"]:
                status, error = "failed", "Verification passed but the patch is empty"
        if environment is not None and getattr(environment, "container_id", None):
            subprocess.run([environment.config.executable, "rm", "-f", environment.container_id],
                           capture_output=True, timeout=30)
            environment.container_id = None
        result["wall_seconds"] = result.get("wall_seconds", 0) + time.monotonic() - started
        result.pop("container_id", None)
        if store.get(task_id)["status"] == "cancelling":
            status = "cancelled"
        if agent is not None:
            write_json(directory / "trajectory.json", {
                "task_id": task_id, "status": status, "messages": agent.messages, "result": result,
            })
        store.transition(task_id, ("running", "cancelling", "interrupted"), status,
                         stage=status, result=result, error=error, pid=None, event=result)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    args = parser.parse_args()
    store = TaskStore(args.root)
    with (store.directory(args.task_id) / "worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_task(store, args.task_id)


if __name__ == "__main__":
    main()
