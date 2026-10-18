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
from minisweagent.tools.code_search import CodeContextTool, CodeSearchTool, RepoMapTool


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


def test_symbol_search_excludes_module_entries(tmp_path):
    (tmp_path / "documentation.py").write_text('"""refresh_token documentation only."""\nVALUE = 1\n')
    (tmp_path / "code.py").write_text('def refresh_token():\n    """Refresh a token."""\n    return 1\n')
    index = RepositoryIndex(tmp_path)
    assert index.ranked_files("documentation", file_only=True) == ["documentation.py"]
    assert index.ranked_files("documentation", file_only=False) == []
    assert all(row["kind"] != "module" for row in index.search("refresh_token"))
    assert "<module>" not in index.repo_map("documentation", max_chars=512)


def test_empty_repo_map_uses_structural_importance(tmp_path):
    (tmp_path / "a_unused.py").write_text("def rare():\n    return 1\n")
    (tmp_path / "z_common.py").write_text("class Common:\n    pass\n\ndef use():\n    return Common()\n")
    mapping = RepositoryIndex(tmp_path).repo_map("", max_chars=2000)
    assert mapping.index("z_common.py") < mapping.index("a_unused.py")
    assert "<module>" not in mapping


def test_context_builder_keeps_specific_symbol_and_budget(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "config.py").write_text('''class ConfigLoader:
    """Load configuration from a file."""

    def load_config(self, path):
        with open(path) as handle:
            return handle.read()

    def unused(self):
        return None
''')
    (tmp_path / "tests" / "test_config.py").write_text("""from src.config import ConfigLoader

def test_empty_config():
    loader = ConfigLoader()
    return loader.load_config("empty")
""")
    index = RepositoryIndex(tmp_path)
    output = index.build_context("load configuration file", max_chars=2000, max_files=5, snippet_lines=6)
    assert len(output) <= 2000
    assert "ConfigLoader.load_config" in output
    assert "class ConfigLoader" in output
    assert "with open(path) as handle" in output
    assert output.index("src/config.py") < output.index("tests/test_config.py")
    assert "<module>" not in output
    budgeted = index.build_context("load configuration file", max_chars=600, max_files=5, snippet_lines=6)
    assert len(budgeted) <= 600


def test_index_cache_is_reused_and_invalidated(tmp_path, monkeypatch):
    for number in range(101):
        (tmp_path / f"m{number}.py").write_text(f"def f{number}():\n    return {number}\n")
    cache_dir = tmp_path / "cache"
    first = RepositoryIndex(tmp_path, cache_dir=str(cache_dir), cache_min_files=1)
    assert first.search("f42")[0]["name"] == "f42"
    assert len(list(cache_dir.glob("*.json.gz"))) == 1

    def fail(*args, **kwargs):
        raise AssertionError("cache miss: ast.parse should not run")

    with monkeypatch.context() as patch:
        patch.setattr(repository_module.ast, "parse", fail)
        cached = RepositoryIndex(tmp_path, cache_dir=str(cache_dir), cache_min_files=1)
    assert cached.search("f42")[0]["name"] == "f42"

    (tmp_path / "m42.py").write_text("def g42():\n    return 42\n")
    rebuilt = RepositoryIndex(tmp_path, cache_dir=str(cache_dir), cache_min_files=1)
    assert rebuilt.search("g42")[0]["name"] == "g42"


def test_tools_execute_index_in_the_environment_without_installed_agent_package(repository):
    env = LocalEnvironment(cwd=str(repository), env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"})
    result = CodeSearchTool()({"query": "refresh_token", "limit": 1}, env)
    assert result["returncode"] == 0
    assert json.loads(result["output"])["matches"][0]["name"] == "Session.refresh_token"
    mapping = RepoMapTool()({"query": "refresh_token", "max_chars": 256}, env)
    assert mapping["returncode"] == 0
    assert "auth.py:2-5" in mapping["output"]
    assert len(mapping["output"]) <= 256
    context = CodeContextTool()(
        {"query": "refresh_token expired authentication", "max_chars": 600, "max_files": 3}, env
    )
    assert context["returncode"] == 0
    assert "Session.refresh_token" in context["output"]
    assert "async def refresh_token" in context["output"]
    assert len(context["output"]) <= 600
    assert not (repository / ".mini-swe-agent").exists()


def test_agent_treats_code_context_as_a_retrieval_gate(repository):
    agent = DefaultAgent(
        DeterministicModel(outputs=[]),
        LocalEnvironment(cwd=str(repository), env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"}),
        enabled_tools=["code_context"],
    )
    with pytest.raises(FormatError, match="code_context"):
        agent.execute_action({"kind": "bash", "action": "ls"})
    result = agent.execute_action(
        {"kind": "tool", "tool_name": "code_context", "tool_args": {"query": "refresh_token", "max_chars": 400}}
    )
    assert result["returncode"] == 0
    assert "refresh_token" in result["output"]


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
    assert (
        agent.execute_action({"kind": "tool", "tool_name": "code_search", "tool_args": {"query": "refresh_token"}})[
            "returncode"
        ]
        == 0
    )
    assert agent.execute_action({"kind": "tool", "tool_name": "repo_map", "tool_args": {}})["returncode"] == 127
    assert agent.execute_action({"kind": "bash", "action": "pwd"})["returncode"] == 0
    assert (
        DefaultAgent(
            DeterministicModel(outputs=[]), LocalEnvironment(cwd=str(repository)), enabled_tools=[]
        ).execute_action({"kind": "bash", "action": "pwd"})["returncode"]
        == 0
    )
    with pytest.raises(ValueError, match="Unknown enabled tools"):
        DefaultAgent(DeterministicModel(outputs=[]), LocalEnvironment(), enabled_tools=["missing_tool"])


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (CodeSearchTool(), {"query": ""}),
        (CodeSearchTool(), {"query": "a", "limit": 0}),
        (RepoMapTool(), {"max_chars": -1}),
        (RepoMapTool(), {"query": 123}),
        (CodeContextTool(), {"query": ""}),
        (CodeContextTool(), {"query": "a", "max_files": 0}),
        (CodeContextTool(), {"query": "a", "snippet_lines": -1}),
    ],
)
def test_invalid_parameters_fail_before_running_code(tool, args):
    assert tool(args)["returncode"] == 2
