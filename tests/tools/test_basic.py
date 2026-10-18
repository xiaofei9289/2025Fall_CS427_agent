import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def test_register_and_use_read_write_file(tmp_path):
    # Import registers tools into REGISTRY
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    assert "read_file" in REGISTRY
    assert "write_file" in REGISTRY

    write = REGISTRY["write_file"]
    read = REGISTRY["read_file"]

    target = tmp_path / "example.txt"
    content = "hello world"

    # Write
    res_w = write({"path": str(target), "content": content})
    assert res_w["returncode"] == 0
    assert target.exists()
    assert target.read_text(encoding="utf-8") == content

    # Read
    res_r = read({"path": str(target)})
    assert res_r["returncode"] == 0
    assert res_r["output"] == content


def test_read_nonexistent(tmp_path):
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    read = REGISTRY["read_file"]
    res = read({"path": str(tmp_path / "nope.txt")})
    assert res["returncode"] != 0
    assert "not found" in res["output"].lower()


def test_write_new_file(tmp_path):
    """Test writing a new file."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    write = REGISTRY["write_file"]
    target = tmp_path / "new_file.txt"
    content = "This is new content"

    result = write({"path": str(target), "content": content})
    assert result["returncode"] == 0
    assert target.exists()
    assert target.read_text(encoding="utf-8") == content
    assert "wrote" in result["output"]
    assert str(target.resolve()) in result["output"]


def test_write_overwrite_existing_file(tmp_path):
    """Test overwriting an existing file."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    write = REGISTRY["write_file"]
    target = tmp_path / "existing.txt"
    
    # Create initial file
    target.write_text("old content", encoding="utf-8")
    assert target.read_text(encoding="utf-8") == "old content"

    # Overwrite with new content
    new_content = "new content"
    result = write({"path": str(target), "content": new_content})
    assert result["returncode"] == 0
    assert target.read_text(encoding="utf-8") == new_content


def test_write_creates_parent_directories(tmp_path):
    """Test that write_file creates parent directories as needed."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    write = REGISTRY["write_file"]
    target = tmp_path / "nested" / "deep" / "file.txt"
    content = "content in nested path"

    result = write({"path": str(target), "content": content})
    assert result["returncode"] == 0
    assert target.exists()
    assert target.read_text(encoding="utf-8") == content
    assert target.parent.exists()
    assert (tmp_path / "nested" / "deep").exists()


def test_write_missing_path(tmp_path):
    """Test write_file with missing path parameter."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    write = REGISTRY["write_file"]
    result = write({"content": "some content"})
    assert result["returncode"] == 2
    assert "Missing 'path'" in result["output"]


def test_write_special_characters(tmp_path):
    """Test writing content with special characters and newlines."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    write = REGISTRY["write_file"]
    target = tmp_path / "special.txt"
    content = "Line 1\nLine 2\n\tIndented\nSpecial: !@#$%^&*()"

    result = write({"path": str(target), "content": content})
    assert result["returncode"] == 0
    assert target.read_text(encoding="utf-8") == content


def test_write_unicode_content(tmp_path):
    """Test writing Unicode content."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    write = REGISTRY["write_file"]
    target = tmp_path / "unicode.txt"
    content = "Hello 世界 🌍 こんにちは"

    result = write({"path": str(target), "content": content})
    assert result["returncode"] == 0
    assert target.read_text(encoding="utf-8") == content


def test_write_empty_content(tmp_path):
    """Test writing empty content."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    write = REGISTRY["write_file"]
    target = tmp_path / "empty.txt"

    result = write({"path": str(target), "content": ""})
    assert result["returncode"] == 0
    assert target.exists()
    assert target.read_text(encoding="utf-8") == ""


def test_write_with_environment(tmp_path):
    """Test write_file with environment (Docker mode)."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    write = REGISTRY["write_file"]
    mock_env = MagicMock()
    mock_env.config.cwd = "/testbed"

    # Mock path resolution, successful directory creation and file write
    mock_env.execute.side_effect = [
        {"output": "/testbed/nested/file.txt", "returncode": 0},  # realpath
        {"output": "", "returncode": 0},  # mkdir success
        {"output": "", "returncode": 0},   # write success
    ]

    result = write({"path": "/testbed/nested/file.txt", "content": "test content"}, env=mock_env)
    assert result["returncode"] == 0
    assert "wrote" in result["output"]
    assert mock_env.execute.call_count == 3


def test_write_with_environment_mkdir_failure(tmp_path):
    """Test write_file with environment when mkdir fails."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    write = REGISTRY["write_file"]
    mock_env = MagicMock()
    mock_env.config.cwd = "/testbed"
    mock_env.execute.side_effect = [
        {"output": "/testbed/nested/file.txt", "returncode": 0},  # realpath
        {"output": "Permission denied", "returncode": 1},  # mkdir fails
    ]

    result = write({"path": "/testbed/nested/file.txt", "content": "test"}, env=mock_env)
    assert result["returncode"] == 1
    assert "Failed to create directories" in result["output"]


def test_write_bytes_count(tmp_path):
    """Test that write_file reports correct byte count."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    write = REGISTRY["write_file"]
    target = tmp_path / "bytes.txt"
    content = "hello world"  # 11 bytes

    result = write({"path": str(target), "content": content})
    assert result["returncode"] == 0
    assert "11 bytes" in result["output"]


class ShellEnv:
    """A minimal environment running commands through the real shell."""

    config = SimpleNamespace(cwd="/testbed")

    def execute(self, command):
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return {"output": result.stdout + result.stderr, "returncode": result.returncode}


def test_write_rejects_paths_outside_workspace(tmp_path):
    """Tool writes must stay inside the environment workspace (/testbed)."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    result = REGISTRY["write_file"](
        {"path": str(tmp_path / "outside-testbed.txt"), "content": "outside"}, ShellEnv()
    )
    assert result["returncode"] != 0
    assert "must be within" in result["output"]
    assert not (tmp_path / "outside-testbed.txt").exists()


def test_write_rejects_testbed_prefix_lookalikes(tmp_path):
    """A /testbed-other style prefix must not pass the workspace boundary check."""
    import minisweagent.tools.basic  # noqa: F401
    from minisweagent.tools import REGISTRY

    result = REGISTRY["write_file"](
        {"path": "/testbed-other/escape.txt", "content": "x"}, ShellEnv()
    )
    assert result["returncode"] != 0
    assert "must be within" in result["output"]

