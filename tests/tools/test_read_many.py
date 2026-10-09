"""Tests for the read_many_files tool."""

import json
import tempfile
from pathlib import Path

import pytest

from minisweagent.tools.read_many import ReadManyFilesTool


@pytest.fixture
def sample_files(tmp_path):
    """Create sample files for testing."""
    files = {}
    
    # Create a simple text file
    simple_file = tmp_path / "simple.txt"
    simple_file.write_text("Line 1\nLine 2\nLine 3\n")
    files["simple"] = simple_file
    
    # Create a longer file
    long_file = tmp_path / "long.txt"
    content = "\n".join([f"Line {i}" for i in range(1, 151)])  # 150 lines
    long_file.write_text(content)
    files["long"] = long_file
    
    # Create a Python file
    py_file = tmp_path / "example.py"
    py_file.write_text("""# Example Python file
def hello():
    print("Hello, world!")

def goodbye():
    print("Goodbye!")

if __name__ == "__main__":
    hello()
    goodbye()
""")
    files["python"] = py_file
    
    # Create a file with empty lines
    empty_lines_file = tmp_path / "empty_lines.txt"
    empty_lines_file.write_text("Line 1\n\n\nLine 4\n\nLine 6\n")
    files["empty_lines"] = empty_lines_file
    
    # Create a binary file
    binary_file = tmp_path / "binary.bin"
    binary_file.write_bytes(b"\x00\x01\x02\x03Binary content")
    files["binary"] = binary_file
    
    return files


@pytest.fixture 
def tool():
    """Create ReadManyFilesTool instance."""
    return ReadManyFilesTool()


def test_read_multiple_files_basic(sample_files, tmp_path):
    """Test basic reading of multiple files."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    paths = [str(sample_files["simple"]), str(sample_files["python"])]
    result = tool({"paths": paths})
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    assert data["files_processed"] == 2
    assert data["files_successful"] == 2
    assert data["files_failed"] == 0
    assert len(data["results"]) == 2
    
    # Check first file
    file1 = data["results"][0]
    assert file1["status"] == "success"
    assert file1["path"] == str(sample_files["simple"])
    assert "Line 1" in file1["content"]
    assert "Line 2" in file1["content"]
    assert file1["line_count"] == 3
    
    # Check second file
    file2 = data["results"][1] 
    assert file2["status"] == "success"
    assert file2["path"] == str(sample_files["python"])
    assert "def hello():" in file2["content"]
    assert file2["line_count"] > 5


def test_max_lines_per_file(sample_files, tmp_path):
    """Test max_lines_per_file parameter."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    result = tool({
        "paths": [str(sample_files["long"])],
        "max_lines_per_file": 10
    })
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    file_result = data["results"][0]
    assert file_result["status"] == "success"
    assert file_result["line_count"] == 10
    assert file_result["truncated_for_line_limit"] == True
    assert "Line 1" in file_result["content"]
    assert "Line 10" in file_result["content"]
    assert "Line 11" not in file_result["content"]


def test_include_metadata(sample_files, tmp_path):
    """Test include_metadata parameter."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    result = tool({
        "paths": [str(sample_files["simple"])],
        "include_metadata": True
    })
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    file_result = data["results"][0]
    assert "size_bytes" in file_result
    assert "total_lines" in file_result
    assert isinstance(file_result["size_bytes"], int)
    assert isinstance(file_result["total_lines"], int)


def test_metadata_disabled(sample_files, tmp_path):
    """Test with metadata disabled."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    result = tool({
        "paths": [str(sample_files["simple"])],
        "include_metadata": False
    })
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    file_result = data["results"][0]
    assert "size_bytes" not in file_result
    assert "total_lines" not in file_result


def test_strip_empty_lines(sample_files, tmp_path):
    """Test strip_empty_lines parameter."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    # First without stripping
    result1 = tool({
        "paths": [str(sample_files["empty_lines"])],
        "strip_empty_lines": False
    })
    
    data1 = json.loads(result1["output"])
    content1 = data1["results"][0]["content"]
    assert "\n\n" in content1  # Empty lines preserved
    
    # Then with stripping
    result2 = tool({
        "paths": [str(sample_files["empty_lines"])],
        "strip_empty_lines": True
    })
    
    data2 = json.loads(result2["output"])
    content2 = data2["results"][0]["content"]
    lines2 = content2.split("\n")
    assert all(line.strip() for line in lines2 if line)  # No empty lines


def test_max_total_chars(sample_files, tmp_path):
    """Test max_total_chars limit."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    result = tool({
        "paths": [str(sample_files["long"]), str(sample_files["python"])],
        "max_total_chars": 100  # Very small limit
    })
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    assert data["total_characters"] <= 100
    # At least one file should be processed
    assert data["files_successful"] >= 1


def test_binary_file_rejection(sample_files, tmp_path):
    """Test that binary files are rejected."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    result = tool({"paths": [str(sample_files["binary"])]})
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    file_result = data["results"][0]
    assert file_result["status"] == "error"
    assert "Binary file detected" in file_result["error"]


def test_file_not_found(tmp_path):
    """Test handling of non-existent files."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    result = tool({"paths": ["/nonexistent/file.txt"]})
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    assert data["files_failed"] == 1
    file_result = data["results"][0]
    assert file_result["status"] == "error"
    assert "File not found" in file_result["error"]


def test_mixed_success_failure(sample_files, tmp_path):
    """Test mixed successful and failed file reads."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    paths = [
        str(sample_files["simple"]),  # Should succeed
        "/nonexistent.txt",           # Should fail
        str(sample_files["binary"]),  # Should fail (binary)
        str(sample_files["python"])   # Should succeed
    ]
    
    result = tool({"paths": paths})
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    assert data["files_processed"] == 4
    assert data["files_successful"] == 2
    assert data["files_failed"] == 2
    assert data["files_skipped"] == 0


def test_empty_paths():
    """Test error when paths is empty."""
    tool = ReadManyFilesTool()
    
    result = tool({"paths": []})
    
    assert result["returncode"] == 2
    assert "Missing 'paths'" in result["output"]


def test_missing_paths():
    """Test error when paths parameter is missing."""
    tool = ReadManyFilesTool()
    
    result = tool({})
    
    assert result["returncode"] == 2
    assert "Missing 'paths'" in result["output"]


def test_invalid_paths_type():
    """Test error when paths is not a list."""
    tool = ReadManyFilesTool()
    
    result = tool({"paths": "not_a_list"})
    
    assert result["returncode"] == 2
    assert "'paths' must be a list" in result["output"]


def test_too_many_files():
    """Test error when too many files are requested."""
    tool = ReadManyFilesTool()
    
    # Create 21 file paths (exceeds limit of 20)
    paths = [f"/file_{i}.txt" for i in range(21)]
    
    result = tool({"paths": paths})
    
    assert result["returncode"] == 2
    assert "Too many files" in result["output"]


def test_default_parameters(sample_files, tmp_path):
    """Test tool with default parameters."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    result = tool({"paths": [str(sample_files["simple"])]})
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    file_result = data["results"][0]
    assert file_result["status"] == "success"
    # Should include metadata by default
    assert "size_bytes" in file_result
    assert "total_lines" in file_result


def test_large_file_truncation(tmp_path):
    """Test truncation of large files."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    # Create a file with many lines
    large_file = tmp_path / "large.txt"
    content = "\n".join([f"This is line {i} with some content" for i in range(1, 201)])
    large_file.write_text(content)
    
    result = tool({
        "paths": [str(large_file)],
        "max_lines_per_file": 50,
        "max_total_chars": 500  # Small char limit to test truncation
    })
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    file_result = data["results"][0] 
    assert file_result["status"] == "success"
    assert data["total_characters"] <= 500
    # Should be truncated due to either line limit or char limit
    assert file_result["truncated_for_line_limit"] or file_result["truncated_for_char_limit"]


def test_directory_instead_of_file(tmp_path):
    """Test handling when a directory path is provided."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    # Create a directory
    test_dir = tmp_path / "test_directory"
    test_dir.mkdir()
    
    result = tool({"paths": [str(test_dir)]})
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    file_result = data["results"][0]
    assert file_result["status"] == "error"
    assert "Not a regular file" in file_result["error"]


def test_permission_denied_simulation(tmp_path, monkeypatch):
    """Test permission denied handling."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    # Create a file
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")
    
    # Mock Path.read_text to raise PermissionError
    def mock_read_text(*args, **kwargs):
        raise PermissionError("Access denied")
    
    monkeypatch.setattr(Path, "read_text", mock_read_text)
    
    result = tool({"paths": [str(test_file)]})
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    file_result = data["results"][0]
    assert file_result["status"] == "error"
    assert "Permission denied" in file_result["error"]


def test_unicode_decode_error_simulation(tmp_path, monkeypatch):
    """Test Unicode decode error handling."""
    tool = ReadManyFilesTool(repo_root=tmp_path)
    
    # Create a file
    test_file = tmp_path / "test.txt"
    test_file.write_text("test content")
    
    # Mock Path.read_text to raise UnicodeDecodeError
    def mock_read_text(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"", 0, 1, "Invalid start byte")
    
    monkeypatch.setattr(Path, "read_text", mock_read_text)
    
    result = tool({"paths": [str(test_file)]})
    
    assert result["returncode"] == 0
    data = json.loads(result["output"])
    
    file_result = data["results"][0]
    assert file_result["status"] == "error"
    assert "Unable to decode as UTF-8" in file_result["error"]