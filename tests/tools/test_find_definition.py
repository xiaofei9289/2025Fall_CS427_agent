import subprocess
import sys
from pathlib import Path

import pytest

from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.docker import DockerEnvironment
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models.test_models import DeterministicModel
from minisweagent.tools.find_definition import FindDefinitionTool

SOURCE = """\
GLOBAL = 1
ANNOTATED: int = 2
PAIR_A, PAIR_B = 1, 2

class Config:
    attr = 3

    async def load_config(self, path):
        return path

    def parse_value(self, value):
        return value

def load_config(path):
    return Config().load_config(path)

async def async_load(path):
    return path
"""


@pytest.fixture
def sample(tmp_path):
    (tmp_path / "sample.py").write_text(SOURCE)
    (tmp_path / "other.py").write_text("def other_symbol(path):\n    return path\n")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "noise.py").write_text("def load_config(path):\n    return path\n")
    return tmp_path


def env_for(root: Path) -> LocalEnvironment:
    return LocalEnvironment(
        cwd=str(root),
        env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"},
    )


def test_finds_async_annotated_and_qualified_definitions(sample):
    tool = FindDefinitionTool()
    result = tool({"symbol": "load_config", "path": str(sample)})
    assert result["returncode"] == 0
    assert "Found 2 definition(s)" in result["output"]
    assert "function load_config" in result["output"]
    assert "method Config.load_config" in result["output"]
    assert ".venv" not in result["output"]

    result = tool({"symbol": "Config.load_config", "path": str(sample)})
    assert result["returncode"] == 0
    assert "Found 1 definition(s)" in result["output"]
    assert "method Config.load_config" in result["output"]

    result = tool({"symbol": "async_load", "path": str(sample)})
    assert result["returncode"] == 0
    assert "function async_load" in result["output"]

    result = tool({"symbol": "ANNOTATED", "path": str(sample), "symbol_type": "variable"})
    assert result["returncode"] == 0
    assert "variable ANNOTATED" in result["output"]

    result = tool({"symbol": "PAIR_B", "path": str(sample), "symbol_type": "variable"})
    assert result["returncode"] == 0
    assert "variable PAIR_B" in result["output"]


def test_file_path_limits_results_to_that_file(sample):
    result = FindDefinitionTool()({"symbol": "load_config", "path": str(sample / "sample.py")})
    assert result["returncode"] == 0
    assert "Found 2 definition(s)" in result["output"]
    assert "other.py" not in result["output"]


def test_context_lines_and_limit(sample):
    result = FindDefinitionTool()(
        {"symbol": "async_load", "path": str(sample), "context_lines": 1, "limit": 1}
    )
    assert result["returncode"] == 0
    assert ">>>" in result["output"]
    assert "return path" in result["output"]
    assert "17: async def async_load" in result["output"]


def test_limit_reports_remaining_matches(sample):
    result = FindDefinitionTool()({"symbol": "load_config", "path": str(sample), "limit": 1})
    assert result["returncode"] == 0
    assert "... and 1 more result(s)" in result["output"]


def test_environment_execution_uses_the_shared_index(sample):
    tool = FindDefinitionTool()
    result = tool({"symbol": "async_load", "path": "."}, env_for(sample))
    assert result["returncode"] == 0
    assert "sample.py:17: function async_load" in result["output"]

    result = tool({"symbol": "ANNOTATED", "path": ".", "symbol_type": "variable"}, env_for(sample))
    assert result["returncode"] == 0
    assert "variable ANNOTATED" in result["output"]


def test_environment_rejects_paths_outside_the_workspace(sample):
    tool = FindDefinitionTool()
    result = tool({"symbol": "load_config", "path": "../outside"}, env_for(sample))
    assert result["returncode"] != 0
    assert "within" in result["output"]

    result = tool({"symbol": "load_config", "path": str(sample.parent / "outside.py")}, env_for(sample))
    assert result["returncode"] != 0
    assert "within" in result["output"]


def test_missing_path_and_missing_symbol(sample):
    tool = FindDefinitionTool()
    result = tool({"symbol": "load_config", "path": str(sample / "missing.py")})
    assert result["returncode"] == 2
    assert "Path not found" in result["output"]

    result = tool({"symbol": "does_not_exist", "path": str(sample)})
    assert result["returncode"] == 0
    assert "No definition found" in result["output"]


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"symbol": ""},
        {"symbol": 123},
        {"symbol": "x", "symbol_type": "method"},
        {"symbol": "x", "context_lines": -1},
        {"symbol": "x", "limit": 0},
        {"symbol": "x", "limit": 51},
    ],
)
def test_invalid_parameters_fail_before_indexing(args):
    assert FindDefinitionTool()(args)["returncode"] == 2


def test_agent_dispatches_find_definition_with_the_environment(sample):
    agent = DefaultAgent(
        DeterministicModel(outputs=[]),
        env_for(sample),
        enabled_tools=["find_definition"],
    )
    result = agent.execute_action(
        {"kind": "tool", "tool_name": "find_definition", "tool_args": {"symbol": "async_load", "path": "."}}
    )
    assert result["returncode"] == 0
    assert "sample.py:17: function async_load" in result["output"]


def docker_available() -> bool:
    """Check whether the slow container test can run in this environment."""
    try:
        subprocess.run(["docker", "version"], capture_output=True, check=True, timeout=10)
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


@pytest.mark.slow
@pytest.mark.skipif(not docker_available(), reason="Docker not available")
def test_find_definition_inside_container():
    """The real SWE-bench path: run the embedded index in a container without git."""
    env = DockerEnvironment(image="python:3.11", cwd="/", timeout=60)
    try:
        command = "mkdir -p /testbed/pkg && cat > /testbed/pkg/sample.py <<'PY'\n" + SOURCE + "PY\n"
        written = env.execute(command)
        assert written["returncode"] == 0, written["output"]

        # DockerEnvironment starts at /, so make /testbed the workspace after creating it.
        env.config.cwd = "/testbed"
        tool = FindDefinitionTool()
        result = tool({"symbol": "load_config", "path": "."}, env)
        assert result["returncode"] == 0, result["output"]
        assert "Found 2 definition(s)" in result["output"]
        assert "pkg/sample.py" in result["output"]
        assert "method Config.load_config" in result["output"]

        result = tool({"symbol": "PAIR_B", "path": ".", "symbol_type": "variable"}, env)
        assert result["returncode"] == 0, result["output"]
        assert "variable PAIR_B" in result["output"]
    finally:
        env.cleanup()
