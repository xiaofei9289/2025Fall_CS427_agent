from pathlib import Path

import pytest


def test_register_and_use_replace(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    assert "replace" in REGISTRY

    replace = REGISTRY["replace"]

    target = tmp_path / "example.txt"
    target.write_text("hello world\nhello python\n")

    result = replace({"path": str(target), "old_text": "hello", "new_text": "hi", "replace_all": True})
    assert result["returncode"] == 0
    assert "Successfully replaced 2 occurrence(s)" in result["output"]
    assert target.read_text(encoding="utf-8") == "hi world\nhi python\n"


def test_replace_single_occurrence(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    target = tmp_path / "example.txt"
    target.write_text("hello world\nhello python\n")

    result = replace({"path": str(target), "old_text": "hello", "new_text": "hi", "replace_all": False})
    assert result["returncode"] == 0
    assert "Successfully replaced 1 occurrence(s)" in result["output"]
    assert target.read_text(encoding="utf-8") == "hi world\nhello python\n"


def test_replace_nonexistent_file():
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    result = replace({"path": "/nonexistent/file.txt", "old_text": "hello", "new_text": "world"})
    assert result["returncode"] != 0
    assert "not found" in result["output"].lower()


def test_replace_text_not_found(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    target = tmp_path / "example.txt"
    target.write_text("hello world\n")

    result = replace({"path": str(target), "old_text": "notfound", "new_text": "replacement"})
    assert result["returncode"] == 0
    assert "No replacements made" in result["output"]
    assert target.read_text(encoding="utf-8") == "hello world\n"


def test_replace_empty_file(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    target = tmp_path / "empty.txt"
    target.write_text("")

    result = replace({"path": str(target), "old_text": "hello", "new_text": "world"})
    assert result["returncode"] == 0
    assert "No replacements made" in result["output"]


def test_replace_missing_path():
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    result = replace({"old_text": "hello", "new_text": "world"})
    assert result["returncode"] == 2
    assert "missing path" in result["output"].lower()


def test_replace_empty_old_text(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    target = tmp_path / "example.txt"
    target.write_text("hello world\n")

    result = replace({"path": str(target), "old_text": "", "new_text": "world"})
    assert result["returncode"] == 2
    assert "old_text empty" in result["output"].lower()


def test_replace_special_characters(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    target = tmp_path / "example.txt"
    target.write_text("price: $10.00\n")

    result = replace({"path": str(target), "old_text": "$10.00", "new_text": "$20.00", "replace_all": True})
    assert result["returncode"] == 0
    assert target.read_text(encoding="utf-8") == "price: $20.00\n"


def test_replace_multiline_text(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    target = tmp_path / "example.txt"
    target.write_text("line1\nline2\nline3\n")

    result = replace({"path": str(target), "old_text": "line1\nline2", "new_text": "new1\nnew2", "replace_all": True})
    assert result["returncode"] == 0
    assert target.read_text(encoding="utf-8") == "new1\nnew2\nline3\n"


def test_replace_with_newlines(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    target = tmp_path / "example.txt"
    target.write_text("hello\nworld\n")

    result = replace({"path": str(target), "old_text": "\n", "new_text": " ", "replace_all": True})
    assert result["returncode"] == 0
    assert target.read_text(encoding="utf-8") == "hello world "


def test_replace_default_replace_all(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    target = tmp_path / "example.txt"
    target.write_text("hello hello hello\n")

    result = replace({"path": str(target), "old_text": "hello", "new_text": "hi"})
    assert result["returncode"] == 0
    assert "Successfully replaced 3 occurrence(s)" in result["output"]
    assert target.read_text(encoding="utf-8") == "hi hi hi\n"


def test_replace_unicode_characters(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    target = tmp_path / "example.txt"
    target.write_text("Hello 世界\n")

    result = replace({"path": str(target), "old_text": "世界", "new_text": "world", "replace_all": True})
    assert result["returncode"] == 0
    assert target.read_text(encoding="utf-8") == "Hello world\n"


def test_replace_backslash_characters(tmp_path):
    from minisweagent.tools import REGISTRY
    import minisweagent.tools.replace  # noqa: F401

    replace = REGISTRY["replace"]
    target = tmp_path / "example.txt"
    target.write_text("path: C:\\Users\\test\n")

    result = replace({"path": str(target), "old_text": "C:\\Users", "new_text": "C:\\Users\\Documents", "replace_all": True})
    assert result["returncode"] == 0
    assert "C:\\Users\\Documents" in target.read_text(encoding="utf-8")

