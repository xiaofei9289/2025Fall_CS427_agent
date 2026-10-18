from __future__ import annotations

from minisweagent.memory.abc.budget import estimate_text_tokens
from minisweagent.memory.abc.search import MemorySearchTool, SearchContext, search_transcript


def messages():
    return [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "Fix the parser in src/parser.py", "extra": {"kind": "task"}},
        {"role": "assistant", "content": "```bash\ncat src/parser.py\n```"},
        {
            "role": "user",
            "content": "Observation: <returncode>0</returncode><output>def parse(): raise ValueError('bad token')</output>",
            "extra": {"kind": "observation", "returncode": 0},
        },
        {"role": "assistant", "content": "```bash\npytest tests/test_parser.py\n```"},
        {
            "role": "user",
            "content": "Observation: <returncode>1</returncode><output>FAILED test_parser.py::test_error</output>",
            "extra": {"kind": "observation", "returncode": 1},
        },
    ]


def test_keyword_search_requires_every_term_and_returns_indices():
    hits = search_transcript(messages(), "ValueError bad")
    assert [hit["index"] for hit in hits] == [3]
    assert "bad token" in hits[0]["snippet"]


def test_regex_search_and_limit():
    hits = search_transcript(messages(), r"test_\w+", use_regex=True, limit=2)
    assert hits
    assert all("test_" in hit["snippet"] for hit in hits)


def test_tool_schema_has_no_session_or_future_scope():
    tool = MemorySearchTool(SearchContext())
    properties = tool.parameters["properties"]
    assert "scope" not in properties
    assert "max_chars" not in properties
    assert "index" in properties


def test_tool_search_is_capped_by_tokens():
    context = SearchContext()
    context.update(messages(), step=3)
    tool = MemorySearchTool(context, token_limit=20)
    result = tool({"query": "parser", "mode": "full", "limit": 5})
    assert result["returncode"] == 0
    assert result["extra"]["retrieval_tokens"] <= 20
    assert estimate_text_tokens(result["output"]) <= 20


def test_index_opens_one_message_and_cannot_see_the_future():
    context = SearchContext()
    transcript = messages()
    context.update(transcript, step=3)
    tool = MemorySearchTool(context, token_limit=100)
    result = tool({"index": 3})
    assert "#3" in result["output"]
    assert "bad token" in result["output"]

    # Appending to the caller's list after the snapshot must not become visible.
    transcript.append({"role": "assistant", "content": "FUTURE_SECRET"})
    future = tool({"query": "FUTURE_SECRET"})
    assert "No matches" in future["output"]


def test_search_context_is_per_agent_not_global():
    first = SearchContext()
    second = SearchContext()
    first.update(messages(), step=1)
    second.update([{"role": "system", "content": "other run"}], step=1)
    assert "bad token" in MemorySearchTool(first)({"query": "bad token"})["output"]
    assert "No matches" in MemorySearchTool(second)({"query": "bad token"})["output"]


def test_index_out_of_range_and_invalid_regex_are_errors():
    context = SearchContext()
    context.update(messages(), step=1)
    tool = MemorySearchTool(context)
    assert tool({"index": 99})["returncode"] == 1
    assert tool({"query": "[", "use_regex": True})["returncode"] == 1


def test_empty_transcript_is_handled():
    tool = MemorySearchTool(SearchContext())
    assert tool({"query": "anything"})["returncode"] == 0
    assert "No transcript" in tool({"query": "anything"})["output"]
