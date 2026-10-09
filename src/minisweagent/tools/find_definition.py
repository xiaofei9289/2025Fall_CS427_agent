"""Find definition tool for locating function, class, and variable definitions.

This tool helps navigate codebases by finding where symbols are defined.
Works in both local and Docker environments.

Example use cases:
- Find where a function is defined: find_definition("function_name")
- Find a class definition: find_definition("ClassName")
- Find definitions in a specific file or directory
"""

from __future__ import annotations

import ast
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from . import register


@dataclass
class FindDefinitionTool:
    name: str = "find_definition"
    description: str = (
        "Find where a function, class, or variable is defined. "
        "Searches for definitions matching the symbol name and returns location with context."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Name of the function, class, or variable to find",
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
                    "description": "Number of context lines to show around the definition (default: 5)",
                    "default": 5,
                },
            },
            "required": ["symbol"],
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        symbol = args.get("symbol", "")
        path_arg = args.get("path", ".")
        symbol_type = args.get("symbol_type", "any")
        context_lines = args.get("context_lines", 5)

        if not symbol:
            return {"output": "Missing 'symbol' parameter", "returncode": 2}
        if not isinstance(context_lines, int) or context_lines < 0:
            return {"output": "context_lines must be a non-negative integer", "returncode": 2}
        if symbol_type not in ["any", "function", "class", "variable"]:
            return {"output": "symbol_type must be one of: any, function, class, variable", "returncode": 2}

        if env is not None:
            return self._find_in_env(env, symbol, path_arg, symbol_type, context_lines)

        return self._find_local(symbol, path_arg, symbol_type, context_lines)

    def _find_in_env(
        self,
        env,
        symbol: str,
        path: str,
        symbol_type: str,
        context_lines: int,
    ) -> dict:
        """Find definition using grep in Docker environment."""
        if path == ".":
            path = "/testbed"
        elif not path.startswith("/testbed"):
            if path.startswith("/"):
                return {
                    "output": f"Path must be within /testbed: {path}",
                    "returncode": 2,
                }
            path = f"/testbed/{path.lstrip('./')}"

        patterns = self._build_grep_patterns(symbol, symbol_type)

        results = []
        for pattern in patterns:
            cmd = f"grep -rn -A {context_lines} -B {context_lines} -- {shlex.quote(pattern)} {shlex.quote(path)} 2>/dev/null || true"
            result = env.execute(cmd)

            if result["returncode"] == 0 and result["output"].strip():
                for line in result["output"].strip().split("\n"):
                    if ":" in line:
                        parts = line.split(":", 2)
                        if len(parts) >= 3:
                            file_path = parts[0]
                            line_num = parts[1]
                            content = parts[2]
                            if self._is_definition_line(content, symbol, symbol_type):
                                results.append((file_path, line_num, content))

        if not results:
            return {
                "output": f"No definition found for '{symbol}' (type: {symbol_type}) in {path}",
                "returncode": 0,
            }

        output_lines = [f"Found {len(results)} definition(s) for '{symbol}':\n"]
        for file_path, line_num, content in results[:10]:
            output_lines.append(f"{file_path}:{line_num}: {content.strip()}")

        if len(results) > 10:
            output_lines.append(f"\n... and {len(results) - 10} more result(s)")

        return {"output": "\n".join(output_lines), "returncode": 0}

    def _find_local(
        self,
        symbol: str,
        path_arg: str,
        symbol_type: str,
        context_lines: int,
    ) -> dict:
        """Find definition using Python AST parsing on local filesystem."""
        try:
            path_obj = Path(path_arg).expanduser().resolve()

            if not path_obj.exists():
                return {"output": f"Path not found: {path_arg}", "returncode": 2}

            results: list[tuple[str, int, str, str]] = []

            if path_obj.is_file():
                if path_obj.suffix == ".py":
                    results.extend(self._parse_python_file(path_obj, symbol, symbol_type, context_lines))
                else:
                    results.extend(self._grep_file(path_obj, symbol, symbol_type, context_lines))
            else:
                for py_file in path_obj.rglob("*.py"):
                    results.extend(self._parse_python_file(py_file, symbol, symbol_type, context_lines))

            if not results:
                return {
                    "output": f"No definition found for '{symbol}' (type: {symbol_type}) in {path_arg}",
                    "returncode": 0,
                }

            output_lines = [f"Found {len(results)} definition(s) for '{symbol}':\n"]
            for file_path, line_num, _content, context in results[:10]:
                output_lines.append(f"{file_path}:{line_num}:")
                output_lines.append(context)

            if len(results) > 10:
                output_lines.append(f"\n... and {len(results) - 10} more result(s)")

            return {"output": "\n".join(output_lines), "returncode": 0}

        except PermissionError:
            return {"output": f"Permission denied: {path_arg}", "returncode": 13}
        except Exception as e:
            return {"output": f"Error finding definition: {e}", "returncode": 1}

    def _build_grep_patterns(self, symbol: str, symbol_type: str) -> list[str]:
        """Build grep patterns to find definitions."""
        patterns = []
        escaped_symbol = re.escape(symbol)

        if symbol_type == "any" or symbol_type == "function":
            patterns.append(f"^def {escaped_symbol}\\b")
            patterns.append(f"^\\s+def {escaped_symbol}\\b")

        if symbol_type == "any" or symbol_type == "class":
            patterns.append(f"^class {escaped_symbol}\\b")

        if symbol_type == "any" or symbol_type == "variable":
            patterns.append(f"^{escaped_symbol}\\s*=")
            patterns.append(f"^\\s+{escaped_symbol}\\s*=")

        return patterns

    def _is_definition_line(self, line: str, symbol: str, symbol_type: str) -> bool:
        """Check if a line is actually a definition line."""
        line = line.strip()
        if not line:
            return False

        if symbol_type == "any" or symbol_type == "function":
            if re.match(rf"^\s*def\s+{re.escape(symbol)}\s*\(", line):
                return True

        if symbol_type == "any" or symbol_type == "class":
            if re.match(rf"^\s*class\s+{re.escape(symbol)}\s*[(:]", line):
                return True

        if symbol_type == "any" or symbol_type == "variable":
            if re.match(rf"^\s*{re.escape(symbol)}\s*=", line):
                return True

        return False

    def _parse_python_file(
        self,
        file_path: Path,
        symbol: str,
        symbol_type: str,
        context_lines: int,
    ) -> list[tuple[str, int, str, str]]:
        """Parse Python file using AST to find definitions."""
        results: list[tuple[str, int, str, str]] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()

            try:
                tree = ast.parse(content, filename=str(file_path))
            except SyntaxError:
                return self._grep_file(file_path, symbol, symbol_type, context_lines)

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and (symbol_type == "any" or symbol_type == "function"):
                    if node.name == symbol:
                        context = self._get_context(lines, node.lineno - 1, context_lines)
                        results.append((str(file_path), node.lineno, lines[node.lineno - 1], context))

                elif isinstance(node, ast.ClassDef) and (symbol_type == "any" or symbol_type == "class"):
                    if node.name == symbol:
                        context = self._get_context(lines, node.lineno - 1, context_lines)
                        results.append((str(file_path), node.lineno, lines[node.lineno - 1], context))

                elif isinstance(node, ast.Assign) and (symbol_type == "any" or symbol_type == "variable"):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and target.id == symbol:
                            context = self._get_context(lines, node.lineno - 1, context_lines)
                            results.append((str(file_path), node.lineno, lines[node.lineno - 1], context))

        except Exception:
            return self._grep_file(file_path, symbol, symbol_type, context_lines)

        return results

    def _grep_file(
        self,
        file_path: Path,
        symbol: str,
        symbol_type: str,
        context_lines: int,
    ) -> list[tuple[str, int, str, str]]:
        """Use grep-like pattern matching to find definitions."""
        results: list[tuple[str, int, str, str]] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()

            patterns = self._build_grep_patterns(symbol, symbol_type)
            for i, line in enumerate(lines):
                for pattern in patterns:
                    if re.search(pattern, line):
                        context = self._get_context(lines, i, context_lines)
                        results.append((str(file_path), i + 1, line, context))
                        break

        except Exception:
            pass

        return results

    def _get_context(self, lines: list[str], line_index: int, context_lines: int) -> str:
        """Get context lines around a definition."""
        start = max(0, line_index - context_lines)
        end = min(len(lines), line_index + context_lines + 1)

        context_parts = []
        for i in range(start, end):
            marker = ">>>" if i == line_index else "   "
            context_parts.append(f"{marker} {i + 1:4d}: {lines[i]}")

        return "\n".join(context_parts)


register(FindDefinitionTool())
