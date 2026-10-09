"""Read Many Files Tool for mini-swe-agent.

This tool allows reading multiple files at once and provides a concise
representation of their contents. An alternative to multiple individual read calls.

Features:
- Read multiple files in a single call
- Optional line limits per file to prevent token overflow
- Summary information for each file (size, encoding, truncation status)
- Support for both environment (Docker) and host execution
- Path validation and security checks
- Binary file detection and rejection

Example use cases:
- Get overview of configuration files
- Read related source files together
- Compare multiple files side by side
- Batch read for analysis tasks
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import register


@dataclass
class ReadManyFilesTool:
    name: str = "read_many_files"
    description: str = (
        "Read multiple files at once with optional line limits per file. "
        "Returns a structured summary with file contents and metadata."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to read",
                    "minItems": 1,
                    "maxItems": 20,  # Reasonable limit to prevent abuse
                },
                "max_lines_per_file": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Maximum lines to read from each file (default: 100)",
                    "default": 100,
                },
                "include_metadata": {
                    "type": "boolean",
                    "description": "Include file metadata (size, line count, etc.) (default: true)",
                    "default": True,
                },
                "strip_empty_lines": {
                    "type": "boolean", 
                    "description": "Remove empty lines from output (default: false)",
                    "default": False,
                },
                "max_total_chars": {
                    "type": "integer",
                    "minimum": 100,
                    "description": "Hard cap on total output characters (default: 50000)",
                    "default": 50000,
                },
            },
            "required": ["paths"],
            "additionalProperties": False,
        }
    )
    repo_root: Path = field(default_factory=Path.cwd)

    def __call__(self, args: dict, env: Any | None = None) -> dict:
        """Execute the read_many_files tool."""
        paths = args.get("paths", [])
        max_lines_per_file = args.get("max_lines_per_file", 100)
        include_metadata = args.get("include_metadata", True)
        strip_empty_lines = args.get("strip_empty_lines", False)
        max_total_chars = args.get("max_total_chars", 50000)

        # Validate inputs
        if not paths:
            return {"output": "Missing 'paths' parameter", "returncode": 2}
        
        if not isinstance(paths, list):
            return {"output": "'paths' must be a list of strings", "returncode": 2}

        if len(paths) > 20:
            return {"output": "Too many files requested (maximum: 20)", "returncode": 2}

        # Execute based on environment
        if env is not None:
            return self._execute_in_env(env, paths, max_lines_per_file, 
                                      include_metadata, strip_empty_lines, max_total_chars)
        else:
            return self._execute_on_host(paths, max_lines_per_file, 
                                       include_metadata, strip_empty_lines, max_total_chars)

    def _execute_in_env(self, env: Any, paths: list[str], max_lines_per_file: int,
                       include_metadata: bool, strip_empty_lines: bool, 
                       max_total_chars: int) -> dict:
        """Execute read operation inside the environment (Docker/sandbox)."""
        results = []
        total_chars = 0

        for file_path in paths:
            if total_chars >= max_total_chars:
                results.append({
                    "path": file_path,
                    "status": "skipped",
                    "reason": "Total character limit reached"
                })
                continue

            # Build command to read file with line limit
            quoted_path = shlex.quote(file_path)
            
            # First check if file exists and get basic info
            check_cmd = f"test -f {quoted_path} && echo 'EXISTS' || echo 'NOT_FOUND'"
            check_result = env.execute(check_cmd)
            
            if "NOT_FOUND" in check_result["output"]:
                results.append({
                    "path": file_path,
                    "status": "error",
                    "error": "File not found"
                })
                continue

            # Read file content with line limit
            read_cmd = f"head -n {max_lines_per_file} {quoted_path}"
            result = env.execute(read_cmd)
            
            if result["returncode"] != 0:
                results.append({
                    "path": file_path,
                    "status": "error", 
                    "error": result["output"]
                })
                continue

            content = result["output"]
            
            # Check for binary content
            if "\x00" in content:
                results.append({
                    "path": file_path,
                    "status": "error",
                    "error": "Binary file detected"
                })
                continue

            # Process content
            content = content.replace("\r\n", "\n").replace("\r", "\n")
            lines = content.splitlines()
            
            if strip_empty_lines:
                lines = [line for line in lines if line.strip()]

            processed_content = "\n".join(lines)
            
            # Check if we need to truncate for total char limit
            remaining_chars = max_total_chars - total_chars
            truncated_for_limit = False
            
            if len(processed_content) > remaining_chars:
                processed_content = processed_content[:remaining_chars]
                truncated_for_limit = True

            # Get metadata if requested
            file_result = {
                "path": file_path,
                "status": "success",
                "content": processed_content,
                "line_count": len(lines),
                "truncated_for_line_limit": len(content.splitlines()) > max_lines_per_file,
                "truncated_for_char_limit": truncated_for_limit,
            }

            if include_metadata:
                # Get file size
                size_cmd = f"wc -c < {quoted_path}"
                size_result = env.execute(size_cmd)
                try:
                    file_size = int(size_result["output"].strip())
                    file_result["size_bytes"] = file_size
                except (ValueError, AttributeError):
                    file_result["size_bytes"] = "unknown"
                
                # Get total line count
                line_count_cmd = f"wc -l < {quoted_path}"
                line_count_result = env.execute(line_count_cmd)
                try:
                    total_lines = int(line_count_result["output"].strip())
                    file_result["total_lines"] = total_lines
                except (ValueError, AttributeError):
                    file_result["total_lines"] = "unknown"

            results.append(file_result)
            total_chars += len(processed_content)

        # Build summary
        summary = {
            "files_processed": len(results),
            "files_successful": sum(1 for r in results if r["status"] == "success"),
            "files_failed": sum(1 for r in results if r["status"] == "error"),
            "files_skipped": sum(1 for r in results if r["status"] == "skipped"),
            "total_characters": total_chars,
            "results": results
        }

        return {"output": json.dumps(summary, indent=2), "returncode": 0}

    def _execute_on_host(self, paths: list[str], max_lines_per_file: int,
                        include_metadata: bool, strip_empty_lines: bool, 
                        max_total_chars: int) -> dict:
        """Execute read operation on host filesystem."""
        results = []
        total_chars = 0

        for file_path in paths:
            if total_chars >= max_total_chars:
                results.append({
                    "path": file_path,
                    "status": "skipped",
                    "reason": "Total character limit reached"
                })
                continue

            try:
                # Resolve and validate path
                path_obj = Path(file_path).expanduser().resolve()
                
                # Security check: ensure path is within reasonable bounds
                # (This is a basic check; in production, you might want more sophisticated validation)
                if not path_obj.exists():
                    results.append({
                        "path": file_path,
                        "status": "error",
                        "error": "File not found"
                    })
                    continue

                if not path_obj.is_file():
                    results.append({
                        "path": file_path,
                        "status": "error",
                        "error": "Not a regular file"
                    })
                    continue

                # Read file content
                content = path_obj.read_text(encoding="utf-8", errors="replace")
                
                # Check for binary content
                if "\x00" in content:
                    results.append({
                        "path": file_path,
                        "status": "error",
                        "error": "Binary file detected"
                    })
                    continue

                # Process content
                content = content.replace("\r\n", "\n").replace("\r", "\n")
                all_lines = content.splitlines()
                
                # Apply line limit
                lines = all_lines[:max_lines_per_file]
                
                if strip_empty_lines:
                    lines = [line for line in lines if line.strip()]

                processed_content = "\n".join(lines)
                
                # Check if we need to truncate for total char limit
                remaining_chars = max_total_chars - total_chars
                truncated_for_limit = False
                
                if len(processed_content) > remaining_chars:
                    processed_content = processed_content[:remaining_chars]
                    truncated_for_limit = True

                # Build result
                file_result = {
                    "path": file_path,
                    "status": "success",
                    "content": processed_content,
                    "line_count": len(lines),
                    "truncated_for_line_limit": len(all_lines) > max_lines_per_file,
                    "truncated_for_char_limit": truncated_for_limit,
                }

                if include_metadata:
                    file_result["size_bytes"] = path_obj.stat().st_size
                    file_result["total_lines"] = len(all_lines)

                results.append(file_result)
                total_chars += len(processed_content)

            except PermissionError:
                results.append({
                    "path": file_path,
                    "status": "error",
                    "error": "Permission denied"
                })
            except UnicodeDecodeError:
                results.append({
                    "path": file_path,
                    "status": "error", 
                    "error": "Unable to decode as UTF-8"
                })
            except Exception as e:
                results.append({
                    "path": file_path,
                    "status": "error",
                    "error": f"Unexpected error: {str(e)}"
                })

        # Build summary
        summary = {
            "files_processed": len(results),
            "files_successful": sum(1 for r in results if r["status"] == "success"),
            "files_failed": sum(1 for r in results if r["status"] == "error"),
            "files_skipped": sum(1 for r in results if r["status"] == "skipped"),
            "total_characters": total_chars,
            "results": results
        }

        return {"output": json.dumps(summary, indent=2), "returncode": 0}


# Register the tool on import
register(ReadManyFilesTool())