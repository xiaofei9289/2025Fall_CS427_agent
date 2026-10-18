import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from minisweagent.agents.default import DefaultAgent, FormatError
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models.test_models import DeterministicModel
from minisweagent.retrieval import repository as repository_module
from minisweagent.retrieval.repository import RepositoryIndex
from minisweagent.tools.code_search import CodeSearchTool, RepoMapTool


@pytest.fixture
def repository(tmp_path):
    (tmp_path / "auth.py").write_text('''class Session:
    @staticmethod
    async def refresh_token(token: str):
        """Refresh an expired authentication token."""
        return token
''')
    (tmp_path / "parser.py").write_text("def parse_date(value):\n    return value\n")
    (tmp_path / "broken.py").write_text("def syntax_error(\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "noise.py").write_text("def refresh_token(): pass\n")
    return tmp_path


def test_ast_ranking_ranges_and_budget_with_malformed_file(repository):
    ast.parse(Path(repository_module.__file__).read_text(), feature_version=(3, 6))
    index = RepositoryIndex(repository)
    match = index.search("refresh_token expired authentication", limit=1)[0]
    assert (match["path"], match["name"], match["kind"]) == ("auth.py", "Session.refresh_token", "method")
    assert (match["start_line"], match["end_line"]) == (2, 5)
    assert "async def Session.refresh_token" in match["signature"]
    assert index.file_count == 2
    assert index.skipped == [{"path": "broken.py", "reason": "SyntaxError"}]
    assert index.search("qzxnonexistent") == []
    mapping = index.repo_map("refresh_token", max_chars=256)
    assert len(mapping) <= 256
    assert "auth.py:2-5" in mapping
    assert ".venv" not in mapping


def test_index_respects_gitignore_and_includes_new_source_files(repository):
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "add", "parser.py"], check=True)
    (repository / ".gitignore").write_text("auth.py\nbroken.py\n.venv/\n")
    (repository / "escape.py").symlink_to(repository / "auth.py")
    (repository / "new.py").write_text("def new_symbol(): pass\n")
    assert {row["path"] for row in RepositoryIndex(repository).search("parse_date")} == {"parser.py"}
    assert RepositoryIndex(repository).search("refresh_token") == []
    assert RepositoryIndex(repository).search("new_symbol")[0]["path"] == "new.py"


def test_tools_execute_index_in_the_environment_without_installed_agent_package(repository):
    env = LocalEnvironment(cwd=str(repository), env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"})
    result = CodeSearchTool()({"query": "refresh_token", "limit": 1}, env)
    assert result["returncode"] == 0
    assert json.loads(result["output"])["matches"][0]["name"] == "Session.refresh_token"
    mapping = RepoMapTool()({"query": "refresh_token", "max_chars": 256}, env)
    assert mapping["returncode"] == 0
    assert "auth.py:2-5" in mapping["output"]
    assert len(mapping["output"]) <= 256
    assert not (repository / ".mini-swe-agent").exists()


def test_agent_tool_allowlist_controls_prompt_and_dispatch(repository):
    agent = DefaultAgent(
        DeterministicModel(outputs=[]),
        LocalEnvironment(cwd=str(repository), env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"}),
        enabled_tools=["code_search"],
    )
    assert set(agent.tools) == {"code_search"}
    assert [spec["name"] for spec in agent.extra_template_vars["tool_specs"]] == ["code_search"]
    with pytest.raises(FormatError, match="code_search"):
        agent.execute_action({"kind": "bash", "action": "ls"})
    assert agent.execute_action(
        {"kind": "tool", "tool_name": "code_search", "tool_args": {"query": "refresh_token"}}
    )["returncode"] == 0
    assert agent.execute_action({"kind": "tool", "tool_name": "repo_map", "tool_args": {}})["returncode"] == 127
    assert agent.execute_action({"kind": "bash", "action": "pwd"})["returncode"] == 0
    assert DefaultAgent(
        DeterministicModel(outputs=[]), LocalEnvironment(cwd=str(repository)), enabled_tools=[]
    ).execute_action({"kind": "bash", "action": "pwd"})["returncode"] == 0
    with pytest.raises(ValueError, match="Unknown enabled tools"):
        DefaultAgent(DeterministicModel(outputs=[]), LocalEnvironment(), enabled_tools=["missing_tool"])


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (CodeSearchTool(), {"query": ""}),
        (CodeSearchTool(), {"query": "a", "limit": 0}),
        (RepoMapTool(), {"max_chars": -1}),
        (RepoMapTool(), {"query": 123}),
    ],
)
def test_invalid_parameters_fail_before_running_code(tool, args):
    assert tool(args)["returncode"] == 2
