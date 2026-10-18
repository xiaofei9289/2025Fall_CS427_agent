"""Find definition tool for locating Python symbol definitions.

The tool reuses the same self-contained AST index as ``code_search``. That keeps
host and container results consistent, avoids shell-specific grep behavior, and
makes async functions and annotated assignments visible.

Example use cases:
- Find where a function is defined: find_definition("function_name")
- Find a class definition: find_definition("ClassName")
- Find a qualified method: find_definition("ClassName.method")
- Find definitions in a specific file or directory
"""

from __future__ import annotations

import json
import posixpath
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from minisweagent.retrieval import repository

from . import ensure_within_workspace, register, workspace_root


@dataclass
class FindDefinitionTool:
    name: str = "find_definition"
    description: str = (
        "Find Python function, class, or variable definitions by symbol name. "
        "Returns qualified names, line ranges, and surrounding context."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Name of the function, class, or variable to find; qualified names are supported",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path to search in (default: current directory)",
                },
                "symbol_type": {
                    "type": "string",
                    "enum": ["any", "function", "class", "variable"],
                    "description": "Type of symbol to find (default: any)",
                    "default": "any",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of context lines to show around each definition (default: 5)",
                    "default": 5,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum number of definitions to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["symbol"],
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        symbol = args.get("symbol", "")
        if not isinstance(symbol, str) or not symbol.strip():
            return {"output": "Missing 'symbol' parameter", "returncode": 2}
        symbol = symbol.strip()
        path_arg = args.get("path", ".")
        if not isinstance(path_arg, str) or not path_arg:
            path_arg = "."
        symbol_type = args.get("symbol_type", "any")
        context_lines = args.get("context_lines", 5)
        limit = args.get("limit", 10)

        if symbol_type not in ["any", "function", "class", "variable"]:
            return {"output": "symbol_type must be one of: any, function, class, variable", "returncode": 2}
        if not isinstance(context_lines, int) or context_lines < 0:
            return {"output": "context_lines must be a non-negative integer", "returncode": 2}
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            return {"output": "limit must be between 1 and 50", "returncode": 2}

        if env is not None:
            if rejected := ensure_within_workspace(env, path_arg):
                return rejected
            return self._find_in_env(env, symbol, path_arg, symbol_type, context_lines, limit)

        return self._find_local(symbol, path_arg, symbol_type, context_lines, limit)

    def _find_local(self, symbol: str, path: str, symbol_type: str, context_lines: int, limit: int) -> dict:
        """Find definitions on the host filesystem with the shared AST index."""
        try:
            return repository.find_definition(
                str(Path.cwd()),
                symbol,
                symbol_type,
                path,
                context_lines,
                limit,
            )
        except Exception as error:  # noqa: BLE001
            return {"output": f"Error finding definition: {error}", "returncode": 1}

    def _find_in_env(
        self,
        env,
        symbol: str,
        path: str,
        symbol_type: str,
        context_lines: int,
        limit: int,
    ) -> dict:
        """Run the shared AST index inside the environment without installing the package."""
        root = workspace_root(env)
        if path.startswith("/"):
            resolved_path = posixpath.normpath(path)
        else:
            resolved_path = posixpath.normpath(posixpath.join(root, path))
        payload = {
            "root": root,
            "symbol": symbol,
            "symbol_type": symbol_type,
            "path": resolved_path,
            "context_lines": context_lines,
            "limit": limit,
        }
        script = (
            Path(repository.__file__).read_text(encoding="utf-8")
            + "\nimport json\n"
            + "try:\n"
            + f"    result = find_definition(**{payload!r})\n"
            + "except Exception as error:\n"
            + "    result = {'output': 'Error finding definition: ' + str(error), 'returncode': 1}\n"
            + "print(json.dumps(result))\n"
        )
        output = env.execute(f"python -c {shlex.quote(script)}")
        if output["returncode"] != 0:
            return output
        try:
            return json.loads(output["output"])
        except json.JSONDecodeError:
            return {"output": output["output"], "returncode": 1}


register(FindDefinitionTool())
