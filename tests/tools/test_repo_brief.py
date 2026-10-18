import sys
from pathlib import Path

import pytest

import minisweagent.tools.basic  # noqa: F401
import minisweagent.tools.code_search  # noqa: F401
from minisweagent.agents.default import DefaultAgent, FormatError
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models.test_models import DeterministicModel
from minisweagent.retrieval.brief import build_brief, extract_issue_hints
from minisweagent.retrieval.brief_tool import build_repo_brief
from minisweagent.retrieval.repository import RepositoryIndex


def write_repo(root: Path) -> None:
    (root / "src").mkdir()
    (root / "tests").mkdir()
    (root / "docs").mkdir()
    (root / "src" / "auth.py").write_text(
        '''class Session:
    """A login session."""

    def refresh_token(self, token):
        """Refresh an expired authentication token."""
        return token


def login(user):
    return Session().refresh_token(user)
'''
    )
    (root / "tests" / "test_auth.py").write_text(
        "from src.auth import Session\n\ndef test_refresh_token():\n    return Session().refresh_token('x')\n"
    )
    (root / "docs" / "guide.py").write_text('"""Refresh token tutorial."""\n\ndef example():\n    return 1\n')


def test_extract_issue_hints_prefers_code_like_tokens() -> None:
    issue = (
        "Field.__hash__ changes. See src/auth.py and `Session.refresh_token`. "
        'Traceback: File "src/auth.py", line 5, in refresh_token. '
        "The URLResolver should not do this. e.g. Description. HTTP."
    )
    hints = extract_issue_hints(issue)
    assert "src/auth.py" in hints["paths"]
    assert hints["frames"] == [{"path": "src/auth.py", "line": 5, "function": "refresh_token"}]
    assert "Field.__hash__" in hints["symbols"]
    assert "Session.refresh_token" in hints["symbols"]
    assert "refresh_token" in hints["symbols"]
    assert "e.g" not in hints["symbols"]
    assert "Description" not in hints["symbols"]
    assert "URLResolver" in hints["symbols"]


def test_brief_routes_paths_and_definitions_before_bm25(tmp_path: Path) -> None:
    write_repo(tmp_path)
    index = RepositoryIndex(tmp_path)
    issue = "`Session.refresh_token` is broken. See src/auth.py. File \"src/auth.py\", line 5, in refresh_token."
    text = build_brief(index, issue, max_chars=2000, max_files=4)
    assert len(text) <= 2000
    assert "Inspect src/auth.py" in text
    assert "src/auth.py" in text
    assert "refresh_token" in text
    assert "src/auth.py:2" in text or "src/auth.py:5" in text
    assert "tests/test_auth.py" not in text or text.index("src/auth.py") < text.index("tests/test_auth.py")
    assert "<module>" not in text


def test_brief_is_honest_when_hints_do_not_resolve(tmp_path: Path) -> None:
    write_repo(tmp_path)
    index = RepositoryIndex(tmp_path)
    text = build_brief(index, "See missing/does_not_exist.py and `missing_symbol`.", max_chars=2000)
    assert "did not resolve" in text
    assert "Fallback BM25 candidates" in text
    assert "Inspect " not in text


def test_brief_respects_character_budget(tmp_path: Path) -> None:
    write_repo(tmp_path)
    index = RepositoryIndex(tmp_path)
    text = build_brief(index, "Session refresh token src/auth.py", max_chars=400, max_files=3)
    assert len(text) <= 400
    assert "[brief truncated" in text


def test_brief_tool_runs_inside_the_environment(tmp_path: Path) -> None:
    write_repo(tmp_path)
    env = LocalEnvironment(
        cwd=str(tmp_path),
        env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"},
    )
    text = build_repo_brief(env, "See src/auth.py and `Session.refresh_token`.", max_chars=1500, max_files=3)
    assert "src/auth.py" in text
    assert "Session.refresh_token" in text
    assert not (tmp_path / ".mini-swe-agent").exists()


def test_agent_injects_brief_and_does_not_gate(tmp_path: Path) -> None:
    write_repo(tmp_path)
    model = DeterministicModel(
        outputs=["```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"],
    )
    agent = DefaultAgent(
        model,
        LocalEnvironment(cwd=str(tmp_path), env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"}),
        enabled_tools=["read_file"],
        retrieval_policy="brief",
        repo_brief_max_chars=1500,
    )
    status, _message = agent.run("`refresh_token` fails in src/auth.py")
    assert status == "Submitted"
    assert agent.repo_brief_text
    assert "<repository_brief>" in agent.messages[1]["content"]
    assert "src/auth.py" in agent.messages[1]["content"]
    # "brief" leaves action choice to the model: no mandatory first search.
    assert agent.retrieval_gate == set()


def test_agent_gate_policy_still_enforces_first_retrieval(tmp_path: Path) -> None:
    write_repo(tmp_path)
    agent = DefaultAgent(
        DeterministicModel(outputs=[]),
        LocalEnvironment(cwd=str(tmp_path), env={"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"}),
        enabled_tools=["code_search"],
        retrieval_policy="gate",
    )
    assert agent.retrieval_gate == {"code_search"}
    with pytest.raises(FormatError, match="code_search"):
        agent.execute_action({"kind": "bash", "action": "pwd"})
    assert agent.execute_action(
        {"kind": "tool", "tool_name": "code_search", "tool_args": {"query": "refresh_token"}}
    )["returncode"] == 0
    assert agent.retrieval_used is True
    assert agent.retrieval_calls == 1


def test_unknown_retrieval_policy_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="retrieval_policy"):
        DefaultAgent(
            DeterministicModel(outputs=[]),
            LocalEnvironment(cwd=str(tmp_path)),
            enabled_tools=[],
            retrieval_policy="bogus",
        )
