"""Tests for session memory functionality."""

import json
import tempfile
from pathlib import Path

import pytest
from minisweagent.memory.session import SessionMemory


class TestSessionMemory:
    """Test cases for SessionMemory class."""

    def test_init_with_auto_session_id(self, tmp_path):
        """Test initialization with auto-generated session ID."""
        memory = SessionMemory(tmp_path)
        assert memory.session_id.startswith("session_")
        assert memory.memory_dir == tmp_path
        assert memory.session_file.parent == tmp_path

    def test_init_with_custom_session_id(self, tmp_path):
        """Test initialization with custom session ID."""
        session_id = "custom_session_123"
        memory = SessionMemory(tmp_path, session_id)
        assert memory.session_id == session_id
        assert memory.session_file.name == f"{session_id}.json"

    def test_save_and_load_session(self, tmp_path):
        """Test saving and loading session data."""
        memory = SessionMemory(tmp_path, "test_session")
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"}
        ]
        metadata = {"task": "test_task"}

        # Save session
        memory.save_session(messages, metadata)
        assert memory.session_file.exists()

        # Load session
        loaded_data = memory.load_session()
        assert loaded_data is not None
        assert loaded_data["session_id"] == "test_session"
        assert loaded_data["messages"] == messages
        assert loaded_data["metadata"] == metadata
        assert "saved_at" in loaded_data

    def test_get_messages(self, tmp_path):
        """Test getting messages from saved session."""
        memory = SessionMemory(tmp_path, "test_session")
        messages = [{"role": "user", "content": "Test message"}]

        # No session file exists
        assert memory.get_messages() == []

        # Save and retrieve messages
        memory.save_session(messages)
        retrieved_messages = memory.get_messages()
        assert retrieved_messages == messages

    def test_load_nonexistent_session(self, tmp_path):
        """Test loading session that doesn't exist."""
        memory = SessionMemory(tmp_path, "nonexistent")
        result = memory.load_session()
        assert result is None

    def test_load_corrupted_session_file(self, tmp_path):
        """Test loading corrupted session file."""
        memory = SessionMemory(tmp_path, "corrupted")

        # Create corrupted JSON file
        memory.session_file.write_text("invalid json content")

        result = memory.load_session()
        assert result is None

    def test_list_sessions(self, tmp_path):
        """Test listing available sessions."""
        memory1 = SessionMemory(tmp_path, "session_1")
        memory2 = SessionMemory(tmp_path, "session_2")

        # Initially no sessions
        sessions = memory1.list_sessions()
        assert len(sessions) == 0

        # Save some sessions
        memory1.save_session([{"role": "user", "content": "Message 1"}])
        memory2.save_session([{"role": "user", "content": "Message 2"}])

        # List sessions
        sessions = memory1.list_sessions()
        assert len(sessions) == 2

        session_ids = [s["session_id"] for s in sessions]
        assert "session_1" in session_ids
        assert "session_2" in session_ids

        # Check session info
        for session in sessions:
            assert "saved_at" in session
            assert "message_count" in session
            assert "file" in session

    def test_delete_session(self, tmp_path):
        """Test deleting session files."""
        memory = SessionMemory(tmp_path, "test_session")

        # Delete non-existent session
        assert memory.delete_session() is False

        # Create and delete session
        memory.save_session([{"role": "user", "content": "Test"}])
        assert memory.session_file.exists()

        assert memory.delete_session() is True
        assert not memory.session_file.exists()

    def test_delete_specific_session(self, tmp_path):
        """Test deleting specific session by ID."""
        memory1 = SessionMemory(tmp_path, "session_1")
        memory2 = SessionMemory(tmp_path, "session_2")

        # Create both sessions
        memory1.save_session([{"role": "user", "content": "Message 1"}])
        memory2.save_session([{"role": "user", "content": "Message 2"}])

        # Delete specific session
        assert memory1.delete_session("session_2") is True
        assert memory1.session_file.exists()  # session_1 still exists
        assert not memory2.session_file.exists()  # session_2 deleted

    def test_cleanup_old_sessions(self, tmp_path):
        """Test cleaning up old session files."""
        # Create multiple sessions
        sessions = []
        for i in range(5):
            memory = SessionMemory(tmp_path, f"session_{i}")
            memory.save_session([{"role": "user", "content": f"Message {i}"}])
            sessions.append(memory)

        # Cleanup, keeping only 3 sessions
        deleted_count = sessions[0].cleanup_old_sessions(keep_count=3)
        assert deleted_count == 2

        # Check remaining sessions
        remaining_sessions = sessions[0].list_sessions()
        assert len(remaining_sessions) == 3

    def test_cleanup_with_fewer_sessions(self, tmp_path):
        """Test cleanup when fewer sessions exist than keep_count."""
        memory = SessionMemory(tmp_path, "test_session")
        memory.save_session([{"role": "user", "content": "Test"}])

        # Cleanup with keep_count higher than existing sessions
        deleted_count = memory.cleanup_old_sessions(keep_count=5)
        assert deleted_count == 0

        # Session should still exist
        assert memory.session_file.exists()

    def test_save_session_creates_directory(self):
        """Test that SessionMemory creates memory directory during initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir) / "nonexistent" / "memory"

            # Directory should not exist before creating SessionMemory
            assert not memory_dir.exists()

            # Creating SessionMemory should create the directory
            memory = SessionMemory(memory_dir, "test_session")
            assert memory_dir.exists()

            # Saving should work
            memory.save_session([{"role": "user", "content": "Test"}])
            assert memory.session_file.exists()