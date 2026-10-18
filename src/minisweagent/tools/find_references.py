"""Find references/callers of a Python symbol using a lightweight AST scan."""

from __future__ import annotations

import json
import posixpath
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from minisweagent.retrieval import relations, repository

from . import ensure_within_workspace, register, workspace_root

MAX_CHARS = 12000


def _script(
    root: str,
    symbol: str,
    path_filter: str,
    context_lines: int,
    limit: int,
) -> str:
    return (
        Path(repository.__file__).read_text(encoding="utf-8")
        + "\n"
        + Path(relations.__file__).read_text(encoding="utf-8")
        + "\n"
        + "import json\n"
        + "from pathlib import Path\n"
        + f"root = {root!r}\n"
        + f"symbol = {symbol!r}\n"
        + f"path_filter = {path_filter!r}\n"
        + f"context_lines = {int(context_lines)}\n"
        + f"limit = {int(limit)}\n"
        + "try:\n"
        + "    index = RepositoryIndex(Path(root))\n"
        + "    result = find_references(index, symbol, limit, path_filter)\n"
        + "    output = format_references(index, result, context_lines)\n"
        + "    payload = {'output': output, 'returncode': 0}\n"
        + "except Exception as error:\n"
        + "    payload = {'output': 'Error finding references: ' + str(error), 'returncode': 1}\n"
        + "print(json.dumps(payload))\n"
    )


@dataclass
class FindReferencesTool:
    name: str = "find_references"
    description: str = (
        "Find Python references, callers, imports, and base-class uses for a symbol. "
        "Returns definitions plus matching locations and one line of context. "
        "Use it after locating a symbol to see what else may be affected."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Function, class, method, or variable name; qualified names are supported",
                },
                "path": {
                    "type": "string",
                    "description": "File or directory to scan (default: current directory)",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Context lines around each reference (default: 1)",
                    "default": 1,
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum references to return (default: 50)",
                    "default": 50,
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
        context_lines = args.get("context_lines", 1)
        limit = args.get("limit", 50)
        if not isinstance(context_lines, int) or not 0 <= context_lines <= 20:
            return {"output": "context_lines must be an integer between 0 and 20", "returncode": 2}
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            return {"output": "limit must be between 1 and 100", "returncode": 2}

        if env is not None:
            if rejected := ensure_within_workspace(env, path_arg):
                return rejected
            root = workspace_root(env)
            if path_arg.startswith("/"):
                target = posixpath.normpath(path_arg)
            else:
                target = posixpath.normpath(posixpath.join(root, path_arg))
            return self._find_in_env(env, root, target, symbol, context_lines, limit)
        return self._find_local(path_arg, symbol, context_lines, limit)

    def _find_in_env(self, env, root: str, target: str, symbol: str, context_lines: int, limit: int) -> dict:
        check = env.execute(f"test -e {shlex.quote(target)}")
        if check["returncode"] != 0:
            return {"output": f"Path not found: {target}", "returncode": 2}
        is_file = env.execute(f"test -f {shlex.quote(target)}")["returncode"] == 0
        index_root = root if is_file else target
        path_filter = posixpath.relpath(target, root) if is_file else ""
        output = env.execute(f"python -c {shlex.quote(_script(index_root, symbol, path_filter, context_lines, limit))}")
        if output["returncode"] != 0:
            return output
        try:
            return json.loads(output["output"])
        except json.JSONDecodeError:
            return {"output": output["output"], "returncode": 1}

    def _find_local(self, path_arg: str, symbol: str, context_lines: int, limit: int) -> dict:
        root_path = Path.cwd().resolve()
        target = Path(path_arg).expanduser()
        target = target.resolve() if target.is_absolute() else (root_path / target).resolve()
        if not target.exists():
            return {"output": f"Path not found: {path_arg}", "returncode": 2}
        if target.is_file():
            try:
                index_root = root_path
                path_filter = target.relative_to(root_path).as_posix()
            except ValueError:
                # A host-side absolute file outside the process cwd: index its
                # parent and display paths relative to that parent.
                index_root = target.parent
                path_filter = target.name
        else:
            index_root = target
            path_filter = ""
        try:
            index = repository.RepositoryIndex(index_root)
            result = relations.find_references(index, symbol, limit, path_filter)
            return {"output": relations.format_references(index, result, context_lines), "returncode": 0}
        except (OSError, ValueError) as error:
            return {"output": f"Error finding references: {error}", "returncode": 1}


register(FindReferencesTool())
