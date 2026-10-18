"""Single service process dispatcher for the durable SQLite queue."""

import fcntl
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

from minisweagent.service.store import TaskStore


def worker_available(directory: Path) -> bool:
    with (directory / "worker.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
    return True


class TaskManager:
    def __init__(self, store: TaskStore, workers: int = 1):
        self.store, self.workers = store, workers
        self.stopped = threading.Event()
        self.active: dict[str, subprocess.Popen] = {}
        self.lock = None
        self.thread = threading.Thread(target=self.dispatch, name="agent-task-dispatch", daemon=True)

    def start(self) -> None:
        self.lock = (self.store.root / "manager.lock").open("w")
        fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.store.recover()
        self.thread.start()

    @staticmethod
    def _signal(process: subprocess.Popen, sig: int) -> None:
        """Signal the worker group, falling back to the child if the host denies killpg."""
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            try:
                process.send_signal(sig)
            except ProcessLookupError:
                pass

    def terminate(self, task_id: str, process: subprocess.Popen) -> None:
        if process.poll() is None:
            self._signal(process, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._signal(process, signal.SIGKILL)
                process.wait()
        task = self.store.get(task_id)
        if container_id := task["result"].get("container_id"):
            subprocess.run([task["config"]["environment"].get("executable", "docker"), "rm", "-f", container_id],
                           capture_output=True, timeout=30)

    def dispatch(self) -> None:
        while not self.stopped.wait(0.15):
            for task_id, process in list(self.active.items()):
                if self.store.get(task_id)["status"] == "cancelling":
                    self.terminate(task_id, process)
                if process.poll() is not None:
                    status = "cancelled" if self.store.get(task_id)["status"] == "cancelling" else "interrupted"
                    self.store.transition(task_id, ("running", "cancelling"), status, stage=status, pid=None,
                                          error="Worker exited before saving its result",
                                          event={"returncode": process.returncode})
                    self.active.pop(task_id)
            for task in self.store.queued(self.workers):
                if len(self.active) >= self.workers:
                    break
                task_id = task["id"]
                if task["status"] != "queued" or not worker_available(self.store.directory(task_id)):
                    continue
                if not self.store.transition(task_id, ("queued",), "running", stage="starting", error=None):
                    continue
                with (self.store.directory(task_id) / "worker.log").open("a") as logfile:
                    process = subprocess.Popen(
                        [sys.executable, "-m", "minisweagent.service.worker", "--root", str(self.store.root),
                         "--task-id", task_id], stdout=logfile, stderr=subprocess.STDOUT, start_new_session=True,
                        env=os.environ | {"MSWEA_SILENT_STARTUP": "1"},
                    )
                self.active[task_id] = process
                self.store.update(task_id, pid=process.pid)
                self.store.event(task_id, "started", {})

    def close(self) -> None:
        self.stopped.set()
        self.thread.join()
        for task_id, process in self.active.items():
            self.terminate(task_id, process)
        self.store.recover()
        self.lock.close()
