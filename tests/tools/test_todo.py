"""Tests for the todo tool."""

import os
from pathlib import Path

import pytest


@pytest.fixture
def todo_tool(tmp_path, monkeypatch):
    """Create a todo tool instance with a temporary TODO file."""
    # Change to tmp directory so TODO.md is created there
    monkeypatch.chdir(tmp_path)

    # Import and register the tool
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.todo  # noqa: F401

    tool = REGISTRY["todo"]

    yield tool

    # Cleanup: remove TODO.md if it exists
    todo_file = tmp_path / "TODO.md"
    if todo_file.exists():
        todo_file.unlink()


def test_add_task(todo_tool, tmp_path):
    """Test adding a task to the TODO list."""
    result = todo_tool({"action": "add", "task": "Write unit tests"})

    assert result["returncode"] == 0
    assert "Added 'Write unit tests' to the TODO list" in result["output"]

    # Verify file was created and contains the task
    todo_file = tmp_path / "TODO.md"
    assert todo_file.exists()
    content = todo_file.read_text()
    assert "- [ ] Write unit tests" in content


def test_add_multiple_tasks(todo_tool, tmp_path):
    """Test adding multiple tasks to the TODO list."""
    tasks = ["Task 1", "Task 2", "Task 3"]

    for task in tasks:
        result = todo_tool({"action": "add", "task": task})
        assert result["returncode"] == 0

    # Verify all tasks are in the file
    todo_file = tmp_path / "TODO.md"
    content = todo_file.read_text()

    for task in tasks:
        assert f"- [ ] {task}" in content


def test_add_task_missing_parameter(todo_tool):
    """Test error when 'task' parameter is missing for add action."""
    result = todo_tool({"action": "add"})

    assert result["returncode"] == 1
    assert "Error: 'task' is required for the 'add' action" in result["output"]


def test_list_tasks_empty(todo_tool):
    """Test listing tasks when TODO file doesn't exist yet."""
    result = todo_tool({"action": "list"})

    assert result["returncode"] == 0
    assert "TODO list is empty" in result["output"]


def test_list_tasks_empty_file(todo_tool, tmp_path):
    """Test listing tasks when TODO file exists but is empty."""
    # Create empty TODO file
    todo_file = tmp_path / "TODO.md"
    todo_file.write_text("")

    result = todo_tool({"action": "list"})

    assert result["returncode"] == 0
    assert "TODO list is empty" in result["output"]


def test_list_tasks_with_content(todo_tool):
    """Test listing tasks after adding some."""
    # Add tasks
    todo_tool({"action": "add", "task": "Task 1"})
    todo_tool({"action": "add", "task": "Task 2"})

    # List tasks
    result = todo_tool({"action": "list"})

    assert result["returncode"] == 0
    assert "- [ ] Task 1" in result["output"]
    assert "- [ ] Task 2" in result["output"]


def test_remove_task_by_number(todo_tool):
    """Test removing a task by its number."""
    # Add tasks
    todo_tool({"action": "add", "task": "Task 1"})
    todo_tool({"action": "add", "task": "Task 2"})
    todo_tool({"action": "add", "task": "Task 3"})

    # Remove task 2
    result = todo_tool({"action": "remove", "task_number": 2})

    assert result["returncode"] == 0
    assert "Removed task 2" in result["output"]
    assert "Task 2" in result["output"]

    # Verify task was removed
    list_result = todo_tool({"action": "list"})
    assert "Task 1" in list_result["output"]
    assert "Task 2" not in list_result["output"]
    assert "Task 3" in list_result["output"]


def test_remove_first_task(todo_tool):
    """Test removing the first task."""
    # Add tasks
    todo_tool({"action": "add", "task": "First"})
    todo_tool({"action": "add", "task": "Second"})

    # Remove first task
    result = todo_tool({"action": "remove", "task_number": 1})

    assert result["returncode"] == 0

    # Verify
    list_result = todo_tool({"action": "list"})
    assert "First" not in list_result["output"]
    assert "Second" in list_result["output"]


def test_remove_last_task(todo_tool):
    """Test removing the last task."""
    # Add tasks
    todo_tool({"action": "add", "task": "First"})
    todo_tool({"action": "add", "task": "Last"})

    # Remove last task
    result = todo_tool({"action": "remove", "task_number": 2})

    assert result["returncode"] == 0

    # Verify
    list_result = todo_tool({"action": "list"})
    assert "First" in list_result["output"]
    assert "Last" not in list_result["output"]


def test_remove_task_missing_parameter(todo_tool):
    """Test error when 'task_number' parameter is missing for remove action."""
    result = todo_tool({"action": "remove"})

    assert result["returncode"] == 1
    assert "Error: 'task_number' is required for the 'remove' action" in result["output"]


def test_remove_task_invalid_number_too_high(todo_tool):
    """Test error when task number is too high."""
    # Add one task
    todo_tool({"action": "add", "task": "Only task"})

    # Try to remove task 5
    result = todo_tool({"action": "remove", "task_number": 5})

    assert result["returncode"] == 1
    assert "Error: Invalid task number" in result["output"]
    assert "Must be between 1 and 1" in result["output"]


def test_remove_task_invalid_number_zero(todo_tool):
    """Test error when task number is zero."""
    # Add tasks
    todo_tool({"action": "add", "task": "Task 1"})

    # Try to remove task 0
    result = todo_tool({"action": "remove", "task_number": 0})

    assert result["returncode"] == 1
    assert "Error: Invalid task number" in result["output"]


def test_remove_task_invalid_number_negative(todo_tool):
    """Test error when task number is negative."""
    # Add tasks
    todo_tool({"action": "add", "task": "Task 1"})

    # Try to remove task -1
    result = todo_tool({"action": "remove", "task_number": -1})

    assert result["returncode"] == 1
    assert "Error: Invalid task number" in result["output"]


def test_remove_from_empty_list(todo_tool):
    """Test error when trying to remove from empty list."""
    result = todo_tool({"action": "remove", "task_number": 1})

    assert result["returncode"] == 1
    assert "Error: TODO list is empty, cannot remove" in result["output"]


def test_invalid_action(todo_tool):
    """Test error when providing an invalid action."""
    result = todo_tool({"action": "invalid_action"})

    assert result["returncode"] == 1
    assert "Error: Unknown action 'invalid_action'" in result["output"]
    assert "Valid actions are 'add', 'list', 'remove'" in result["output"]


def test_missing_action_parameter(todo_tool):
    """Test behavior when action parameter is missing."""
    result = todo_tool({})

    # The tool should handle this gracefully
    assert result["returncode"] == 1


def test_add_task_with_special_characters(todo_tool):
    """Test adding a task with special characters."""
    special_task = "Fix bug in function foo() - issue #123 @user"
    result = todo_tool({"action": "add", "task": special_task})

    assert result["returncode"] == 0

    # Verify task is stored correctly
    list_result = todo_tool({"action": "list"})
    assert special_task in list_result["output"]


def test_add_empty_task(todo_tool):
    """Test adding an empty task."""
    result = todo_tool({"action": "add", "task": ""})

    # Empty task should be rejected (implementation validates task is not empty)
    assert result["returncode"] == 1
    assert "Error" in result["output"] or "task" in result["output"].lower()


def test_sequential_operations(todo_tool):
    """Test a sequence of add, list, and remove operations."""
    # Start with empty list
    result = todo_tool({"action": "list"})
    assert "TODO list is empty" in result["output"]

    # Add three tasks
    todo_tool({"action": "add", "task": "Task A"})
    todo_tool({"action": "add", "task": "Task B"})
    todo_tool({"action": "add", "task": "Task C"})

    # List should show all three
    result = todo_tool({"action": "list"})
    assert "Task A" in result["output"]
    assert "Task B" in result["output"]
    assert "Task C" in result["output"]

    # Remove middle task
    todo_tool({"action": "remove", "task_number": 2})

    # List should show only A and C
    result = todo_tool({"action": "list"})
    assert "Task A" in result["output"]
    assert "Task B" not in result["output"]
    assert "Task C" in result["output"]

    # Remove remaining tasks
    todo_tool({"action": "remove", "task_number": 1})
    todo_tool({"action": "remove", "task_number": 1})

    # List should be empty
    result = todo_tool({"action": "list"})
    assert "TODO list is empty" in result["output"]


def test_tool_registration():
    """Test that the todo tool is properly registered."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.todo  # noqa: F401

    assert "todo" in REGISTRY
    tool = REGISTRY["todo"]
    assert tool.name == "todo"
    assert "add" in tool.description
    assert "list" in tool.description
    assert "remove" in tool.description
