"""Tests for memory search."""

import pytest

from minisweagent.memory.search import MemorySearch, set_search_context
from minisweagent.memory.session import SessionMemory


MESSAGES = [
    {"role": "system", "content": "You are helpful"},
    {"role": "user", "content": "Fix the parser in src/app.py"},
    {"role": "assistant", "content": "The parser raised a Traceback in src/app.py"},
    {"role": "user", "content": "Observation: tests passed"},
]


class TestMemorySearch:
    def test_keyword_search_requires_every_term(self):
        hits = MemorySearch().search(MESSAGES, "parser traceback")
        assert len(hits) == 1
        assert hits[0]["index"] == 2
        assert "Traceback" in hits[0]["snippet"]

    def test_keyword_search_miss(self):
        assert MemorySearch().search(MESSAGES, "database migration") == []

    def test_regex_search(self):
        hits = MemorySearch().search(MESSAGES, r"src/\w+\.py", use_regex=True)
        assert [hit["index"] for hit in hits] == [1, 2]

    def test_invalid_regex_raises(self):
        with pytest.raises(Exception):
            MemorySearch().search(MESSAGES, "(", use_regex=True)

    def test_role_filter(self):
        hits = MemorySearch().search(MESSAGES, "parser", role="user")
        assert len(hits) == 1
        assert hits[0]["role"] == "user"

    def test_session_search(self, tmp_path):
        memory = SessionMemory(tmp_path, "bugfix")
        memory.save_session(MESSAGES)
        hits = memory.search("traceback")
        assert len(hits) == 1
        assert hits[0]["session_id"] == "bugfix"
        assert hits[0]["index"] == 2

    def test_search_context_roundtrip(self):
        set_search_context(MESSAGES, None)
        from minisweagent.memory.search import get_search_context

        messages, session = get_search_context()
        assert messages == MESSAGES
        assert session is None
