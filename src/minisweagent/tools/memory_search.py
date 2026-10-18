"""Search the current transcript or saved sessions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from minisweagent.memory.search import MemorySearch, get_search_context

from . import register


@dataclass
class MemorySearchTool:
    name: str = "memory_search"
    description: str = (
        "Search the current conversation or saved sessions for a keyword or regex. "
        "Use this to recover an earlier error, path, or decision that is no longer in view."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword terms or a regular expression to find.",
                },
                "use_regex": {
                    "type": "boolean",
                    "description": "Treat query as a regular expression. Default false.",
                },
                "scope": {
                    "type": "string",
                    "description": "'current' searches this run. 'sessions' searches saved sessions.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum matches to return. Default 5.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        query = str(args.get("query", "")).strip()
        if not query:
            return {"output": "Error: 'query' is required.", "returncode": 1}

        use_regex = bool(args.get("use_regex", False))
        scope = args.get("scope") or "current"
        limit = args.get("limit", 5)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            return {"output": "Error: 'limit' must be an integer.", "returncode": 1}
        if limit <= 0:
            return {"output": "Error: 'limit' must be positive.", "returncode": 1}

        messages, session_memory = get_search_context()
        searcher = MemorySearch()
        try:
            if scope == "sessions":
                if session_memory is None:
                    return {"output": "No saved sessions are available.", "returncode": 1}
                hits = session_memory.search(query, use_regex=use_regex, limit=limit)
            elif scope == "current":
                hits = searcher.search(messages, query, use_regex=use_regex, limit=limit)
            else:
                return {"output": "Error: scope must be 'current' or 'sessions'.", "returncode": 1}
        except re.error as exc:
            return {"output": f"Invalid regex: {exc}", "returncode": 1}

        if not hits:
            return {"output": f"No matches for {query!r}.", "returncode": 0}

        lines = [f"Found {len(hits)} match(es) for {query!r}."]
        for hit in hits:
            where = f"session {hit['session_id']}, " if hit.get("session_id") else ""
            lines.append(f"- {where}#{hit['index']} {hit['role']} (score {hit['score']}): {hit['snippet']}")
        return {"output": "\n".join(lines), "returncode": 0}


register(MemorySearchTool())
