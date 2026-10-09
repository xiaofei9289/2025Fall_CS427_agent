"""Tests for the refined read_file tool."""

import json
from pathlib import Path

import pytest

from minisweagent.tools.read import RefinedReadFile


@pytest.fixture
def sample_file(tmp_path):
    """Create a sample file with known content."""
    content = "\n".join([f"Line {i}" for i in range(1, 11)])  # Lines 1-10
    file_path = tmp_path / "sample.txt"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def python_file(tmp_path):
    """Create a Python file with comments."""
    content = """# This is a comment
def hello():
    # Another comment
    print("world")  # inline comment
    return True
"""
    file_path = tmp_path / "sample.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def binary_file(tmp_path):
    """Create a binary file."""
    file_path = tmp_path / "binary.bin"
    file_path.write_bytes(b"\x00\x01\x02\x03")
    return file_path


def test_read_entire_file(sample_file, tmp_path):
    """Test reading entire file without selector."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(sample_file)})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    assert output["path"] == str(sample_file)
    assert output["encoding"] == "utf-8"
    assert output["start_line"] == 1
    assert output["line_count"] == 10
    assert output["truncated"] is False
    assert "Line 1" in output["content"]
    assert "Line 10" in output["content"]


def test_read_lines_selector(sample_file, tmp_path):
    """Test reading specific line numbers."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(sample_file), "selector": {"lines": [2, 5, 8]}})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    assert output["line_count"] == 3
    assert "Line 2" in output["content"]
    assert "Line 5" in output["content"]
    assert "Line 8" in output["content"]
    assert "Line 1" not in output["content"]


def test_read_range_selector(sample_file, tmp_path):
    """Test reading a line range."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(sample_file), "selector": {"range": {"start": 3, "end": 6}}})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    assert output["start_line"] == 3
    assert output["line_count"] == 4  # Lines 3, 4, 5, 6
    assert "Line 3" in output["content"]
    assert "Line 6" in output["content"]
    assert "Line 2" not in output["content"]
    assert "Line 7" not in output["content"]


def test_read_head_selector(sample_file, tmp_path):
    """Test reading first N lines."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(sample_file), "selector": {"head": 3}})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    assert output["start_line"] == 1
    assert output["line_count"] == 3
    assert "Line 1" in output["content"]
    assert "Line 3" in output["content"]
    assert "Line 4" not in output["content"]


def test_read_tail_selector(sample_file, tmp_path):
    """Test reading last N lines."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(sample_file), "selector": {"tail": 3}})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    assert output["start_line"] == 8  # Lines 8, 9, 10
    assert output["line_count"] == 3
    assert "Line 8" in output["content"]
    assert "Line 10" in output["content"]
    assert "Line 7" not in output["content"]


def test_read_around_selector(sample_file, tmp_path):
    """Test reading window around a line."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(sample_file), "selector": {"around": {"line": 5, "radius": 2}}})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    assert output["start_line"] == 3  # 5 - 2
    assert output["line_count"] == 5  # Lines 3, 4, 5, 6, 7
    assert "Line 3" in output["content"]
    assert "Line 7" in output["content"]
    assert "Line 2" not in output["content"]
    assert "Line 8" not in output["content"]


def test_max_chars_truncation(sample_file, tmp_path):
    """Test max_chars truncation."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(sample_file), "max_chars": 20})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    assert output["truncated"] is True
    assert len(output["content"]) == 20


def test_strip_comments_python(python_file, tmp_path):
    """Test comment stripping for Python files."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(python_file), "strip_comments": True})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    content = output["content"]
    assert "# This is a comment" not in content
    assert "# Another comment" not in content
    assert "def hello():" in content
    assert 'print("world")' in content


def test_binary_file_rejection(binary_file, tmp_path):
    """Test that binary files are rejected."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(binary_file)})
    
    assert result["returncode"] == 1
    assert "Binary file rejected" in result["output"]


def test_path_traversal_denied(tmp_path):
    """Test that path traversal is denied."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": "../../../etc/passwd"})
    
    assert result["returncode"] == 1
    assert "Path traversal denied" in result["output"]


def test_file_not_found(tmp_path):
    """Test handling of non-existent file."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(tmp_path / "nonexistent.txt")})
    
    assert result["returncode"] == 2
    assert "File not found" in result["output"]


def test_missing_path():
    """Test error when path is missing."""
    tool = RefinedReadFile()
    result = tool({})
    
    assert result["returncode"] == 2
    assert "Missing 'path'" in result["output"]


def test_multiple_selectors_error(sample_file, tmp_path):
    """Test that providing multiple selectors raises an error."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({
        "path": str(sample_file),
        "selector": {"head": 5, "tail": 5}
    })
    
    assert result["returncode"] == 22
    assert "exactly one selector" in result["output"]


def test_out_of_bounds_lines_clamped(sample_file, tmp_path):
    """Test that out-of-bounds line requests are clamped."""
    tool = RefinedReadFile(repo_root=tmp_path)
    
    # Request lines beyond file length
    result = tool({"path": str(sample_file), "selector": {"lines": [1, 5, 100, 200]}})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    # Should only get lines 1 and 5 (100 and 200 are beyond file length)
    assert output["line_count"] == 2


def test_range_clamping(sample_file, tmp_path):
    """Test that range is clamped to file bounds."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(sample_file), "selector": {"range": {"start": 8, "end": 100}}})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    assert output["start_line"] == 8
    assert output["line_count"] == 3  # Lines 8, 9, 10


def test_empty_tail(sample_file, tmp_path):
    """Test tail with 0 lines."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(sample_file), "selector": {"tail": 0}})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    assert output["line_count"] == 0
    assert output["content"] == ""


def test_crlf_normalization(tmp_path):
    """Test that CRLF line endings are normalized to LF."""
    file_path = tmp_path / "crlf.txt"
    file_path.write_bytes(b"Line 1\r\nLine 2\r\nLine 3\r\n")
    
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(file_path)})
    
    assert result["returncode"] == 0
    output = json.loads(result["output"])
    # Should have LF, not CRLF
    assert "\r\n" not in output["content"]
    assert "Line 1\n" in output["content"]


def test_invalid_range_start_greater_than_end(sample_file, tmp_path):
    """Test error when range start > end."""
    tool = RefinedReadFile(repo_root=tmp_path)
    result = tool({"path": str(sample_file), "selector": {"range": {"start": 10, "end": 5}}})
    
    assert result["returncode"] == 22
    assert "start cannot exceed end" in result["output"]
