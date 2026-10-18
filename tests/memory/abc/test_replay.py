from __future__ import annotations

import pytest

from minisweagent.memory.abc import PolicyLimits, build_policy
from minisweagent.memory.abc.conversation import ConversationError
from minisweagent.memory.abc.replay import replay_transcript


def message(action, observation, code=0):
    return [
        {"role": "assistant", "content": action},
        {
            "role": "user",
            "content": f"<returncode>{code}</returncode><output>{observation}</output>",
            "extra": {"kind": "observation", "returncode": code},
        },
    ]


def transcript(actions):
    messages = [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "TASK", "extra": {"kind": "task"}},
    ]
    for action, observation, code in actions:
        messages += message(action, observation, code)
    return messages


def policy(total_tokens=260):
    return build_policy("summary", PolicyLimits(total_tokens=total_tokens, summary_tokens=120, retrieval_tokens=60))


def read(name, output):
    return (f"```bash\ncat src/{name}.py\n```", output, 0)


def test_complete_reads_are_not_recovery():
    messages = transcript([read("a", "A" * 100), read("a", "A2" * 100)])
    stats = replay_transcript(messages, policy(total_tokens=800))
    assert stats.repeat_reads == 1
    assert stats.recovery_reads == 0


def test_lost_evidence_makes_a_reread_a_recovery():
    actions = [read("a", "A" * 100)]
    for index in range(4):
        actions.append(read(f"f{index}", f"f{index} " + "f" * 100))
    actions.append(read("a", "A2 " + "a" * 100))
    stats = replay_transcript(transcript(actions), policy(total_tokens=180))
    assert stats.repeat_reads == 1
    assert stats.recovery_reads == 1
    assert stats.lost_recovery_reads == 1


def test_summarized_evidence_makes_a_reread_a_recovery():
    actions = [read("a", "A" * 100)]
    for index in range(4):
        actions.append(read(f"f{index}", f"f{index} " + "f" * 100))
    actions.append(read("a", "A2 " + "a" * 100))
    stats = replay_transcript(transcript(actions), policy(total_tokens=260))
    assert stats.repeat_reads == 1
    assert stats.recovery_reads == 1
    assert stats.summary_recovery_reads == 1


def test_reread_after_a_write_is_not_counted_as_recovery():
    messages = transcript(
        [
            read("a", "OLD_A" + "a" * 100),
            ("```bash\nsed -i 's/x/y/' src/a.py\n```", "edited", 0),
            read("a", "NEW_A" + "a" * 100),
        ]
    )
    stats = replay_transcript(messages, policy(total_tokens=180))
    assert stats.repeat_reads == 0
    assert stats.recovery_reads == 0
    assert stats.write_events == 1


def test_read_many_files_counts_every_path():
    messages = transcript(
        [
            (
                '```tool\n{"name": "read_many_files", "args": {"paths": ["src/a.py", "src/b.py"]}}\n```',
                "both files",
                0,
            )
        ]
    )
    stats = replay_transcript(messages, policy(total_tokens=800))
    assert stats.read_events == 2


def test_malformed_transcript_raises():
    with pytest.raises(ConversationError):
        replay_transcript([{"role": "assistant", "content": "```bash\ncat a\n```"}], policy())
