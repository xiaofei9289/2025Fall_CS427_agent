from __future__ import annotations

import pytest

from minisweagent.memory.abc.conversation import ConversationError, parse_conversation


def tagged_transcript():
    return [
        {"role": "system", "content": "system", "extra": {"kind": "system"}},
        {"role": "user", "content": "task", "extra": {"kind": "task"}},
        {"role": "assistant", "content": "```bash\ncat a.py\n```"},
        {"role": "user", "content": "Observation: a", "extra": {"kind": "observation", "returncode": 0}},
        {"role": "assistant", "content": "```bash\ncat b.py\n```"},
        {"role": "user", "content": "Observation: b", "extra": {"kind": "observation", "returncode": 0}},
    ]


def test_parse_tagged_transcript_into_complete_turns():
    conversation = parse_conversation(tagged_transcript())
    assert conversation.task_index == 1
    assert conversation.system_indices == (0,)
    assert [segment.kind for segment in conversation.segments] == ["turn", "turn"]
    assert conversation.segments[0].indices == (2, 3)
    assert conversation.segments[1].indices == (4, 5)
    assert conversation.steps == {2: 1, 4: 2}


def test_feedback_stays_inside_the_turn():
    messages = tagged_transcript()[:4] + [
        {"role": "user", "content": "Please use one action.", "extra": {"kind": "feedback"}},
        {"role": "assistant", "content": "```bash\ncat b.py\n```"},
        {"role": "user", "content": "Observation: b", "extra": {"kind": "observation", "returncode": 0}},
    ]
    conversation = parse_conversation(messages)
    assert conversation.segments[0].indices == (2, 3, 4)
    assert conversation.segments[1].indices == (5, 6)


def test_untagged_transcript_uses_conservative_fallback():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "fix the bug"},
        {"role": "assistant", "content": "```bash\nls\n```"},
        {"role": "user", "content": "Observation: files"},
    ]
    conversation = parse_conversation(messages)
    assert conversation.task_index == 1
    assert conversation.segments[0].indices == (2, 3)


def test_missing_task_is_rejected():
    with pytest.raises(ConversationError):
        parse_conversation([{"role": "system", "content": "system"}])


def test_history_before_the_task_is_rejected():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "assistant", "content": "old"},
        {"role": "user", "content": "task", "extra": {"kind": "task"}},
    ]
    with pytest.raises(ConversationError):
        parse_conversation(messages)


def test_multiple_tasks_are_rejected():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task one", "extra": {"kind": "task"}},
        {"role": "assistant", "content": "```bash\nls\n```"},
        {"role": "user", "content": "task two", "extra": {"kind": "task"}},
    ]
    with pytest.raises(ConversationError):
        parse_conversation(messages)


def test_loose_user_message_becomes_its_own_segment():
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task", "extra": {"kind": "task"}},
        {"role": "user", "content": "Budget exhausted", "extra": {"kind": "terminal"}},
    ]
    conversation = parse_conversation(messages)
    assert conversation.segments[0].kind == "loose"
    assert conversation.segments[0].indices == (2,)
