"""Search the current transcript or saved sessions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from minisweagent.memory.history import message_text
from minisweagent.memory.search import MemorySearch, get_search_context

from . import register

DEFAULT_MAX_CHARS = 4000
MAX_CHARS = 16000


def _clip(text: str, limit: int) -> tuple[str, bool]:
    """Return the text capped at limit characters and whether it was clipped."""
    if len(text) <= limit:
        return text, False
    return text[:limit], True


@dataclass
class MemorySearchTool:
    name: str = "memory_search"
    description: str = (
        "Search the current conversation or saved sessions for a keyword or regex. "
        "Use mode=full to read the matching messages instead of a snippet, and index=N "
        "to reopen one message by the number a result showed. Use this to recover an "
        "earlier error, path, or decision that is no longer in view."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword terms or a regular expression to find. Required unless index is given.",
                },
                "use_regex": {
                    "type": "boolean",
                    "description": "Treat query as a regular expression. Default false.",
                },
                "scope": {
                    "type": "string",
                    "description": "'current' searches this run. 'sessions' searches saved sessions.",
                },
                "mode": {
                    "type": "string",
                    "description": "'snippet' returns a short window; 'full' returns the message text. Default snippet.",
                },
                "index": {
                    "type": "integer",
                    "description": "Open one message by its 0-based number instead of searching.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum matches to return. Default 5.",
                },
                "max_chars": {
                    "type": "integer",
                    "description": f"Character budget for returned text. Default {DEFAULT_MAX_CHARS}.",
                },
            },
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        query = str(args.get("query", "")).strip()
        use_regex = bool(args.get("use_regex", False))
        scope = args.get("scope") or "current"
        mode = str(args.get("mode") or "snippet").strip().lower()
        index = args.get("index")

        if scope not in {"current", "sessions"}:
            return {"output": "Error: scope must be 'current' or 'sessions'.", "returncode": 1}
        if mode not in {"snippet", "full"}:
            return {"output": "Error: mode must be 'snippet' or 'full'.", "returncode": 1}
        try:
            limit = int(args.get("limit", 5))
            max_chars = int(args.get("max_chars", DEFAULT_MAX_CHARS))
        except (TypeError, ValueError):
            return {"output": "Error: 'limit' and 'max_chars' must be integers.", "returncode": 1}
        if limit <= 0:
            return {"output": "Error: 'limit' must be positive.", "returncode": 1}
        if max_chars <= 0:
            return {"output": "Error: 'max_chars' must be positive.", "returncode": 1}
        max_chars = min(max_chars, MAX_CHARS)

        messages, session_memory = get_search_context()
        if index is not None:
            if scope != "current":
                return {"output": "Error: 'index' reads the current transcript only.", "returncode": 1}
            return self._open(messages, index, max_chars)
        if not query:
            return {"output": "Error: 'query' is required unless 'index' is given.", "returncode": 1}

        searcher = MemorySearch()
        try:
            if scope == "sessions":
                if session_memory is None:
                    return {"output": "No saved sessions are available.", "returncode": 1}
                hits = session_memory.search(query, use_regex=use_regex, limit=limit)
            else:
                hits = searcher.search(messages, query, use_regex=use_regex, limit=limit)
        except re.error as exc:
            return {"output": f"Invalid regex: {exc}", "returncode": 1}

        if not hits:
            return {"output": f"No matches for {query!r}.", "returncode": 0}
        if mode == "full" and scope == "current":
            return self._full(messages, hits, query, max_chars)

        lines = [f"Found {len(hits)} match(es) for {query!r}."]
        if mode == "full":
            lines.append("Full text is available with scope=current; showing snippets.")
        for hit in hits:
            where = f"session {hit['session_id']}, " if hit.get("session_id") else ""
            lines.append(f"- {where}#{hit['index']} {hit['role']} (score {hit['score']}): {hit['snippet']}")
        return {"output": "\n".join(lines), "returncode": 0}

    @staticmethod
    def _open(messages: list[dict], index, max_chars: int) -> dict:
        try:
            index = int(index)
        except (TypeError, ValueError):
            return {"output": "Error: 'index' must be an integer.", "returncode": 1}
        if not 0 <= index < len(messages):
            return {"output": f"Error: index {index} is outside 0..{len(messages) - 1}.", "returncode": 1}
        message = messages[index]
        text = message_text(message)
        body, clipped = _clip(text, max_chars)
        note = f"\n[truncated at {max_chars} characters; the message has {len(text)}]" if clipped else ""
        return {"output": f"#{index} {message.get('role', 'unknown')}:\n{body}{note}", "returncode": 0}

    @staticmethod
    def _full(messages: list[dict], hits: list[dict], query: str, max_chars: int) -> dict:
        """Return the matched messages themselves within one shared character budget."""
        budget = max_chars
        chunks = [f"Found {len(hits)} match(es) for {query!r}. Full text, most relevant first."]
        for hit in hits:
            if budget <= 0:
                break
            text = message_text(messages[hit["index"]])
            body, clipped = _clip(text, budget)
            note = ""
            if clipped:
                note = f"\n[truncated; the message has {len(text)} characters, call index={hit['index']} for the rest]"
            chunks.append(f"#{hit['index']} {hit['role']} (score {hit['score']}):\n{body}{note}")
            budget -= len(body)
        return {"output": "\n\n".join(chunks), "returncode": 0}


register(MemorySearchTool())
