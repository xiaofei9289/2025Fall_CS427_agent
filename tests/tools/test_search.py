"""Unit tests for search_file_content tool."""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def test_search_tool_registered():
    """Test that search tool is properly registered."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    assert "search_file_content" in REGISTRY
    tool = REGISTRY["search_file_content"]
    assert tool.name == "search_file_content"
    assert "search" in tool.description.lower()


def test_basic_literal_search(tmp_path):
    """Test basic literal text search."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    # Create test file
    test_file = tmp_path / "test.txt"
    test_file.write_text(
        "Line 1: First line\n"
        "Line 2: Contains pattern here\n"
        "Line 3: Middle line\n"
        "Line 4: Another pattern match\n"
        "Line 5: Last line\n"
    )

    search = REGISTRY["search_file_content"]
    result = search({"path": str(test_file), "pattern": "pattern"})

    assert result["returncode"] == 0
    assert "2 match(es)" in result["output"]
    assert "Line 2: Contains pattern here" in result["output"]
    assert "Line 4: Another pattern match" in result["output"]
    # Check line numbers are shown
    assert "2:>" in result["output"]
    assert "4:>" in result["output"]


def test_case_insensitive_search(tmp_path):
    """Test case-insensitive search."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    test_file.write_text(
        "Line 1: ERROR message\n"
        "Line 2: Normal line\n"
        "Line 3: error in lowercase\n"
        "Line 4: ErRoR in mixed case\n"
    )

    search = REGISTRY["search_file_content"]
    result = search({
        "path": str(test_file),
        "pattern": "error",
        "case_sensitive": False,
    })

    assert result["returncode"] == 0
    assert "3 match(es)" in result["output"]
    assert "ERROR message" in result["output"]
    assert "error in lowercase" in result["output"]
    assert "ErRoR in mixed case" in result["output"]


def test_case_sensitive_search_default(tmp_path):
    """Test that search is case-sensitive by default."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    test_file.write_text(
        "Line 1: ERROR message\n"
        "Line 2: Normal line\n"
        "Line 3: Another line\n"
        "Line 4: error in lowercase\n"
        "Line 5: More content\n"
    )

    search = REGISTRY["search_file_content"]
    result = search({"path": str(test_file), "pattern": "error", "context_lines": 0})

    assert result["returncode"] == 0
    assert "1 match(es)" in result["output"]
    assert "error in lowercase" in result["output"]
    # Should only match lowercase, not uppercase
    assert "4:> Line 4: error in lowercase" in result["output"]
    # With context_lines=0, ERROR message line shouldn't be in output
    assert "ERROR message" not in result["output"]


def test_regex_search(tmp_path):
    """Test regex pattern matching."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    test_file.write_text(
        "Line 1: def function_one():\n"
        "Line 2: some code\n"
        "Line 3: some more code\n"
        "Line 4: def function_two():\n"
        "Line 5: more code\n"
        "Line 6: even more code\n"
        "Line 7: class MyClass:\n"
    )

    search = REGISTRY["search_file_content"]
    result = search({
        "path": str(test_file),
        "pattern": r"def \w+\(",
        "use_regex": True,
        "context_lines": 1,  # Limit context so MyClass line is not included
    })

    assert result["returncode"] == 0
    assert "2 match(es)" in result["output"]
    assert "function_one" in result["output"]
    assert "function_two" in result["output"]
    # MyClass is too far from the matches to be in context
    assert "MyClass" not in result["output"]


def test_invalid_regex(tmp_path):
    """Test that invalid regex returns error."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    test_file.write_text("some content")

    search = REGISTRY["search_file_content"]
    result = search({
        "path": str(test_file),
        "pattern": "[invalid(regex",
        "use_regex": True,
    })

    assert result["returncode"] == 2
    assert "Invalid regex" in result["output"]


def test_context_lines(tmp_path):
    """Test configurable context lines."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    test_file.write_text(
        "Line 1\n"
        "Line 2\n"
        "Line 3\n"
        "Line 4: MATCH\n"
        "Line 5\n"
        "Line 6\n"
        "Line 7\n"
    )

    search = REGISTRY["search_file_content"]

    # Test with 1 context line
    result = search({
        "path": str(test_file),
        "pattern": "MATCH",
        "context_lines": 1,
    })

    assert result["returncode"] == 0
    assert "Line 3" in result["output"]
    assert "Line 4: MATCH" in result["output"]
    assert "Line 5" in result["output"]
    assert "Line 2" not in result["output"]
    assert "Line 6" not in result["output"]


def test_no_context_lines(tmp_path):
    """Test search with zero context lines."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    test_file.write_text(
        "Line 1\n"
        "Line 2: MATCH\n"
        "Line 3\n"
    )

    search = REGISTRY["search_file_content"]
    result = search({
        "path": str(test_file),
        "pattern": "MATCH",
        "context_lines": 0,
    })

    assert result["returncode"] == 0
    assert "Line 2: MATCH" in result["output"]
    assert "Line 1" not in result["output"]
    assert "Line 3" not in result["output"]


def test_no_matches_found(tmp_path):
    """Test when pattern is not found in file."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    test_file.write_text("Some content without the pattern")

    search = REGISTRY["search_file_content"]
    result = search({"path": str(test_file), "pattern": "nonexistent"})

    assert result["returncode"] == 0
    assert "No matches found" in result["output"]


def test_file_not_found():
    """Test error when file doesn't exist."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    search = REGISTRY["search_file_content"]
    result = search({"path": "/nonexistent/file.txt", "pattern": "test"})

    assert result["returncode"] == 2
    assert "not found" in result["output"].lower()


def test_missing_path():
    """Test error when path parameter is missing."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    search = REGISTRY["search_file_content"]
    result = search({"pattern": "test"})

    assert result["returncode"] == 2
    assert "Missing 'path'" in result["output"]


def test_missing_pattern(tmp_path):
    """Test error when pattern parameter is missing."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    test_file.write_text("content")

    search = REGISTRY["search_file_content"]
    result = search({"path": str(test_file)})

    assert result["returncode"] == 2
    assert "Missing 'pattern'" in result["output"]


def test_invalid_context_lines(tmp_path):
    """Test error with invalid context_lines parameter."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    test_file.write_text("content")

    search = REGISTRY["search_file_content"]
    result = search({
        "path": str(test_file),
        "pattern": "test",
        "context_lines": -1,
    })

    assert result["returncode"] == 2
    assert "non-negative integer" in result["output"]


def test_multiple_matches_grouping(tmp_path):
    """Test that nearby matches are grouped together."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    lines = []
    for i in range(1, 21):
        if i in [5, 7, 15]:  # Three matches
            lines.append(f"Line {i}: MATCH")
        else:
            lines.append(f"Line {i}: regular")

    test_file.write_text("\n".join(lines))

    search = REGISTRY["search_file_content"]
    result = search({
        "path": str(test_file),
        "pattern": "MATCH",
        "context_lines": 1,
    })

    assert result["returncode"] == 0
    assert "3 match(es)" in result["output"]
    # Lines 5 and 7 should be in same group (separated by less than 2*context+1)
    # Line 15 should be separate
    assert "---" in result["output"]  # Separator between groups


def test_docker_mode_path_validation():
    """Test that Docker mode validates paths are within /testbed."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    # Mock environment
    mock_env = MagicMock()

    search = REGISTRY["search_file_content"]

    # Test path outside /testbed should fail
    result = search(
        {"path": "/etc/passwd", "pattern": "root"},
        env=mock_env,
    )

    assert result["returncode"] == 1
    assert "/testbed" in result["output"]

    # Test path within /testbed should proceed (will call env.execute)
    mock_env.execute.return_value = {"output": "No matches", "returncode": 1}
    result = search(
        {"path": "/testbed/file.txt", "pattern": "test"},
        env=mock_env,
    )

    assert mock_env.execute.called


def test_docker_mode_grep_command():
    """Test that Docker mode uses correct grep command."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    mock_env = MagicMock()
    mock_env.execute.return_value = {
        "output": "5:some match here",
        "returncode": 0,
    }

    search = REGISTRY["search_file_content"]
    result = search(
        {
            "path": "/testbed/test.txt",
            "pattern": "test",
            "context_lines": 2,
        },
        env=mock_env,
    )

    # Verify grep was called with correct flags
    call_args = mock_env.execute.call_args[0][0]
    assert "grep" in call_args
    assert "-F" in call_args  # Fixed string (literal)
    assert "-n" in call_args  # Line numbers
    assert "-C 2" in call_args  # Context lines
    assert "test" in call_args


def test_docker_mode_regex_grep():
    """Test that Docker mode uses -E flag for regex."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    mock_env = MagicMock()
    mock_env.execute.return_value = {"output": "", "returncode": 1}

    search = REGISTRY["search_file_content"]
    search(
        {
            "path": "/testbed/test.txt",
            "pattern": "test.*pattern",
            "use_regex": True,
        },
        env=mock_env,
    )

    call_args = mock_env.execute.call_args[0][0]
    assert "-E" in call_args  # Extended regex


def test_empty_file(tmp_path):
    """Test search on empty file."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "empty.txt"
    test_file.write_text("")

    search = REGISTRY["search_file_content"]
    result = search({"path": str(test_file), "pattern": "anything"})

    assert result["returncode"] == 0
    assert "No matches found" in result["output"]


def test_special_characters_literal_search(tmp_path):
    """Test that special regex chars are escaped in literal search."""
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.search  # noqa: F401

    test_file = tmp_path / "test.txt"
    test_file.write_text(
        "Line 1: function()\n"
        "Line 2: other stuff\n"
        "Line 3: array[0]\n"
    )

    search = REGISTRY["search_file_content"]

    # Search for literal "function()" - parentheses should be escaped
    result = search({
        "path": str(test_file),
        "pattern": "function()",
        "use_regex": False,
    })

    assert result["returncode"] == 0
    assert "1 match(es)" in result["output"]
    assert "function()" in result["output"]

    # Search for literal "array[0]" - brackets should be escaped
    result = search({
        "path": str(test_file),
        "pattern": "array[0]",
        "use_regex": False,
    })

    assert result["returncode"] == 0
    assert "1 match(es)" in result["output"]
    assert "array[0]" in result["output"]
