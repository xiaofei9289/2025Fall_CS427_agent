"""Session memory for cross-session persistence."""

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from minisweagent.memory.search import MemorySearch


class SessionMemory:
    """Manages session memory storage and retrieval."""

    def __init__(self, memory_dir: Path, session_id: str | None = None):
        """Initialize session memory.

        Args:
            memory_dir: Directory to store memory files
            session_id: Unique session identifier, auto-generated if None
        """
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = session_id or f"session_{int(time.time())}"
        self.session_file = self.memory_dir / f"{self.session_id}.json"

    def save_session(self, messages: list[dict[str, Any]], metadata: dict | None = None) -> None:
        """Save session data to file."""
        session_data = {
            "session_id": self.session_id,
            "messages": messages,
            "metadata": metadata or {},
            "saved_at": self._get_timestamp(),
        }
        self.session_file.write_text(json.dumps(session_data, indent=2))

    def load_session(self) -> dict[str, Any] | None:
        """Load session data, or None if the file is missing or unreadable."""
        if not self.session_file.exists():
            return None
        # Corrupt or unreadable session files fail gracefully to an empty memory.
        try:
            return json.loads(self.session_file.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def get_messages(self) -> list[dict[str, Any]]:
        """Get messages from the saved session, or an empty list."""
        return (self.load_session() or {}).get("messages", [])

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all available sessions, most recent first."""
        sessions = []
        for session_file in self.memory_dir.glob("*.json"):
            try:
                data = json.loads(session_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            sessions.append({
                "session_id": data.get("session_id"),
                "saved_at": data.get("saved_at"),
                "message_count": len(data.get("messages", [])),
                "file": str(session_file),
            })
        return sorted(sessions, key=lambda x: x.get("saved_at", ""), reverse=True)

    def delete_session(self, session_id: str | None = None) -> bool:
        """Delete a session file, keeping the current session by default."""
        target_file = self.memory_dir / f"{session_id or self.session_id}.json"
        if target_file.exists():
            target_file.unlink()
            return True
        return False

    def cleanup_old_sessions(self, keep_count: int = 10) -> int:
        """Clean up old session files, keeping only the most recent ones."""
        return sum(self.delete_session(session["session_id"]) for session in self.list_sessions()[keep_count:])

    def search(self, query: str, *, use_regex: bool = False, limit: int = 5) -> list[dict[str, Any]]:
        """Search every saved session file for a query."""
        searcher = MemorySearch()
        hits: list[dict[str, Any]] = []
        for session_file in self.memory_dir.glob("*.json"):
            try:
                data = json.loads(session_file.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            session_id = data.get("session_id", session_file.stem)
            hits.extend(
                {**hit, "session_id": session_id}
                for hit in searcher.search(data.get("messages", []), query, use_regex=use_regex, limit=limit)
            )
        hits.sort(key=lambda hit: (-hit["score"], hit.get("session_id", ""), hit["index"]))
        return hits[:limit]

    def _get_timestamp(self) -> str:
        """Get current timestamp as ISO string."""
        return datetime.now().isoformat()
