"""History management for conversation compression."""

from typing import Any


class HistoryManager:
    """Manages conversation history with compression capabilities."""

    def __init__(self, max_messages: int = 50, keep_system: bool = True):
        """Initialize history manager.

        Args:
            max_messages: Maximum number of messages to keep
            keep_system: Whether to always keep system messages
        """
        self.max_messages = max_messages
        self.keep_system = keep_system

    def compress_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compress message history by keeping only recent messages.

        Args:
            messages: List of message dictionaries

        Returns:
            Compressed list of messages
        """
        if len(messages) <= self.max_messages:
            return messages

        if not self.keep_system:
            return messages[-self.max_messages:]

        # Keep system messages and most recent user/assistant messages
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        other_messages = [msg for msg in messages if msg.get("role") != "system"]

        # Calculate how many non-system messages we can keep
        available_slots = max(0, self.max_messages - len(system_messages))
        recent_messages = other_messages[-available_slots:] if available_slots > 0 else []

        # If we have too many system messages, just return the limit
        if len(system_messages) >= self.max_messages:
            return system_messages[:self.max_messages]

        # Combine system messages with recent non-system messages
        result = system_messages + recent_messages
        return result

    def get_summary_stats(self, messages: list[dict[str, Any]]) -> dict[str, int]:
        """Get statistics about message history.

        Args:
            messages: List of message dictionaries

        Returns:
            Dictionary with statistics
        """
        role_counts = {}
        total_chars = 0

        for msg in messages:
            role = msg.get("role", "unknown")
            role_counts[role] = role_counts.get(role, 0) + 1
            total_chars += len(msg.get("content", ""))

        return {
            "total_messages": len(messages),
            "total_characters": total_chars,
            "role_counts": role_counts,
            "compressed": len(messages) > self.max_messages
        }