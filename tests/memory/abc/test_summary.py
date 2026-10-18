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


def test_mixed_read_and_write_of_the_same_path_is_recorded_as_a_write():
    summary = summary_for(
        [("```bash\ncat src/app.py && sed -i 's/x/y/' src/app.py\n```", "OLD_CONTENT", 0)]
    )
    assert "OLD_CONTENT" not in summary.text
    assert "modified src/app.py" in summary.text
    assert summary.read_facts == 0
    assert summary.write_facts == 1


def test_mixed_command_keeps_a_read_of_an_untouched_file():
    summary = summary_for(
        [("```bash\ncat src/app.py && sed -i 's/x/y/' src/other.py\n```", "APP_CONTENT", 0)]
    )
    assert "read src/app.py" in summary.text
    assert "APP_CONTENT" in summary.text
    assert "modified src/other.py" in summary.text


def test_reread_is_the_most_recent_read():
    actions = [("```bash\ncat src/a.py\n```", "A_EARLY", 0)]
    for name in "bcde":
        actions.append((f"```bash\ncat src/{name}.py\n```", f"{name.upper()}_CONTENT", 0))
    actions.append(("```bash\ncat src/a.py\n```", "A_LATEST", 0))
    summary = summary_for(actions, limit=200)
    assert "A_LATEST" in summary.text
    assert "A_EARLY" not in summary.text
    assert "step 6" in summary.text


def test_test_pass_before_a_later_edit_is_not_verification():
    summary = summary_for(
        [
            ("```bash\npytest tests/test_app.py -q\n```", "1 passed", 0),
            ("```bash\nsed -i 's/x/y/' src/app.py\n```", "edited", 0),
        ]
    )
    assert "Verification" not in summary.text
    assert "Earlier test runs" in summary.text
    assert "not verification" in summary.text
    assert "pytest tests/test_app.py" in summary.text


def test_test_pass_after_the_latest_edit_is_verification():
    summary = summary_for(
        [
            ("```bash\nsed -i 's/x/y/' src/app.py\n```", "edited", 0),
            ("```bash\npytest tests/test_app.py -q\n```", "1 passed", 0),
        ]
    )
    assert "Verification (tests passing after the latest edit):" in summary.text
    assert "pytest tests/test_app.py" in summary.text
    assert "Earlier test runs" not in summary.text


def test_later_write_invalidates_a_summarized_read():
    messages = transcript(
        [
            ("```bash\ncat src/app.py\n```", "OLD_CONTENT", 0),
            ("```bash\nsed -i 's/x/y/' src/app.py\n```", "edited", 0),
        ]
    )
    conversation = parse_conversation(messages)
    earlier, later = conversation.segments
    summary = build_evidence_summary(
        [earlier],
        conversation.steps,
        token_limit=1000,
        later_segments=[later],
    )
    assert "OLD_CONTENT" not in summary.text
    assert "Superseded by later edits:" in summary.text
    assert "modified src/app.py after the summarized read" in summary.text
    assert summary.superseded_read_facts == 1


def test_later_unknown_write_supersedes_every_summarized_read():
    messages = transcript(
        [
            ("```bash\ncat src/a.py\n```", "SECRET_A", 0),
            ("```bash\ncat src/b.py\n```", "SECRET_B", 0),
            ("```bash\npython - <<'EOF'\nopen('src/a.py','w').write('x')\nEOF\n```", "", 0),
        ]
    )
    conversation = parse_conversation(messages)
    summary = build_evidence_summary(
        list(conversation.segments[:2]),
        conversation.steps,
        token_limit=1000,
        later_segments=[conversation.segments[2]],
    )
    assert "SECRET_A" not in summary.text
    assert "SECRET_B" not in summary.text
    assert "unknown targets" in summary.text


def test_later_write_marks_a_summarized_test_pass_stale():
    messages = transcript(
        [
            ("```bash\npytest tests/test_app.py -q\n```", "1 passed", 0),
            ("```bash\nsed -i 's/x/y/' src/app.py\n```", "edited", 0),
        ]
    )
    conversation = parse_conversation(messages)
    earlier, later = conversation.segments
    summary = build_evidence_summary(
        [earlier],
        conversation.steps,
        token_limit=1000,
        later_segments=[later],
    )
    assert "Verification" not in summary.text
    assert "Earlier test runs" in summary.text
    assert "not verification" in summary.text
    assert summary.stale_verification_facts == 1
    assert summary.verification_facts == 0


def test_later_test_failure_marks_an_earlier_pass_stale():
    messages = transcript(
        [
            ("```bash\npytest tests/test_app.py -q\n```", "1 passed", 0),
            ("```bash\npytest tests/test_app.py -q\n```", "1 failed", 1),
        ]
    )
    conversation = parse_conversation(messages)
    earlier, later = conversation.segments
    summary = build_evidence_summary(
        [earlier],
        conversation.steps,
        token_limit=1000,
        later_segments=[later],
    )
    assert "Verification" not in summary.text
    assert "Earlier test runs" in summary.text
    assert "not verification" in summary.text
    assert summary.stale_verification_facts == 1


def test_unknown_write_replaces_the_known_modified_list():
    summary = summary_for(
        [
            ("```bash\nsed -i 's/x/y/' src/app.py\n```", "edited", 0),
            ("```bash\npython - <<'EOF'\nopen('src/other.py','w').write('x')\nEOF\n```", "", 0),
        ]
    )
    assert "modified src/app.py" not in summary.text
    assert "unknown targets" in summary.text
    assert summary.write_facts == 1


def test_a_grep_for_pytest_is_not_verification():
    summary = summary_for(
        [("```bash\ngrep -n 'pytest' tests/test_app.py\n```", "tests/test_app.py:1:import pytest", 0)]
    )
    assert "Verification" not in summary.text
    assert "Other executed actions" in summary.text


def test_pytest_after_a_cd_is_verification():
    summary = summary_for(
        [("```bash\ncd /testbed && python -m pytest tests/test_app.py -q\n```", "1 passed", 0)]
    )
    assert "Verification (tests passing after the latest edit):" in summary.text
    assert "python -m pytest" in summary.text


def test_uv_run_pytest_is_verification():
    summary = summary_for([("```bash\nuv run pytest tests/test_app.py -q\n```", "1 passed", 0)])
    assert "Verification (tests passing after the latest edit):" in summary.text
    assert "uv run pytest" in summary.text


def test_pytest_version_is_not_verification():
    summary = summary_for([("```bash\npytest --version\n```", "pytest 8.0", 0)])
    assert "Verification" not in summary.text
    assert "Other executed actions" in summary.text


def test_a_test_after_a_read_is_still_verification():
    summary = summary_for(
        [("```bash\ncat src/app.py && pytest tests/test_app.py -q\n```", "SOURCE 1 passed", 0)]
    )
    assert "Verification (tests passing after the latest edit):" in summary.text
    assert "read src/app.py" in summary.text
    assert "pytest tests/test_app.py" in summary.text


def test_a_test_redirect_to_a_log_is_verification_not_a_source_write():
    summary = summary_for(
        [("```bash\npytest tests/test_app.py -q > /tmp/pytest.log\n```", "1 passed", 0)]
    )
    assert "Verification (tests passing after the latest edit):" in summary.text
    assert "modified" not in summary.text
    assert summary.write_facts == 0
