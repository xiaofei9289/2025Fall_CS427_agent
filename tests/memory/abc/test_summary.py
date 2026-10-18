from __future__ import annotations

from minisweagent.memory.abc.budget import estimate_text_tokens
from minisweagent.memory.abc.conversation import parse_conversation
from minisweagent.memory.abc.summary import build_evidence_summary


def transcript(actions):
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task", "extra": {"kind": "task"}},
    ]
    for action, output, code in actions:
        messages.append({"role": "assistant", "content": action})
        messages.append(
            {
                "role": "user",
                "content": f"Observation: <returncode>{code}</returncode><output>{output}</output>",
                "extra": {"kind": "observation", "returncode": code},
            }
        )
    return messages


def summary_for(actions, limit=1000):
    messages = transcript(actions)
    conversation = parse_conversation(messages)
    return build_evidence_summary(conversation.segments, conversation.steps, token_limit=limit)


def test_records_reads_with_step_and_source():
    summary = summary_for([("```bash\ncat src/app.py\n```", "SOURCE_CODE", 0)])
    assert "step 1" in summary.text
    assert "read src/app.py" in summary.text
    assert "SOURCE_CODE" in summary.text
    assert summary.read_facts == 1


def test_write_invalidates_the_read_of_the_same_path():
    summary = summary_for(
        [
            ("```bash\ncat src/app.py\n```", "OLD_CONTENT", 0),
            ("```bash\nsed -i 's/old/new/' src/app.py\n```", "edited", 0),
        ]
    )
    assert "OLD_CONTENT" not in summary.text
    assert "modified src/app.py" in summary.text
    assert summary.write_facts == 1


def test_failure_is_removed_when_the_same_command_succeeds():
    summary = summary_for(
        [
            ("```bash\npytest tests/test_app.py\n```", "FAILED", 1),
            ("```bash\npytest tests/test_app.py\n```", "PASSED", 0),
        ]
    )
    assert "FAILED" not in summary.text
    assert "Failures" not in summary.text


def test_unresolved_failure_is_reported_as_open_issue():
    summary = summary_for([("```bash\npytest tests/test_app.py\n```", "FAILED", 1)])
    assert "Failures / open issues" in summary.text
    assert "pytest tests/test_app.py" in summary.text
    assert "FAILED" in summary.text
    assert summary.failure_facts == 1


def test_unknown_target_write_clears_earlier_reads():
    summary = summary_for(
        [
            ("```bash\ncat src/app.py\n```", "SECRET_SOURCE", 0),
            ("```bash\npython - <<'EOF'\nopen('src/app.py','w').write('x')\nEOF\n```", "", 0),
        ]
    )
    assert "SECRET_SOURCE" not in summary.text
    assert "unknown targets" in summary.text


def test_summary_never_exceeds_the_token_cap():
    actions = []
    for index in range(10):
        actions.append((f"```bash\ncat src/file{index}.py\n```", "x" * 800, 0))
        actions.append((f"```bash\npytest tests/test_{index}.py\n```", "FAILED " * 100, 1))
    for limit in (40, 80, 120, 200, 400):
        summary = summary_for(actions, limit=limit)
        assert estimate_text_tokens(summary.text) <= limit
        assert summary.text.startswith("[memory] Omitted")


def test_empty_summary_for_no_segments():
    summary = build_evidence_summary([], {}, token_limit=1000)
    assert summary.text == ""
    assert summary.tokens == 0
