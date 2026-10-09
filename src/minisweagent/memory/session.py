"""Session memory for cross-session persistence."""

import json
from pathlib import Path
from typing import Any, Optional


class SessionMemory:
    """Manages session memory storage and retrieval."""

    def __init__(self, memory_dir: Path, session_id: Optional[str] = None):
        """Initialize session memory.

        Args:
            memory_dir: Directory to store memory files
            session_id: Unique session identifier, auto-generated if None
        """
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        if session_id is None:
            import time
            session_id = f"session_{int(time.time())}"

        self.session_id = session_id
        self.session_file = self.memory_dir / f"{session_id}.json"

    def save_session(self, messages: list[dict[str, Any]], metadata: Optional[dict] = None) -> None:
        """Save session data to file.

        Args:
            messages: List of conversation messages
            metadata: Optional metadata about the session
        """
        session_data = {
            "session_id": self.session_id,
            "messages": messages,
            "metadata": metadata or {},
            "saved_at": self._get_timestamp()
        }

        with open(self.session_file, 'w') as f:
            json.dump(session_data, f, indent=2)

    def load_session(self) -> Optional[dict[str, Any]]:
        """Load session data from file.

        Returns:
            Session data dictionary or None if file doesn't exist
        """
        if not self.session_file.exists():
            return None

        try:
            with open(self.session_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def get_messages(self) -> list[dict[str, Any]]:
        """Get messages from saved session.

        Returns:
            List of messages or empty list if no session found
        """
        session_data = self.load_session()
        if session_data:
            return session_data.get("messages", [])
        return []

    def list_sessions(self) -> list[dict[str, Any]]:
        """List all available sessions.

        Returns:
            List of session info dictionaries
        """
        sessions = []
        for session_file in self.memory_dir.glob("session_*.json"):
            try:
                with open(session_file, 'r') as f:
                    data = json.load(f)
                    sessions.append({
                        "session_id": data.get("session_id"),
                        "saved_at": data.get("saved_at"),
                        "message_count": len(data.get("messages", [])),
                        "file": str(session_file)
                    })
            except (json.JSONDecodeError, IOError):
                continue

        return sorted(sessions, key=lambda x: x.get("saved_at", ""), reverse=True)

    def delete_session(self, session_id: Optional[str] = None) -> bool:
        """Delete a session file.

        Args:
            session_id: Session to delete, defaults to current session

        Returns:
            True if file was deleted, False otherwise
        """
        target_id = session_id or self.session_id
        target_file = self.memory_dir / f"{target_id}.json"

        if target_file.exists():
            target_file.unlink()
            return True
        return False

    def cleanup_old_sessions(self, keep_count: int = 10) -> int:
        """Clean up old session files, keeping only the most recent ones.

        Args:
            keep_count: Number of recent sessions to keep

        Returns:
            Number of sessions deleted
        """
        sessions = self.list_sessions()
        if len(sessions) <= keep_count:
            return 0

        sessions_to_delete = sessions[keep_count:]
        deleted_count = 0

        for session in sessions_to_delete:
            if self.delete_session(session["session_id"]):
                deleted_count += 1

        return deleted_count

    def _get_timestamp(self) -> str:
        """Get current timestamp as ISO string."""
        from datetime import datetime
        return datetime.now().isoformat()