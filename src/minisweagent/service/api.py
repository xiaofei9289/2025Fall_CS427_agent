"""Trusted operator API: clients submit issues, operators choose execution policy."""

import copy
import os
import re
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from minisweagent.config import builtin_config_dir
from minisweagent.service.manager import TaskManager, worker_available
from minisweagent.service.store import TaskStore

BASE_TOOLS = ["read_file", "write_file", "refined_read_file", "search_file_content", "replace",
              "find_definition", "read_many_files"]
ARTIFACTS = {"patch.diff", "trajectory.json", "checkpoint.json", "verification.txt"}


@dataclass
class ServiceSettings:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("MSWEA_SERVICE_DATA_DIR", ".agent-service")))
    repo_root: Path = field(default_factory=lambda: Path(os.getenv("MSWEA_SERVICE_REPO_ROOT", ".")))
    config_path: Path = field(default_factory=lambda: Path(os.getenv("MSWEA_SERVICE_CONFIG", builtin_config_dir / "service.yaml")))
    workers: int = 1
    token: str = field(default_factory=lambda: os.getenv("MSWEA_SERVICE_TOKEN", ""))
    workspace_volume: str = field(default_factory=lambda: os.getenv("MSWEA_SERVICE_WORKSPACE_VOLUME", ""))


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repo: str = Field(min_length=1, max_length=2000)
    issue: str = Field(min_length=1, max_length=30000)
    ref: str = Field(default="", max_length=200)
    variant: Literal["baseline", "retrieval"] = "retrieval"


def public(task: dict) -> dict:
    return {key: value for key, value in task.items() if key not in {"config", "pid"}}


def create_app(settings: ServiceSettings | None = None) -> FastAPI:
    settings = settings or ServiceSettings()
    store = TaskStore(settings.data_dir)
    manager = TaskManager(store, settings.workers)
    config = yaml.safe_load(settings.config_path.read_text())

    @asynccontextmanager
    async def lifespan(_app):
        manager.start()
        try:
            yield
        finally:
            manager.close()

    def authorize(authorization: str = Header(default="")) -> None:
        if settings.token and not secrets.compare_digest(authorization, f"Bearer {settings.token}"):
            raise HTTPException(401, "Invalid service token")

    app = FastAPI(title="CS427 Coding Agent", lifespan=lifespan, dependencies=[Depends(authorize)])
    app.state.store = store

    def require(task_id: str) -> dict:
        if not (task := store.get(task_id)):
            raise HTTPException(404, "Task not found")
        return task

    @app.get("/health")
    def health():
        return {"status": "ok", "task_workers": settings.workers}

    @app.post("/tasks", status_code=202)
    def submit(request: TaskCreate):
        if request.ref.startswith("-") or any(ord(char) < 32 for char in request.ref):
            raise HTTPException(422, "Invalid git ref")
        if re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", request.repo):
            repo = request.repo
        else:
            repo_path = Path(request.repo).resolve()
            if not repo_path.is_relative_to(settings.repo_root.resolve()) or not (repo_path / ".git").exists():
                raise HTTPException(422, "Use a GitHub HTTPS repository or a local Git repository inside repo_root")
            repo = str(repo_path)
        task_config = copy.deepcopy(config)
        if settings.workspace_volume:
            task_config["workspace_volume"] = settings.workspace_volume
        task_config["agent"]["enabled_tools"] = BASE_TOOLS + (
            ["code_search", "repo_map"] if request.variant == "retrieval" else []
        )
        return public(store.create(request.model_dump() | {"repo": repo}, task_config))

    @app.get("/tasks")
    def list_tasks(limit: int = Query(default=50, ge=1, le=1000)):
        return [public(task) for task in store.list(limit)]

    @app.get("/tasks/{task_id}")
    def get_task(task_id: str):
        return public(require(task_id))

    @app.get("/tasks/{task_id}/events")
    def events(task_id: str, after: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=1000)):
        require(task_id)
        return store.events(task_id, after, limit)

    @app.post("/tasks/{task_id}/cancel")
    def cancel(task_id: str):
        task = require(task_id)
        if task["status"] not in {"queued", "running", "cancelling", "cancelled"}:
            raise HTTPException(409, "Only queued or running tasks can be cancelled")
        status = "cancelled" if task["status"] == "queued" else "cancelling"
        if task["status"] != "cancelled" and store.transition(task_id, (task["status"],), status, stage=status):
            store.event(task_id, status, {})
        return public(require(task_id))

    @app.post("/tasks/{task_id}/resume", status_code=202)
    def resume(task_id: str):
        task = require(task_id)
        if task["status"] not in {"cancelled", "interrupted"} or not worker_available(store.directory(task_id)):
            raise HTTPException(409, "Task must be cancelled or interrupted with its previous worker stopped")
        if not store.transition(task_id, (task["status"],), "queued", stage="queued", error=None):
            raise HTTPException(409, "Task state changed; reload before resuming")
        store.event(task_id, "queued", {"resume": True})
        return public(require(task_id))

    @app.get("/tasks/{task_id}/artifacts/{name}")
    def artifact(task_id: str, name: str):
        require(task_id)
        if name not in ARTIFACTS or not (path := store.directory(task_id) / name).is_file():
            raise HTTPException(404, "Artifact not found")
        return FileResponse(path, filename=name)

    return app
