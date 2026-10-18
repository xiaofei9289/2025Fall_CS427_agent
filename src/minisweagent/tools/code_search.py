"""AST retrieval tools using the same implementation on host and in containers."""

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from minisweagent.retrieval import repository
from minisweagent.tools import register


def execute_retrieval(args: dict, operation: str, env=None) -> dict:
    query = args.get("query", "")
    if not isinstance(query, str) or (operation in {"code_search", "context"} and not query.strip()):
        return {"output": f"query must be a nonempty string for {operation}", "returncode": 2}
    limit, max_chars = args.get("limit", 10), args.get("max_chars", 6000)
    max_files, snippet_lines = args.get("max_files", 5), args.get("snippet_lines", 8)
    if not isinstance(limit, int) or not 1 <= limit <= 50:
        return {"output": "limit must be between 1 and 50", "returncode": 2}
    if not isinstance(max_chars, int) or not 256 <= max_chars <= 20000:
        return {"output": "max_chars must be between 256 and 20000", "returncode": 2}
    if not isinstance(max_files, int) or not 1 <= max_files <= 20:
        return {"output": "max_files must be between 1 and 20", "returncode": 2}
    if not isinstance(snippet_lines, int) or not 0 <= snippet_lines <= 80:
        return {"output": "snippet_lines must be between 0 and 80", "returncode": 2}
    payload = {
        "operation": operation,
        "query": query,
        "limit": limit,
        "max_chars": max_chars,
        "max_files": max_files,
        "snippet_lines": snippet_lines,
    }
    if env is None:
        return repository.retrieve(payload)
    script = (
        Path(repository.__file__).read_text()
        + f"\nimport json\nprint(json.dumps(retrieve(json.loads({json.dumps(payload)!r}))))\n"
    )
    output = env.execute(f"python -c {shlex.quote(script)}")
    return json.loads(output["output"]) if output["returncode"] == 0 else output


@dataclass
class CodeSearchTool:
    name: str = "code_search"
    description: str = "Rank Python functions/classes by issue keywords, BM25, and symbol names. Returns qualified names and line ranges."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            "required": ["query"],
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        return execute_retrieval(args, "code_search", env)


@dataclass
class RepoMapTool:
    name: str = "repo_map"
    description: str = "Show an issue-relevant Python repository map of classes, functions, signatures and line ranges within a character budget."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 256, "maximum": 20000},
            },
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        return execute_retrieval(args, "repo_map", env)


@dataclass
class CodeContextTool:
    name: str = "code_context"
    description: str = "Return issue-relevant Python code snippets with paths, symbols, line ranges, and class context within a character budget."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 256, "maximum": 20000},
                "max_files": {"type": "integer", "minimum": 1, "maximum": 20},
                "snippet_lines": {"type": "integer", "minimum": 0, "maximum": 80},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        return execute_retrieval(args, "context", env)


register(CodeSearchTool())
register(RepoMapTool())
register(CodeContextTool())
