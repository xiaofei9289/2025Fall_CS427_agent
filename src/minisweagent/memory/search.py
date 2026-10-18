"""Keyword and regex search over agent messages and saved sessions."""

from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Any

from minisweagent.memory.history import message_text

_search_context: ContextVar[tuple[list[dict[str, Any]], Any]] = ContextVar("memory_search_context", default=([], None))


def set_search_context(messages: list[dict[str, Any]], session_memory: Any = None) -> None:
    """Remember the transcript the memory_search tool should read."""
    _search_context.set((list(messages), session_memory))


def get_search_context() -> tuple[list[dict[str, Any]], Any]:
    """Return the transcript and session store set by the agent."""
    return _search_context.get()


class MemorySearch:
    """Find earlier messages that match a query."""

    def search(
        self,
        messages: list[dict[str, Any]],
        query: str,
        *,
        use_regex: bool = False,
        role: str | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return the highest scoring matches.

        Keyword queries are case-insensitive and require every term to appear.
        Regex queries use the whole query as one pattern.
        """
        query = query.strip()
        if not query or limit <= 0:
            return []

        pattern = self._compile(query) if use_regex else None
        terms = [] if use_regex else [term.lower() for term in query.split() if term]
        hits: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            if role and message.get("role") != role:
                continue
            text = message_text(message)
            score, start = self._score(text, terms, pattern)
            if score <= 0:
                continue
            hits.append(
                {
                    "index": index,
                    "role": message.get("role", "unknown"),
                    "score": score,
                    "snippet": self._snippet(text, start),
                }
            )
        hits.sort(key=lambda hit: (-hit["score"], hit["index"]))
        return hits[:limit]

    def _compile(self, query: str) -> re.Pattern[str]:
        return re.compile(query, re.IGNORECASE)

    def _score(self, text: str, terms: list[str], pattern: re.Pattern[str] | None) -> tuple[int, int]:
        if pattern is not None:
            match = pattern.search(text)
            if not match:
                return 0, 0
            return len(pattern.findall(text)) or 1, match.start()

        lowered = text.lower()
        if any(term not in lowered for term in terms):
            return 0, 0
        score = sum(lowered.count(term) for term in terms)
        start = min(lowered.find(term) for term in terms)
        return score, start

    def _snippet(self, text: str, start: int, window: int = 240) -> str:
        begin = max(0, start - 40)
        excerpt = " ".join(text[begin : begin + window].split())
        if begin > 0:
            excerpt = "..." + excerpt
        if begin + window < len(text):
            excerpt = excerpt + "..."
        return excerpt
