"""A tool for managing a TODO list in a simple text file.

This tool allows the agent to add items to, remove items from, and display
a TODO list stored in a `TODO.md` file. The agent should only use this
tool when explicitly asked by the user. As per project guidelines, this
tool operates on the local filesystem, not within the SWE-bench Docker container.

Example user prompts:
- "add 'Refactor the authentication module' to my todo list"
- "show me my todo list"
- "remove task 2 from my todo list"
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import register

TODO_FILE = "TODO.md"


@dataclass
class TodoTool:
    name: str = "todo"
    description: str = (
        "Manages a local TODO list. Actions: 'add' a task, 'list' all tasks, "
        "'remove' a task by its number."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to perform: 'add', 'list', or 'remove'",
                },
                "task": {
                    "type": "string",
                    "description": "The content of the task to add. Required for 'add' action.",
                },
                "task_number": {
                    "type": "integer",
                    "description": "The number of the task to remove. Required for 'remove' action.",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env=None) -> dict:
        # This tool intentionally ignores the `env` parameter and always
        # operates on the local filesystem, as it manages the agent's
        # internal state, not the code in the sandbox.
        action = args.get("action")
        task = args.get("task")
        task_number = args.get("task_number")

        try:
            if action == "add":
                if not task:
                    return {"output": "Error: 'task' is required for the 'add' action.", "returncode": 1}
                with open(TODO_FILE, "a") as f:
                    f.write(f"- [ ] {task}\n")
                return {"output": f"Added '{task}' to the TODO list.", "returncode": 0}

            elif action == "list":
                if not os.path.exists(TODO_FILE):
                    return {"output": "TODO list is empty.", "returncode": 0}
                with open(TODO_FILE, "r") as f:
                    content = f.read()
                if not content.strip():
                    return {"output": "TODO list is empty.", "returncode": 0}
                return {"output": content, "returncode": 0}

            elif action == "remove":
                if task_number is None:
                    return {"output": "Error: 'task_number' is required for the 'remove' action.", "returncode": 1}
                
                if not os.path.exists(TODO_FILE):
                    return {"output": "Error: TODO list is empty, cannot remove.", "returncode": 1}

                with open(TODO_FILE, "r") as f:
                    lines = f.readlines()

                if not (1 <= task_number <= len(lines)):
                    return {"output": f"Error: Invalid task number. Must be between 1 and {len(lines)}.", "returncode": 1}

                removed_task = lines.pop(task_number - 1).strip()

                with open(TODO_FILE, "w") as f:
                    f.writelines(lines)
                
                return {"output": f"Removed task {task_number}: '{removed_task}'", "returncode": 0}

            else:
                return {"output": f"Error: Unknown action '{action}'. Valid actions are 'add', 'list', 'remove'.", "returncode": 1}

        except Exception as e:
            return {"output": f"An unexpected error occurred: {e}", "returncode": 1}


# Register the tool
register(TodoTool())
