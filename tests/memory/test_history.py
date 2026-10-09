"""Tests for history management functionality."""

import pytest
from minisweagent.memory.history import HistoryManager


class TestHistoryManager:
    """Test cases for HistoryManager class."""

    def test_init_default(self):
        """Test HistoryManager initialization with defaults."""
        manager = HistoryManager()
        assert manager.max_messages == 50
        assert manager.keep_system is True

    def test_init_custom(self):
        """Test HistoryManager initialization with custom values."""
        manager = HistoryManager(max_messages=20, keep_system=False)
        assert manager.max_messages == 20
        assert manager.keep_system is False

    def test_compress_messages_under_limit(self):
        """Test compression when messages are under the limit."""
        manager = HistoryManager(max_messages=5)
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        result = manager.compress_messages(messages)
        assert result == messages

    def test_compress_messages_over_limit_keep_system(self):
        """Test compression when messages exceed limit with system kept."""
        manager = HistoryManager(max_messages=3, keep_system=True)
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"}
        ]
        result = manager.compress_messages(messages)

        # Should keep system message + 2 most recent messages
        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert result[1]["content"] == "Response 2"
        assert result[2]["content"] == "Message 3"

    def test_compress_messages_over_limit_no_system(self):
        """Test compression when messages exceed limit without keeping system."""
        manager = HistoryManager(max_messages=2, keep_system=False)
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"}
        ]
        result = manager.compress_messages(messages)

        # Should keep only 2 most recent messages
        assert len(result) == 2
        assert result[0]["content"] == "Message 2"
        assert result[1]["content"] == "Response 2"

    def test_get_summary_stats(self):
        """Test summary statistics generation."""
        manager = HistoryManager()
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"}
        ]
        stats = manager.get_summary_stats(messages)

        assert stats["total_messages"] == 4
        assert stats["total_characters"] > 0
        assert stats["role_counts"]["system"] == 1
        assert stats["role_counts"]["user"] == 2
        assert stats["role_counts"]["assistant"] == 1
        assert stats["compressed"] is False

    def test_get_summary_stats_compressed(self):
        """Test summary statistics when compression would occur."""
        manager = HistoryManager(max_messages=2)
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "User 1"},
            {"role": "assistant", "content": "Assistant 1"},
            {"role": "user", "content": "User 2"}
        ]
        stats = manager.get_summary_stats(messages)
        assert stats["compressed"] is True

    def test_empty_messages(self):
        """Test handling of empty message list."""
        manager = HistoryManager()
        result = manager.compress_messages([])
        assert result == []

        stats = manager.get_summary_stats([])
        assert stats["total_messages"] == 0
        assert stats["total_characters"] == 0
        assert stats["role_counts"] == {}

    def test_multiple_system_messages(self):
        """Test handling of multiple system messages."""
        manager = HistoryManager(max_messages=2, keep_system=True)
        messages = [
            {"role": "system", "content": "System 1"},
            {"role": "system", "content": "System 2"},
            {"role": "user", "content": "User message"},
            {"role": "assistant", "content": "Assistant message"}
        ]
        result = manager.compress_messages(messages)

        # Should keep both system messages (no room for others)
        assert len(result) == 2
        assert all(msg["role"] == "system" for msg in result)