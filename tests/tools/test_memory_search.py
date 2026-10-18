"""Tests for the memory_search tool."""

import minisweagent.tools.memory_search  # noqa: F401
from minisweagent.memory.search import set_search_context
from minisweagent.memory.session import SessionMemory
from minisweagent.tools import REGISTRY


def test_memory_search_current_transcript():
    set_search_context(
        [
            {"role": "user", "content": "Investigate src/app.py"},
            {"role": "assistant", "content": "Found a Traceback in src/app.py"},
        ]
    )
    result = REGISTRY["memory_search"]({"query": "traceback"})
    assert result["returncode"] == 0
    assert "Traceback" in result["output"]


def test_memory_search_requires_query():
    result = REGISTRY["memory_search"]({"query": "  "})
    assert result["returncode"] == 1


def test_memory_search_invalid_regex():
    set_search_context([{"role": "user", "content": "hello"}])
    result = REGISTRY["memory_search"]({"query": "(", "use_regex": True})
    assert result["returncode"] == 1
    assert "Invalid regex" in result["output"]


def test_memory_search_saved_sessions(tmp_path):
    memory = SessionMemory(tmp_path, "saved")
    memory.save_session([{"role": "assistant", "content": "port is 8080"}])
    set_search_context([], memory)
    result = REGISTRY["memory_search"]({"query": "8080", "scope": "sessions"})
    assert result["returncode"] == 0
    assert "8080" in result["output"]
    assert "saved" in result["output"]
