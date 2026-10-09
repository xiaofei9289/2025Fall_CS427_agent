"""Basic, safe local tools: read_file and write_file.

Both tools are synchronous and return a dict matching the environment
execute result shape: {"output": str, "returncode": int}.

Safety considerations (kept simple on purpose for a starter set):
- Paths are resolved to absolute paths.
- write_file creates parent directories as needed.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
import shlex

from . import register


@dataclass
class ReadFile:
    name: str = "read_file"
    description: str = "Read a UTF-8 text file."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"},
            },
            "required": ["path"],
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        path_arg = str(args.get("path", ""))
        # If an environment is provided, run inside it so reads happen in the sandbox (e.g., /testbed)
        if env is not None:
            if not path_arg:
                return {"output": "Missing 'path'", "returncode": 2}
            cmd = f"cat -- {shlex.quote(path_arg)}"
            return env.execute(cmd)
        # Fallback: host filesystem read
        try:
            p = Path(path_arg).expanduser().resolve()
            content = p.read_text(encoding="utf-8", errors="replace")
            return {"output": content, "returncode": 0}
        except FileNotFoundError:
            return {"output": f"File not found: {path_arg}", "returncode": 2}
        except IsADirectoryError:
            return {"output": f"Is a directory: {path_arg}", "returncode": 21}
        except PermissionError:
            return {"output": f"Permission denied: {path_arg}", "returncode": 13}
        except Exception as e:  # pragma: no cover - generic safety net
            return {"output": f"Error reading file: {e}", "returncode": 1}


@dataclass
class WriteFile:
    name: str = "write_file"
    description: str = "Write content to a file inside the workspace."
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        path_arg = str(args.get("path", ""))
        content = args.get("content", "")
        
        if not path_arg:
            return {"output": "Missing 'path'", "returncode": 2}
        
        # If an environment is provided, run inside it so writes happen in the sandbox (e.g., /testbed)
        if env is not None:
            return self._execute_in_env(env, path_arg, content)
        
        # Fallback: host filesystem write
        return self._execute_on_host(path_arg, content)
    
    def _execute_in_env(self, env, path_arg: str, content: str) -> dict:
        """Execute write in environment using bash commands."""
        # Create parent directories first
        parent_dir = Path(path_arg).parent
        if str(parent_dir) != ".":
            mkdir_cmd = f"mkdir -p -- {shlex.quote(str(parent_dir))}"
            mkdir_result = env.execute(mkdir_cmd)
            if mkdir_result["returncode"] != 0:
                return {"output": f"write_file error: Failed to create directories: {mkdir_result['output']}", "returncode": 1}
        
        # Write content using base64 encoding to safely handle any content including newlines and special characters
        content_b64 = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = f"printf '%s' {shlex.quote(content_b64)} | base64 -d > {shlex.quote(path_arg)}"
        result = env.execute(cmd)
        
        if result["returncode"] == 0:
            return {"output": f"write_file: wrote {len(content.encode('utf-8'))} bytes to {path_arg}.", "returncode": 0}
        return {"output": f"write_file error: {result['output']}", "returncode": result["returncode"]}
    
    def _execute_on_host(self, path_arg: str, content: str) -> dict:
        """Execute write on host filesystem."""
        try:
            p = Path(path_arg).expanduser()
            # Create parent directories if they don't exist
            p.parent.mkdir(parents=True, exist_ok=True)
            # Write content
            p.write_text(content, encoding="utf-8")
            bytes_written = len(content.encode("utf-8"))
            return {"output": f"write_file: wrote {bytes_written} bytes to {p.resolve()}.", "returncode": 0}
        except PermissionError:
            return {"output": f"write_file error: Permission denied: {path_arg}", "returncode": 13}
        except OSError as e:
            return {"output": f"write_file error: {e}", "returncode": 1}
        except Exception as e:  # pragma: no cover - generic safety net
            return {"output": f"write_file error: {e}", "returncode": 1}

# Register defaults on import for convenience
register(ReadFile())
register(WriteFile())
