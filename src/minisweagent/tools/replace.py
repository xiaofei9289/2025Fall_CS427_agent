"""
this is a replace tool that can search and then replace the content in the workspace

1. literal text replace to keep it safe
2. return a result dict with how many replacements were made

"""

from __future__ import annotations

import base64
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from . import register


@dataclass
class ReplaceTool:
    # the tool name
    name: str = "replace"
    # the tool description
    description: str = "Search and replace text in a file under the workspace. replace the first or all occurrences."
    # use dict to descript relevant parameters
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "path to the file",
                },
                "old_text": {
                    "type": "string",
                    "description": "content to search for",
                },
                "new_text": {
                    "type": "string",
                    "description": "content to be replaced",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences",
                    "default": True,
                },
            },
            "required": ["path", "old_text", "new_text"],
            "additionalProperties": False,
        }
    )

    # define a method that will take replacement actions
    # receive an args dict and return a result dict
    def __call__(self, args: dict, env=None) -> dict:
        # get all the parameters
        # get the file path
        path_arg = str(args.get("path", ""))
        # get the content that will be searched
        old_text = args.get("old_text", "")
        # get the new content that will replace the old text
        new_text = args.get("new_text", "")
        # set the default parameters that replace all the content
        replace_all = args.get("replace_all", True)
        # if fail to get file path
        if not path_arg:
            return {"output": "missing path", "returncode": 2}
        # if old_text is empty
        if not old_text:
            return {"output": "old_text empty is not allowed", "returncode": 2}

        # running in Docker environment (SWEBench), use Python for file operations
        if env is not None:
            return self._execute_in_env(env, path_arg, old_text, new_text, replace_all)

        # read the file content
        try:
            # Convert the path string into a Path object, expand '~' to the user home directory,
            # resolve it into a normalized absolute path.
            path_obj = Path(path_arg).expanduser().resolve()
            content = path_obj.read_text(encoding="utf-8", errors="replace")
        # if the file doesn't exist
        except FileNotFoundError:
            return {"output": f"File not found: {path_arg}", "returncode": 2}
        # if without permission
        except PermissionError:
            return {"output": f"Permission denied: {path_arg}", "returncode": 13}
        # if other unknown errors
        except Exception as e:
            return {"output": f"Error replacing text: {e}", "returncode": 1}

        if replace_all:
            replacements = content.count(old_text)
            new_content = content.replace(old_text, new_text)
        else:
            index = content.find(old_text)
            if index == -1:
                replacements = 0
                new_content = content
            else:
                replacements = 1
                new_content = content[:index] + new_text + content[index + len(old_text) :]

        if replacements == 0:
            return {"output": "No replacements made (text not found)", "returncode": 0}

        try:
            path_obj.write_text(new_content, encoding="utf-8", errors="replace")
        except PermissionError:
            return {"output": f"Permission denied when writing: {path_arg}", "returncode": 13}
        except Exception as e:
            return {"output": f"Error writing file: {e}", "returncode": 1}

        return {
            "output": f"Successfully replaced {replacements} occurrence(s) in {path_arg}",
            "returncode": 0,
        }

    def _execute_in_env(self, env, path_arg: str, old_text: str, new_text: str, replace_all: bool) -> dict:
        """Execute replace operation in Docker environment using Python."""
        # Validate path is within /testbed
        validate_cmd = f"realpath -- {shlex.quote(path_arg)}"
        validate_result = env.execute(validate_cmd)
        if validate_result["returncode"] != 0:
            return {"output": f"Invalid path: {path_arg}", "returncode": 2}
        normalized_path = validate_result["output"].strip()
        if not normalized_path.startswith("/testbed"):
            return {
                "output": f"Path must be within /testbed: {path_arg} (resolved to {normalized_path})",
                "returncode": 2,
            }

        # Read file using cat (same approach as read_file tool)
        read_cmd = f"cat -- {shlex.quote(path_arg)}"
        read_result = env.execute(read_cmd)
        if read_result["returncode"] != 0:
            if "No such file" in read_result["output"] or "cannot open" in read_result["output"]:
                return {"output": f"File not found: {path_arg}", "returncode": 2}
            return {"output": f"Error reading file: {read_result['output']}", "returncode": 1}

        # Get content and check for binary
        content = read_result["output"]
        if "\x00" in content:
            return {"output": "Binary file not supported", "returncode": 1}

        # Perform replacement (same logic as local mode)
        if replace_all:
            replacements = content.count(old_text)
            new_content = content.replace(old_text, new_text)
        else:
            index = content.find(old_text)
            if index == -1:
                replacements = 0
                new_content = content
            else:
                replacements = 1
                new_content = content[:index] + new_text + content[index + len(old_text) :]

        if replacements == 0:
            return {"output": "No replacements made (text not found)", "returncode": 0}

        # Write content back using base64 encoding (same approach as write_file)
        content_b64 = base64.b64encode(new_content.encode("utf-8")).decode("ascii")
        write_cmd = f"printf '%s' {shlex.quote(content_b64)} | base64 -d > {shlex.quote(path_arg)}"
        write_result = env.execute(write_cmd)

        if write_result["returncode"] != 0:
            return {"output": f"Error writing file: {write_result['output']}", "returncode": 1}

        return {
            "output": f"Successfully replaced {replacements} occurrence(s) in {path_arg}",
            "returncode": 0,
        }


# make tools registered
register(ReplaceTool())
