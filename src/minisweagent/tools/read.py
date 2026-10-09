"""Refined read_file tool with targeted line selection.

This module provides a refined read_file tool that supports:
- lines: exact line numbers
- range: inclusive start-end
- head: first N lines
- tail: last N lines
- around: window around a line (radius)
- max_chars truncation
- Path traversal protection
- Binary file rejection
- Optional comment stripping

The tool follows the Tool protocol and returns {"output": str, "returncode": int}.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from . import register


@dataclass
class RefinedReadFile:
    name: str = "refined_read_file"
    description: str = "Read a text file with targeted line selection to reduce tokens."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"},
                "selector": {
                    "type": "object",
                    "description": "Line selection strategy (provide exactly one)",
                    "properties": {
                        "lines": {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 1},
                            "description": "Exact line numbers (1-indexed)",
                        },
                        "range": {
                            "type": "object",
                            "properties": {
                                "start": {"type": "integer", "minimum": 1},
                                "end": {"type": "integer", "minimum": 1},
                            },
                            "required": ["start", "end"],
                            "description": "Inclusive line range",
                        },
                        "head": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "First N lines",
                        },
                        "tail": {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Last N lines",
                        },
                        "around": {
                            "type": "object",
                            "properties": {
                                "line": {"type": "integer", "minimum": 1},
                                "radius": {"type": "integer", "minimum": 0},
                            },
                            "required": ["line", "radius"],
                            "description": "Window around a line",
                        },
                    },
                },
                "strip_comments": {
                    "type": "boolean",
                    "description": "Remove comments (best-effort for .py and // languages)",
                    "default": False,
                },
                "max_chars": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Hard cap on output characters",
                    "default": 20000,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        }
    )

    repo_root: Path = field(default_factory=Path.cwd)

    def __call__(self, args: dict, env=None) -> dict:
        path_arg = args.get("path", "")
        selector = args.get("selector", {})
        strip_comments = args.get("strip_comments", False)
        max_chars = args.get("max_chars", 20000)

        if not path_arg:
            return {"output": "Missing 'path'", "returncode": 2}

        # If environment is provided, execute inside sandbox (e.g., Docker for SWEBench)
        if env is not None:
            return self._execute_in_env(env, path_arg, selector, strip_comments, max_chars)

        # Fallback: host filesystem read
        return self._execute_on_host(path_arg, selector, strip_comments, max_chars)

    def _execute_in_env(self, env, path_arg: str, selector: dict, strip_comments: bool, max_chars: int) -> dict:
        """Execute read operation inside the environment (Docker/sandbox)."""
        # Build bash command to read file with line selection
        cmd = self._build_bash_command(path_arg, selector)

        # Execute in environment
        result = env.execute(cmd)

        if result["returncode"] != 0:
            return result

        # Process the output
        text = result["output"]

        # Reject binary content
        if "\x00" in text:
            return {"output": f"Binary file rejected: {path_arg}", "returncode": 1}

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.splitlines(keepends=True)

        # Determine start_line based on selector
        start_line = self._get_start_line_from_selector(selector, len(lines))

        # Strip comments if requested
        if strip_comments:
            suffix = Path(path_arg).suffix
            lines = self._strip_comments(lines, suffix)

        # Join and enforce max_chars
        result_content = "".join(lines)
        truncated = len(result_content) > max_chars
        if truncated:
            result_content = result_content[:max_chars]

        # Build result metadata
        result_data = {
            "path": str(path_arg),
            "encoding": "utf-8",
            "start_line": start_line,
            "line_count": len(lines),
            "truncated": truncated,
            "content": result_content,
        }

        return {"output": json.dumps(result_data, indent=2), "returncode": 0}

    def _build_bash_command(self, path_arg: str, selector: dict) -> str:
        """Build bash command for line selection using sed/head/tail."""
        quoted_path = shlex.quote(path_arg)

        # No selector = read entire file
        if not selector:
            return f"cat -- {quoted_path}"

        # lines: exact line numbers
        if "lines" in selector:
            line_nums = selector["lines"]
            # Use sed to print specific lines
            sed_expr = ";".join([f"{ln}p" for ln in sorted(set(line_nums))])
            return f"sed -n '{sed_expr}' {quoted_path}"

        # range: inclusive start-end
        if "range" in selector:
            start = selector["range"]["start"]
            end = selector["range"]["end"]
            return f"sed -n '{start},{end}p' {quoted_path}"

        # head: first N lines
        if "head" in selector:
            n = selector["head"]
            return f"head -n {n} {quoted_path}"

        # tail: last N lines
        if "tail" in selector:
            n = selector["tail"]
            return f"tail -n {n} {quoted_path}"

        # around: window around a line
        if "around" in selector:
            center = selector["around"]["line"]
            radius = selector["around"]["radius"]
            start = max(1, center - radius)
            end = center + radius
            return f"sed -n '{start},{end}p' {quoted_path}"

        return f"cat -- {quoted_path}"

    def _get_start_line_from_selector(self, selector: dict, line_count: int) -> int:
        """Determine the starting line number based on selector."""
        if not selector:
            return 1

        if "lines" in selector:
            line_nums = selector["lines"]
            return min(line_nums) if line_nums else 1

        if "range" in selector:
            return selector["range"]["start"]

        if "head" in selector:
            return 1

        if "tail" in selector:
            n = selector["tail"]
            return max(1, line_count - n + 1) if n > 0 else line_count

        if "around" in selector:
            center = selector["around"]["line"]
            radius = selector["around"]["radius"]
            return max(1, center - radius)

        return 1

    def _execute_on_host(self, path_arg: str, selector: dict, strip_comments: bool, max_chars: int) -> dict:
        """Execute read operation on host filesystem."""
        # Resolve and validate path
        try:
            resolved_path = self._resolve_path(path_arg)
        except ValueError as e:
            return {"output": str(e), "returncode": 1}

        # Read file content
        try:
            content = resolved_path.read_bytes()
        except FileNotFoundError:
            return {"output": f"File not found: {path_arg}", "returncode": 2}
        except IsADirectoryError:
            return {"output": f"Is a directory: {path_arg}", "returncode": 21}
        except PermissionError:
            return {"output": f"Permission denied: {path_arg}", "returncode": 13}
        except Exception as e:
            return {"output": f"Error reading file: {e}", "returncode": 1}

        # Reject binary files
        if b"\x00" in content:
            return {"output": f"Binary file rejected: {path_arg}", "returncode": 1}

        # Decode text
        try:
            text = content.decode("utf-8", errors="replace")
        except Exception as e:
            return {"output": f"Error decoding file: {e}", "returncode": 1}

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.splitlines(keepends=True)
        total_lines = len(lines)

        # Apply selector
        try:
            selected_lines, start_line = self._apply_selector(lines, selector)
        except ValueError as e:
            return {"output": str(e), "returncode": 22}

        # Strip comments if requested
        if strip_comments:
            selected_lines = self._strip_comments(selected_lines, resolved_path.suffix)

        # Join and enforce max_chars
        result_content = "".join(selected_lines)
        truncated = len(result_content) > max_chars
        if truncated:
            result_content = result_content[:max_chars]

        # Build result metadata
        result = {
            "path": str(path_arg),
            "encoding": "utf-8",
            "start_line": start_line,
            "line_count": len(selected_lines),
            "truncated": truncated,
            "content": result_content,
        }

        return {"output": json.dumps(result, indent=2), "returncode": 0}

    def _resolve_path(self, path_arg: str) -> Path:
        """Resolve path and deny traversal outside repo root."""
        try:
            p = Path(path_arg).expanduser()
            if not p.is_absolute():
                p = self.repo_root / p
            resolved = p.resolve()

            # Check if resolved path is within repo root
            try:
                resolved.relative_to(self.repo_root.resolve())
            except ValueError:
                raise ValueError(f"Path traversal denied: {path_arg}")

            return resolved
        except Exception as e:
            raise ValueError(f"Invalid path: {e}")

    def _apply_selector(self, lines: list[str], selector: dict) -> tuple[list[str], int]:
        """Apply line selector and return (selected_lines, start_line_number)."""
        total_lines = len(lines)

        # Count selectors
        selector_count = sum(1 for k in ["lines", "range", "head", "tail", "around"] if k in selector)
        if selector_count > 1:
            raise ValueError("Provide exactly one selector: lines, range, head, tail, or around")

        # No selector = read entire file
        if selector_count == 0:
            return lines, 1

        # lines: exact line numbers
        if "lines" in selector:
            line_nums = selector["lines"]
            if not isinstance(line_nums, list) or not line_nums:
                raise ValueError("'lines' must be a non-empty array")

            selected = []
            for ln in sorted(set(line_nums)):
                if ln < 1:
                    raise ValueError(f"Line number {ln} must be >= 1")
                if ln <= total_lines:
                    selected.append(lines[ln - 1])

            start_line = min(line_nums) if line_nums else 1
            return selected, start_line

        # range: inclusive start-end
        if "range" in selector:
            r = selector["range"]
            start = r.get("start", 1)
            end = r.get("end", total_lines)

            if start < 1 or end < 1:
                raise ValueError("Range start and end must be >= 1")
            if start > end:
                raise ValueError("Range start cannot exceed end")

            # Clamp to file bounds
            start = max(1, min(start, total_lines))
            end = max(1, min(end, total_lines))

            return lines[start - 1 : end], start

        # head: first N lines
        if "head" in selector:
            n = selector["head"]
            if not isinstance(n, int) or n < 0:
                raise ValueError("'head' must be >= 0")
            n = min(n, total_lines)
            return lines[:n], 1

        # tail: last N lines
        if "tail" in selector:
            n = selector["tail"]
            if not isinstance(n, int) or n < 0:
                raise ValueError("'tail' must be >= 0")
            n = min(n, total_lines)
            start_line = max(1, total_lines - n + 1) if n > 0 else total_lines
            return lines[-n:] if n > 0 else [], start_line

        # around: window around a line
        if "around" in selector:
            a = selector["around"]
            center = a.get("line", 1)
            radius = a.get("radius", 0)

            if center < 1:
                raise ValueError("'around.line' must be >= 1")
            if radius < 0:
                raise ValueError("'around.radius' must be >= 0")

            # Clamp window to file bounds
            start = max(1, center - radius)
            end = min(total_lines, center + radius)

            return lines[start - 1 : end], start

        return lines, 1

    def _strip_comments(self, lines: list[str], suffix: str) -> list[str]:
        """Best-effort comment stripping for .py and // languages."""
        if suffix == ".py":
            return [self._strip_python_comment(line) for line in lines]
        elif suffix in {".js", ".ts", ".java", ".c", ".cpp", ".go", ".rs"}:
            return [self._strip_slash_comment(line) for line in lines]
        return lines

    def _strip_python_comment(self, line: str) -> str:
        """Remove Python # comments (naive, doesn't handle strings)."""
        idx = line.find("#")
        if idx >= 0:
            return line[:idx].rstrip() + "\n" if line.endswith("\n") else line[:idx].rstrip()
        return line

    def _strip_slash_comment(self, line: str) -> str:
        """Remove // comments (naive, doesn't handle strings)."""
        idx = line.find("//")
        if idx >= 0:
            return line[:idx].rstrip() + "\n" if line.endswith("\n") else line[:idx].rstrip()
        return line


# Register the refined read_file tool
register(RefinedReadFile())
