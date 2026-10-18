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


def test_memory_search_full_mode_recovers_the_whole_message():
    # A snippet only shows a window around the match; the treatment arm needs the text itself.
    set_search_context([{"role": "user", "content": "EARLY_MARKER\n" + ("q" * 600) + "\nQUERYWORD"}])
    snippet = REGISTRY["memory_search"]({"query": "QUERYWORD"})
    assert "EARLY_MARKER" not in snippet["output"]
    full = REGISTRY["memory_search"]({"query": "QUERYWORD", "mode": "full"})
    assert full["returncode"] == 0
    assert "EARLY_MARKER" in full["output"]


def test_memory_search_opens_a_message_by_index():
    set_search_context(
        [
            {"role": "user", "content": "TASK"},
            {"role": "user", "content": "DROPPED_ERROR: KeyError in src/app.py"},
        ]
    )
    result = REGISTRY["memory_search"]({"index": 1})
    assert result["returncode"] == 0
    assert "DROPPED_ERROR" in result["output"]
    assert REGISTRY["memory_search"]({"index": 9})["returncode"] == 1


def test_memory_search_full_text_respects_the_character_budget():
    set_search_context([{"role": "user", "content": "x" * 5000 + " NEEDLE"}])
    result = REGISTRY["memory_search"]({"index": 0, "max_chars": 120})
    assert result["returncode"] == 0
    assert len(result["output"]) < 400
    assert "truncated" in result["output"]


def test_memory_search_rejects_unknown_mode():
    set_search_context([{"role": "user", "content": "hello"}])
    result = REGISTRY["memory_search"]({"query": "hello", "mode": "everything"})
    assert result["returncode"] == 1
