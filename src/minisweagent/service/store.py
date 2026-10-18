"""SQLite task queue and append-only execution events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "tasks.sqlite3"
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, stage TEXT NOT NULL,
                    request TEXT NOT NULL, config TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}',
                    error TEXT, pid INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                    kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_task ON events(task_id, id);
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, request: dict, config: dict) -> dict:
        task_id, now = uuid.uuid4().hex, timestamp()
        self.directory(task_id).mkdir()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO tasks(id,status,stage,request,config,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (task_id, "queued", "queued", json.dumps(request), json.dumps(config), now, now),
            )
            connection.execute("INSERT INTO events(task_id,kind,payload,created_at) VALUES(?,?,?,?)",
                               (task_id, "queued", "{}", now))
        return self.get(task_id)

    def directory(self, task_id: str) -> Path:
        return self.root / task_id

    def get(self, task_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            return None
        task = dict(row)
        for name in ("request", "config", "result"):
            task[name] = json.loads(task[name])
        return task

    def list(self, limit: int = 50) -> list[dict]:
        with self.connect() as connection:
            ids = connection.execute("SELECT id FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self.get(row["id"]) for row in ids]

    def queued(self, limit: int) -> list[dict]:
        with self.connect() as connection:
            ids = connection.execute(
                "SELECT id FROM tasks WHERE status='queued' ORDER BY created_at LIMIT ?", (limit,)
            ).fetchall()
        return [self.get(row["id"]) for row in ids]

    def transition(self, task_id: str, previous: tuple[str, ...], status: str,
                   *, event: dict | None = None, **values) -> bool:
        if not set(values) <= {"stage", "result", "error", "pid"}:
            raise ValueError("Unknown task field")
        values = {"status": status, "updated_at": timestamp(), **values}
        if "result" in values:
            values["result"] = json.dumps(values["result"])
        placeholders = ",".join("?" for _ in previous)
        assignments = ",".join(f"{key}=?" for key in values)
        with self.connect() as connection:
            changed = connection.execute(
                f"UPDATE tasks SET {assignments} WHERE id=? AND status IN ({placeholders})",
                (*values.values(), task_id, *previous),
            ).rowcount
            if changed and event is not None:
                connection.execute("INSERT INTO events(task_id,kind,payload,created_at) VALUES(?,?,?,?)",
                                   (task_id, status, json.dumps(event), timestamp()))
        return bool(changed)

    def update(self, task_id: str, **values) -> None:
        task = self.get(task_id)
        if task is not None:
            self.transition(task_id, (task["status"],), task["status"], **values)

    def recover(self) -> None:
        with self.connect() as connection:
            interrupted = connection.execute("SELECT id FROM tasks WHERE status IN ('running','cancelling')").fetchall()
            connection.execute(
                "UPDATE tasks SET status='interrupted',stage='interrupted',pid=NULL,updated_at=? "
                "WHERE status IN ('running','cancelling')", (timestamp(),),
            )
            for task in interrupted:
                connection.execute("INSERT INTO events(task_id,kind,payload,created_at) VALUES(?,?,?,?)",
                                   (task["id"], "interrupted", '{"reason":"service_restart"}', timestamp()))

    def event(self, task_id: str, kind: str, payload: dict) -> None:
        with self.connect() as connection:
            connection.execute("INSERT INTO events(task_id,kind,payload,created_at) VALUES(?,?,?,?)",
                               (task_id, kind, json.dumps(payload), timestamp()))

    def events(self, task_id: str, after: int = 0, limit: int = 100) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM events WHERE task_id=? AND id>? ORDER BY id LIMIT ?", (task_id, after, limit)
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]
