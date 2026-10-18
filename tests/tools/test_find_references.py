import sys
from pathlib import Path

import pytest

from minisweagent.environments.local import LocalEnvironment
from minisweagent.retrieval.relations import find_references, format_references
from minisweagent.retrieval.repository import RepositoryIndex
from minisweagent.tools.find_references import FindReferencesTool


def write_repo(root: Path) -> None:
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "src" / "auth.py").write_text(
        '''class Session:
    def refresh_token(self, token):
        return token


class AdminSession(Session):
    pass


def login(user):
    return Session().refresh_token(user)
'''
    )
    (root / "tests" / "test_auth.py").write_text(
        "from src.auth import Session, login\n\ndef test_refresh():\n    return login('x')\n"
    )


def env_for(root: Path) -> LocalEnvironment:
    return LocalEnvironment(
        cwd=str(root),
        env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"},
    )


def test_find_references_returns_definitions_and_callers(tmp_path: Path) -> None:
    write_repo(tmp_path)
    index = RepositoryIndex(tmp_path)
    result = find_references(index, "refresh_token")
    assert result["definitions"][0]["name"] == "Session.refresh_token"
    locations = {(entry["path"], entry["line"], entry["kind"]) for entry in result["references"]}
    assert ("src/auth.py", 11, "call") in locations
    assert ("src/auth.py", 11, "attribute") not in locations  # collapsed into the call entry
    text = format_references(index, result, context_lines=1)
    assert "src/auth.py:2" in text
    assert "refresh_token" in text
    assert "call" in text


def test_find_references_finds_imports_and_class_bases(tmp_path: Path) -> None:
    write_repo(tmp_path)
    index = RepositoryIndex(tmp_path)
    login_refs = find_references(index, "login")
    assert any(entry["kind"] == "import" and entry["path"] == "tests/test_auth.py" for entry in login_refs["references"])
    assert any(entry["kind"] == "call" and entry["path"] == "tests/test_auth.py" for entry in login_refs["references"])
    session_refs = find_references(index, "Session")
    assert any(entry["kind"] == "base" and entry["owner"] == "AdminSession" for entry in session_refs["references"])


def test_find_references_can_restrict_to_one_file(tmp_path: Path) -> None:
    write_repo(tmp_path)
    index = RepositoryIndex(tmp_path)
    result = find_references(index, "Session", path_filter="src/auth.py")
    assert all(entry["path"] == "src/auth.py" for entry in result["references"])
    assert result["files_scanned"] == 1


def test_find_references_tool_in_environment(tmp_path: Path) -> None:
    write_repo(tmp_path)
    tool = FindReferencesTool()
    result = tool({"symbol": "refresh_token", "path": ".", "context_lines": 1}, env_for(tmp_path))
    assert result["returncode"] == 0
    assert "Definitions for 'Session.refresh_token'" in result["output"]
    assert "src/auth.py:11" in result["output"]
    assert "src/auth.py:2" in result["output"]


def test_find_references_missing_symbol_is_not_an_error(tmp_path: Path) -> None:
    write_repo(tmp_path)
    result = FindReferencesTool()({"symbol": "does_not_exist", "path": str(tmp_path)}, env=None)
    assert result["returncode"] == 0
    assert "Definitions: none" in result["output"]


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"symbol": ""},
        {"symbol": "x", "context_lines": -1},
        {"symbol": "x", "limit": 0},
        {"symbol": "x", "limit": 101},
    ],
)
def test_find_references_invalid_parameters(args: dict) -> None:
    assert FindReferencesTool()(args)["returncode"] == 2
