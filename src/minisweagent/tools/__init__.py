"""Lightweight tool registry for mini-swe-agent.

This module defines a very small Tool protocol and a global registry
that lets projects (or students) add tools with a single import.

Tools should return a dict shaped like the Environment.execute result:
    {"output": str, "returncode": int}

Keeping this consistent makes it trivial to surface tool output in
agent observations alongside bash command output.
"""

from __future__ import annotations

import posixpath
import shlex
from pathlib import Path
from typing import Any, Protocol

from minisweagent.utils.log import logger


def workspace_root(env: Any) -> str:
    """The environment's working directory as an absolute path (host cwd when unset)."""
    cwd = getattr(getattr(env, "config", None), "cwd", "") or ""
    return str(cwd) if cwd else str(Path.cwd())


def ensure_all_within_workspace(env: Any, paths: list[str]) -> dict | None:
    """Reject paths that resolve outside the environment workspace; None when all are allowed.

    Resolution runs inside the environment so relative paths and symlink escapes
    are judged there; hosts without ``realpath -m`` fall back to lexical checks.
    A path-component check avoids prefix mistakes like ``/testbed-other``.
    """
    root = workspace_root(env)
    result = env.execute("realpath -m -- " + " ".join(shlex.quote(p) for p in paths))
    if result["returncode"] == 0 and (lines := result["output"].strip().splitlines()) and len(lines) == len(paths):
        resolved = [line.strip() for line in lines]
    else:
        resolved = [
            posixpath.normpath(p if p.startswith("/") else posixpath.join(root, p)) for p in paths
        ]
    prefix = root.rstrip("/") + "/"
    outside = [p for p, r in zip(paths, resolved) if r != root and not r.startswith(prefix)]
    if outside:
        return {"output": f"Paths must be within {root}, got: {outside}", "returncode": 1}
    return None


def ensure_within_workspace(env: Any, path_arg: str) -> dict | None:
    """Single-path variant of ``ensure_all_within_workspace``."""
    return ensure_all_within_workspace(env, [path_arg])


class Tool(Protocol):
    """Protocol for simple callable tools.

    - name: unique identifier for dispatching
    - description: short human-readable description
    - parameters: JSON-schema-like dict for arguments
    - __call__(args): executes the tool and returns {"output", "returncode"}
    """

    name: str
    description: str
    parameters: dict

    def __call__(self, args: dict, env: Any | None = None) -> dict: ...


# Global registry
REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    """Register a tool instance in the global REGISTRY and return it."""
    logger.info(f"Registering tool: {tool.name}")
    REGISTRY[tool.name] = tool
    return tool


def list_tool_specs() -> list[dict[str, Any]]:
    """Return lightweight specs for all registered tools.

    Useful for prompting (enumerating available tools and schemas).
    """
    specs: list[dict[str, Any]] = []
    for t in REGISTRY.values():
        specs.append({
            "name": t.name,
            "description": t.description,
            "parameters": t.parameters,
        })
    return specs


__all__ = ["Tool", "REGISTRY", "register", "list_tool_specs",
           "workspace_root", "ensure_within_workspace", "ensure_all_within_workspace"]
