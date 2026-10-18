"""Current-run transcript search for the ``summary_search`` arm.

The tool is deliberately narrow: it can only read the transcript snapshot the
agent installed immediately before the current model call.  It cannot see a
future message, another run, saved sessions, or grading feedback.  The result is
capped by estimated tokens at the tool boundary, so the history policy never
has to repair an oversized retrieval observation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .budget import (
    DEFAULT_RETRIEVAL_TOKENS,
    estimate_text_tokens,
    fit_text_to_tokens,
    message_text,
)

_SNIPPET_WINDOW = 240
_MAX_LIMIT = 10


class SearchContext:
    """A per-agent snapshot of the transcript visible to the search tool."""

    def __init__(self) -> None:
        self._messages: list[dict[str, Any]] = []
        self._step = 0

    def update(self, messages: list[dict[str, Any]], step: int) -> None:
        # A shallow copy freezes the set of messages.  The message dicts are not
        # mutated by the agent, so sharing them is safe and cheap.
        self._messages = list(messages)
        self._step = step

    def snapshot(self) -> tuple[list[dict[str, Any]], int]:
        return list(self._messages), self._step


def _snippet(text: str, start: int, window: int = _SNIPPET_WINDOW) -> str:
    begin = max(0, start - 40)
    excerpt = " ".join(text[begin : begin + window].split())
    if begin > 0:
        excerpt = "..." + excerpt
    if begin + window < len(text):
        excerpt = excerpt + "..."
    return excerpt


def search_transcript(
    messages: list[dict[str, Any]],
    query: str,
    *,
    use_regex: bool = False,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return highest-scoring messages, with their indices and snippets."""
    query = query.strip()
    if not query or limit <= 0:
        return []
    pattern = re.compile(query, re.IGNORECASE) if use_regex else None
    terms = [] if use_regex else [term.lower() for term in query.split() if term]
    hits: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        text = message_text(message)
        if pattern is not None:
            found = pattern.findall(text)
            if not found:
                continue
            match = pattern.search(text)
            score = len(found) or 1
            start = match.start() if match else 0
        else:
            lowered = text.lower()
            if any(term not in lowered for term in terms):
                continue
            score = sum(lowered.count(term) for term in terms)
            start = min(lowered.find(term) for term in terms)
        hits.append(
            {
                "index": index,
                "role": message.get("role", "unknown"),
                "score": score,
                "snippet": _snippet(text, start),
            }
        )
    hits.sort(key=lambda hit: (-hit["score"], hit["index"]))
    return hits[:limit]


@dataclass
class MemorySearchTool:
    """Search only the current run's transcript; no sessions, no future steps."""

    context: SearchContext
    token_limit: int = DEFAULT_RETRIEVAL_TOKENS
    name: str = "memory_search"
    description: str = (
        "Search this run's earlier transcript for a keyword or regular expression. "
        "Call this whenever a file path, error, or earlier decision you need is no longer "
        "in view; do not guess or redo work. Use mode=full to read matching messages, or "
        "index=N to reopen one message by the number a result showed. Only messages "
        "already produced in this run are visible."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword terms (all must match) or a regular expression. Required unless index is given.",
                },
                "use_regex": {
                    "type": "boolean",
                    "description": "Treat query as a regular expression. Default false.",
                },
                "mode": {
                    "type": "string",
                    "description": "'snippet' returns a short window; 'full' returns the matched messages. Default snippet.",
                },
                "index": {
                    "type": "integer",
                    "description": "Open one message by its 0-based transcript index instead of searching.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum matches to return. Default 5.",
                },
            },
            "additionalProperties": False,
        }
    )

    def __post_init__(self) -> None:
        if self.token_limit <= 0:
            raise ValueError("token_limit must be positive")

    def __call__(self, args: dict, env=None) -> dict:
        messages, step = self.context.snapshot()
        if not messages:
            return self._result("No transcript is available yet.", 0)

        index = args.get("index")
        if index is not None:
            return self._open(messages, index, step)

        query = str(args.get("query", "")).strip()
        if not query:
            return self._error("'query' is required unless 'index' is given.")
        use_regex = bool(args.get("use_regex", False))
        mode = str(args.get("mode") or "snippet").strip().lower()
        if mode not in {"snippet", "full"}:
            return self._error("mode must be 'snippet' or 'full'.")
        try:
            limit = int(args.get("limit", 5))
        except (TypeError, ValueError):
            return self._error("'limit' must be an integer.")
        if limit <= 0:
            return self._error("'limit' must be positive.")
        limit = min(limit, _MAX_LIMIT)

        try:
            hits = search_transcript(messages, query, use_regex=use_regex, limit=limit)
        except re.error as error:
            return self._error(f"Invalid regex: {error}")
        if not hits:
            return self._result(f"No matches for {query!r} in this run's transcript.", 0)

        if mode == "full":
            return self._full(messages, hits, query)
        lines = [f"Found {len(hits)} match(es) for {query!r} in this run's transcript."]
        for hit in hits:
            lines.append(f"- #{hit['index']} {hit['role']} (score {hit['score']}): {hit['snippet']}")
        text = "\n".join(lines)
        text = fit_text_to_tokens(text, self.token_limit)
        return self._result(text, estimate_text_tokens(text), matches=len(hits))

    def _open(self, messages: list[dict[str, Any]], index: Any, step: int) -> dict:
        try:
            number = int(index)
        except (TypeError, ValueError):
            return self._error("'index' must be an integer.")
        if not 0 <= number < len(messages):
            return self._error(f"index {number} is outside 0..{len(messages) - 1}")
        message = messages[number]
        body = message_text(message)
        available = self.token_limit - estimate_text_tokens(f"#{number} {message.get('role')}:\n") - 4
        clipped = fit_text_to_tokens(body, max(1, available))
        text = f"#{number} {message.get('role')} (transcript at step {step}):\n{clipped}"
        if clipped != body:
            text += f"\n[truncated; the message has {len(body)} characters]"
        text = fit_text_to_tokens(text, self.token_limit)
        return self._result(text, estimate_text_tokens(text), matches=1)

    def _full(self, messages: list[dict[str, Any]], hits: list[dict[str, Any]], query: str) -> dict:
        header = f"Found {len(hits)} match(es) for {query!r}. Full text, most relevant first."
        parts = [header]
        used = estimate_text_tokens(header)
        for hit in hits:
            prefix = f"#{hit['index']} {hit['role']} (score {hit['score']}):\n"
            prefix_tokens = estimate_text_tokens(prefix)
            remaining = self.token_limit - used - prefix_tokens
            if remaining <= 0:
                break
            body = message_text(messages[hit["index"]])
            fitted = fit_text_to_tokens(body, remaining)
            if not fitted:
                break
            parts.append(prefix + fitted)
            used += prefix_tokens + estimate_text_tokens(fitted)
            if fitted != body:
                parts.append(f"[truncated; call index={hit['index']} for the rest]")
                break
        text = "\n\n".join(parts)
        text = fit_text_to_tokens(text, self.token_limit)
        return self._result(text, estimate_text_tokens(text), matches=len(hits))

    def _result(self, text: str, tokens: int, *, matches: int = 0) -> dict:
        return {
            "output": text,
            "returncode": 0,
            "extra": {
                "tool": "memory_search",
                "retrieval_tokens": tokens,
                "matches": matches,
            },
        }

    @staticmethod
    def _error(message: str) -> dict:
        return {"output": f"Error: {message}", "returncode": 1, "extra": {"tool": "memory_search", "retrieval_tokens": 0}}
