"""Search tool for finding patterns in files with context.

This tool allows searching for literal text or regex patterns in files,
showing matching lines with configurable context (surrounding lines).
Works in both local and Docker environments.

Example use cases:
- Find function definitions: search for "def function_name"
- Find error patterns: search for "Error:" or "Exception"
- Locate TODO comments: search for "TODO"
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from . import register


@dataclass
class SearchFileTool:
    name: str = "search_file_content"
    description: str = (
        "Search for text patterns in a file and show surrounding context. "
        "Returns matching lines with line numbers and configurable context lines."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to search in",
                },
                "pattern": {
                    "type": "string",
                    "description": "Text pattern to search for (literal text or regex if use_regex is true)",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of lines to show before and after each match (default: 3)",
                },
                "use_regex": {
                    "type": "boolean",
                    "description": "Treat pattern as regex instead of literal text (default: false)",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Whether search should be case-sensitive (default: true)",
                },
            },
            "required": ["path", "pattern"],
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        path_arg = str(args.get("path", ""))
        pattern = args.get("pattern", "")
        context_lines = args.get("context_lines", 3)
        use_regex = args.get("use_regex", False)
        case_sensitive = args.get("case_sensitive", True)

        # Validate inputs
        if not path_arg:
            return {"output": "Missing 'path' parameter", "returncode": 2}
        if not pattern:
            return {"output": "Missing 'pattern' parameter", "returncode": 2}
        if not isinstance(context_lines, int) or context_lines < 0:
            return {"output": "context_lines must be a non-negative integer", "returncode": 2}

        # If running in Docker environment (SWEBench)
        if env is not None:
            # Validate path is within /testbed for safety
            if not path_arg.startswith("/testbed"):
                return {
                    "output": f"Path must be within /testbed directory, got: {path_arg}",
                    "returncode": 1,
                }
            return self._search_in_env(env, path_arg, pattern, context_lines, use_regex, case_sensitive)

        # Local filesystem search
        return self._search_local(path_arg, pattern, context_lines, use_regex, case_sensitive)

    def _search_in_env(
        self,
        env,
        path: str,
        pattern: str,
        context_lines: int,
        use_regex: bool,
        case_sensitive: bool,
    ) -> dict:
        """Search using grep in the Docker environment."""
        # Build grep command with appropriate flags
        flags = []
        if not case_sensitive:
            flags.append("-i")
        if use_regex:
            flags.append("-E")  # Extended regex
        else:
            flags.append("-F")  # Fixed string (literal)

        flags.append("-n")  # Show line numbers
        flags.append(f"-C {context_lines}")  # Context lines

        # Construct safe grep command
        flag_str = " ".join(flags)
        cmd = f"grep {flag_str} -- {shlex.quote(pattern)} {shlex.quote(path)} || test $? = 1"

        result = env.execute(cmd)

        # grep returns 1 if no matches found, which is not an error for us
        if result["returncode"] in (0, 1):
            if not result["output"].strip():
                return {"output": f"No matches found for '{pattern}' in {path}", "returncode": 0}
            return {"output": self._format_grep_output(result["output"], pattern), "returncode": 0}

        return result  # Return error as-is

    def _search_local(
        self,
        path_arg: str,
        pattern: str,
        context_lines: int,
        use_regex: bool,
        case_sensitive: bool,
    ) -> dict:
        """Search in local filesystem using Python."""
        try:
            path_obj = Path(path_arg).expanduser().resolve()

            # Validate path exists and is a file
            if not path_obj.exists():
                return {"output": f"File not found: {path_arg}", "returncode": 2}
            if not path_obj.is_file():
                return {"output": f"Not a file: {path_arg}", "returncode": 21}

            # Read file content
            content = path_obj.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()

            # Compile search pattern
            if use_regex:
                try:
                    regex_flags = 0 if case_sensitive else re.IGNORECASE
                    compiled_pattern = re.compile(pattern, regex_flags)
                except re.error as e:
                    return {"output": f"Invalid regex pattern: {e}", "returncode": 2}
            else:
                # For literal search, escape special chars and compile
                escaped = re.escape(pattern)
                regex_flags = 0 if case_sensitive else re.IGNORECASE
                compiled_pattern = re.compile(escaped, regex_flags)

            # Find all matching lines
            matches = []
            for i, line in enumerate(lines):
                if compiled_pattern.search(line):
                    matches.append(i)

            if not matches:
                return {"output": f"No matches found for '{pattern}' in {path_arg}", "returncode": 0}

            # Format output with context
            output = self._format_matches(lines, matches, context_lines, pattern)
            return {"output": output, "returncode": 0}

        except PermissionError:
            return {"output": f"Permission denied: {path_arg}", "returncode": 13}
        except Exception as e:
            return {"output": f"Error searching file: {e}", "returncode": 1}

    def _format_matches(
        self,
        lines: list[str],
        match_indices: list[int],
        context_lines: int,
        pattern: str,
    ) -> str:
        """Format search results with context and line numbers."""
        output_lines = []
        output_lines.append(f"Found {len(match_indices)} match(es) for '{pattern}':\n")

        # Group nearby matches to avoid duplicate context
        groups = []
        current_group = []

        for match_idx in match_indices:
            if not current_group or match_idx <= current_group[-1] + 2 * context_lines + 1:
                current_group.append(match_idx)
            else:
                groups.append(current_group)
                current_group = [match_idx]
        if current_group:
            groups.append(current_group)

        # Format each group
        for group in groups:
            start = max(0, group[0] - context_lines)
            end = min(len(lines), group[-1] + context_lines + 1)

            for i in range(start, end):
                line_num = i + 1
                line_content = lines[i]

                # Mark matching lines with indicator
                if i in group:
                    output_lines.append(f"{line_num:4d}:> {line_content}")
                else:
                    output_lines.append(f"{line_num:4d}:  {line_content}")

            # Add separator between groups
            if group != groups[-1]:
                output_lines.append("---")

        return "\n".join(output_lines)

    def _format_grep_output(self, grep_output: str, pattern: str) -> str:
        """Add a header to grep output."""
        lines = grep_output.strip().split("\n")
        match_count = sum(1 for line in lines if line and not line.startswith("--"))
        header = f"Found {match_count} match(es) for '{pattern}':\n"
        return header + grep_output


# Register the tool
register(SearchFileTool())
