"""Lightweight tool registry for mini-swe-agent.

This module defines a very small Tool protocol and a global registry
that lets projects (or students) add tools with a single import.

Tools should return a dict shaped like the Environment.execute result:
    {"output": str, "returncode": int}

Keeping this consistent makes it trivial to surface tool output in
agent observations alongside bash command output.
"""

from __future__ import annotations

from typing import Any, Protocol

from minisweagent.utils.log import logger

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


__all__ = ["Tool", "REGISTRY", "register", "list_tool_specs"]
