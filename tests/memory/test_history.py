"""Tests for history management functionality."""

import copy
import json

import pytest

from minisweagent.memory.history import HistoryManager, estimate_tokens


class TestHistoryManager:
    """Test cases for HistoryManager class."""

    def test_init_default(self):
        """Test HistoryManager initialization with defaults."""
        manager = HistoryManager()
        assert manager.max_messages == 50
        assert manager.keep_system is True

    def test_init_custom(self):
        """Test HistoryManager initialization with custom values."""
        manager = HistoryManager(max_messages=20, keep_system=False)
        assert manager.max_messages == 20
        assert manager.keep_system is False

    def test_compress_messages_under_limit(self):
        """Test compression when messages are under the limit."""
        manager = HistoryManager(max_messages=5)
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = manager.compress_messages(messages)
        assert result == messages

    def test_compress_messages_over_limit_keep_system(self):
        """Test compression when messages exceed limit with system kept."""
        manager = HistoryManager(max_messages=3, keep_system=True)
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"},
        ]
        result = manager.compress_messages(messages)

        # Should keep system message + 2 most recent messages
        assert len(result) == 3
        assert result[0]["role"] == "system"
        assert result[1]["content"] == "Response 2"
        assert result[2]["content"] == "Message 3"

    def test_compress_messages_over_limit_no_system(self):
        """Test compression when messages exceed limit without keeping system."""
        manager = HistoryManager(max_messages=2, keep_system=False)
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
        ]
        result = manager.compress_messages(messages)

        # Should keep only 2 most recent messages
        assert len(result) == 2
        assert result[0]["content"] == "Message 2"
        assert result[1]["content"] == "Response 2"

    def test_get_summary_stats(self):
        """Test summary statistics generation."""
        manager = HistoryManager()
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "How are you?"},
        ]
        stats = manager.get_summary_stats(messages)

        assert stats["total_messages"] == 4
        assert stats["total_characters"] > 0
        assert stats["role_counts"]["system"] == 1
        assert stats["role_counts"]["user"] == 2
        assert stats["role_counts"]["assistant"] == 1
        assert stats["compressed"] is False

    def test_get_summary_stats_compressed(self):
        """Test summary statistics when compression would occur."""
        manager = HistoryManager(max_messages=2)
        messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "User 1"},
            {"role": "assistant", "content": "Assistant 1"},
            {"role": "user", "content": "User 2"},
        ]
        stats = manager.get_summary_stats(messages)
        assert stats["compressed"] is True

    def test_empty_messages(self):
        """Test handling of empty message list."""
        manager = HistoryManager()
        result = manager.compress_messages([])
        assert result == []

        stats = manager.get_summary_stats([])
        assert stats["total_messages"] == 0
        assert stats["total_characters"] == 0
        assert stats["role_counts"] == {}

    def test_multiple_system_messages(self):
        """Test handling of multiple system messages."""
        manager = HistoryManager(max_messages=2, keep_system=True)
        messages = [
            {"role": "system", "content": "System 1"},
            {"role": "system", "content": "System 2"},
            {"role": "user", "content": "User message"},
            {"role": "assistant", "content": "Assistant message"},
        ]
        result = manager.compress_messages(messages)

        # Should keep both system messages (no room for others)
        assert len(result) == 2
        assert all(msg["role"] == "system" for msg in result)

    def test_compress_salient_keeps_task_error_and_latest(self):
        """Salient compression keeps the task, a failure, and the latest turn."""
        manager = HistoryManager(max_messages=5, keep_system=True)
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Fix the parser in src/app.py"},
            {"role": "assistant", "content": "```bash\npython src/app.py\n```"},
            {"role": "user", "content": "<returncode>1</returncode> Traceback Error in src/app.py line 10"},
            {"role": "assistant", "content": "Trying a different edit"},
            {"role": "user", "content": "Observation: command finished"},
            {"role": "assistant", "content": "Still looking"},
            {"role": "user", "content": "Observation: latest status"},
        ]
        result = manager.compress_salient(messages)

        assert len(result) <= 5
        contents = [msg["content"] for msg in result]
        assert result[0]["role"] == "system"
        assert "Fix the parser in src/app.py" in contents
        assert any("Traceback Error" in content for content in contents)
        assert result[-1]["content"] == "Observation: latest status"

    def test_compress_salient_adds_summary_when_budget_allows(self):
        """Dropped messages are described when a summary slot fits."""
        manager = HistoryManager(max_messages=6, keep_system=True)
        messages = [{"role": "system", "content": "System"}]
        messages.append({"role": "user", "content": "Start the task"})
        for index in range(8):
            messages.append({"role": "assistant", "content": f"note {index}"})
            messages.append({"role": "user", "content": f"ack {index}"})
        messages.append({"role": "assistant", "content": "latest command"})
        messages.append({"role": "user", "content": "latest turn"})
        result = manager.compress_salient(messages)

        assert len(result) <= 6
        assert any(msg["content"].startswith("[memory] Omitted") for msg in result)
        assert result[-1]["content"] == "latest turn"

    def test_prompt_is_unchanged_before_history_limit(self):
        manager = HistoryManager(max_messages=50)
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "Fix the bug"},
            {"role": "assistant", "content": "```bash\nsed -n '1,20p' django/core/mail/message.py\n```"},
            {"role": "user", "content": "<returncode>1</returncode>\nnot found"},
        ]
        sent = manager.prompt_messages(messages)
        assert sent == messages


def tool_turn(name, path, code=0, output="source", *, selector=None, **extra_args):
    args = {"path": path, **extra_args}
    if selector is not None:
        args["selector"] = selector
    return [
        {"role": "assistant", "content": "```tool\n" + json.dumps({"name": name, "args": args}) + "\n```"},
        {"role": "user", "content": output, "extra": {"returncode": code}},
    ]


def test_compression_keeps_recent_complete_turns_despite_old_errors():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    for step in range(12):
        messages += tool_turn(
            "read_file",
            f"src/file{step}.py",
            code=1 if step < 8 else 0,
            output="error exception traceback failed failure" if step < 8 else "source",
        )
    original = copy.deepcopy(messages)
    sent = HistoryManager(max_messages=12).prompt_messages(messages)
    assert len(sent) <= 12  # Includes the summary.
    assert sent[-8:] == messages[-8:]
    assert sent[:2] == messages[:2]
    assert messages == original
    for action, observation in zip(messages[2::2], messages[3::2]):
        assert (action in sent) == (observation in sent)
    summary = next(m for m in sent if m["content"].startswith("[memory]"))
    assert summary["role"] == "user"


def test_finalization_instruction_stays_with_latest_action_and_observation():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    for step in range(5):
        messages += tool_turn("read_file", f"{step}.py")
    messages.append({"role": "user", "content": "FINALIZATION: inspect diff and submit"})
    sent = HistoryManager(max_messages=6).prompt_messages(messages)
    assert sent[-3:] == messages[-3:]
    assert len(sent) <= 6


def test_tiny_budget_rejects_orphaned_latest_observation():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    messages += tool_turn("read_file", "file.py")
    with pytest.raises(ValueError, match="latest complete turn"):
        HistoryManager(max_messages=3).prompt_messages(messages)


def test_evidence_requires_a_successful_executed_read():
    messages = [
        {"role": "assistant", "content": "I might inspect imaginary.py"},
        {"role": "user", "content": "not executed"},
    ]
    messages += tool_turn("read_file", "missing.py", 2, "File not found")
    messages += tool_turn("read_file", "real.py", 0, "raise ValueError('failed')")
    note = HistoryManager().evidence_note(messages)
    assert "imaginary.py" not in note
    assert "Read missing.py" not in note
    assert "step 2, nonzero exit 2" in note
    assert "step 3: Read real.py" in note
    assert "nonzero exit 0" not in note


def test_later_success_clears_failure_and_updates_file_state():
    messages = tool_turn("read_file", "src/app.py", 2, "missing")
    messages += tool_turn("read_file", "/testbed/src/app.py", 0, "source")
    messages += tool_turn("replace", "src/app.py", 0, "replaced")
    note = HistoryManager().evidence_note(messages)
    assert "nonzero exit" not in note
    assert "Read src/app.py" not in note
    assert "step 3: Modified src/app.py; earlier reads may be stale" in note


def test_summary_does_not_reintroduce_failure_resolved_in_recent_turn():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    messages += tool_turn("read_file", "app.py", 2, "missing")
    messages += tool_turn("read_file", "app.py", 0, "source")
    sent = HistoryManager(max_messages=5).prompt_messages(messages)
    summary = next(m["content"] for m in sent if m["content"].startswith("[memory]"))
    assert "missing" not in summary
    assert "nonzero exit" not in summary


def test_evidence_retains_latest_reads_and_selection_scope():
    messages = []
    for step in range(7):
        messages += tool_turn("refined_read_file", f"file{step}.py", selector={"head": 20})
    note = HistoryManager().evidence_note(messages)
    assert "file0.py" not in note
    assert "file1.py" not in note
    assert 'step 7: Read file6.py, selector={"head": 20}' in note


def test_unrelated_success_on_same_file_does_not_clear_failed_operation():
    messages = tool_turn("search_file_content", "app.py", 1, "failed search", pattern="first")
    messages += tool_turn("search_file_content", "app.py", 0, "found", pattern="different")
    assert "step 1, nonzero exit 1" in HistoryManager().evidence_note(messages)


def test_unknown_tool_named_bash_does_not_break_memory():
    messages = tool_turn("bash", "app.py", 127, "Unknown tool: bash")
    assert "nonzero exit 127" in HistoryManager().evidence_note(messages)


def test_omitted_file_read_keeps_output_excerpt():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    messages.append({"role": "assistant", "content": "```bash\nsed -n '60,110p' django/urls/resolvers.py\n```"})
    messages.append(
        {
            "role": "user",
            "content": "<returncode>0</returncode>\n<output>\ndef get_resolver():\n    UNIQUE_MARKER\n</output>",
        }
    )
    for step in range(4):
        messages += tool_turn("read_file", f"other{step}.py", 0, "x")
    sent = HistoryManager(max_messages=8).prompt_messages(messages)
    summary = next(message["content"] for message in sent if message["content"].startswith("[memory]"))
    assert "django/urls/resolvers.py" in summary
    assert "UNIQUE_MARKER" in summary


def bash_turn(command, output="ok"):
    return [
        {"role": "assistant", "content": "```bash\n" + command + "\n```"},
        {"role": "user", "content": output, "extra": {"returncode": 0}},
    ]


def test_current_task_survives_session_continuation_compression():
    # Continuing a loaded session appends the new task after the old task's turns;
    # compression must pin the new task, not the first user message it finds.
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "OLD_TASK"}]
    for i in range(4):
        messages += bash_turn(f"echo old{i}")
    messages.append({"role": "user", "content": "NEW_TASK_KEEP_ME"})
    for i in range(4):
        messages += bash_turn(f"echo new{i}")
    sent = HistoryManager(max_messages=8).prompt_messages(messages)
    assert any("NEW_TASK_KEEP_ME" in m["content"] for m in sent)


def test_bash_edit_marks_prior_read_stale():
    # bash is the main execution path: a sed -i edit must drop the earlier cat
    # excerpt as stale instead of feeding outdated source back to the model.
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    messages += bash_turn("cat app.py", "OLD_SOURCE_VERSION")
    messages += bash_turn("sed -i 's/OLD_SOURCE_VERSION/NEW_SOURCE_VERSION/' app.py", "")
    for i in range(4):
        messages += bash_turn(f"echo filler{i}")
    sent = HistoryManager(max_messages=6).prompt_messages(messages)
    summary = next(m["content"] for m in sent if m["content"].startswith("[memory]"))
    assert "OLD_SOURCE_VERSION" not in summary
    assert "Modified app.py via bash; earlier reads may be stale" in summary


def test_git_patch_style_edit_expires_all_earlier_reads():
    # Writes with unknown targets (git apply, heredocs) must conservatively drop
    # every earlier read instead of keeping possibly outdated excerpts.
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    messages += bash_turn("cat app.py", "UNIQUE_READ_MARKER")
    messages += bash_turn("git apply fix.patch", "")
    messages += bash_turn("cat other.py", "OTHER_READ_MARKER")
    note = HistoryManager().evidence_note(messages)
    assert "UNIQUE_READ_MARKER" not in note
    assert "unknown targets" in note
    # Reads after the edit survive.
    assert "OTHER_READ_MARKER" in note


def test_token_policies_share_a_limit_and_keep_different_history():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "TASK-KEEP"}]
    messages += [
        {"role": "assistant", "content": "```bash\necho old\n```"},
        {"role": "user", "content": "DROPME " + ("x" * 400), "extra": {"returncode": 0}},
    ]
    for step in range(4):
        messages += [
            {"role": "assistant", "content": f"```bash\necho {step}\n```"},
            {"role": "user", "content": "y" * 400, "extra": {"returncode": 0}},
        ]
    limit = estimate_tokens([messages[0], messages[1], messages[-2], messages[-1]]) + 40
    original = copy.deepcopy(messages)
    truncated = HistoryManager().fit(messages, policy="truncate", token_limit=limit)
    compressed = HistoryManager().fit(messages, policy="compress", token_limit=limit)
    assert estimate_tokens(truncated) <= limit
    assert estimate_tokens(compressed) <= limit
    # Both policies pin the task: losing the goal is not the memory treatment.
    assert any(message["content"] == "TASK-KEEP" for message in truncated)
    assert any(message["content"] == "TASK-KEEP" for message in compressed)
    # Only the compress arm carries summarized evidence of what it dropped.
    assert not any(message["content"].startswith("[memory]") for message in truncated)
    assert any(message["content"].startswith("[memory]") for message in compressed)
    assert "DROPME" not in "".join(message["content"] for message in compressed)
    assert messages == original


def test_truncate_pins_the_task_when_the_limit_binds():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "TASK-STATEMENT"}]
    for step in range(8):
        messages += [
            {"role": "assistant", "content": f"```bash\necho {step}\n```"},
            {"role": "user", "content": "y" * 400, "extra": {"returncode": 0}},
        ]
    for policy in ("truncate", "compress"):
        sent = HistoryManager().fit(messages, policy=policy, token_limit=250)
        assert estimate_tokens(sent) <= 250
        assert any(message["content"] == "TASK-STATEMENT" for message in sent)


def test_compress_keeps_the_latest_action_when_one_turn_exceeds_the_budget():
    # A single file dump larger than the whole budget must not erase the agent's own
    # last action, which is exactly what the truncate arm would still show.
    messages = [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "task"},
        {"role": "assistant", "content": "```bash\ncat big.log\n```"},
        {"role": "user", "content": "Z" * 20000, "extra": {"returncode": 0}},
    ]
    sent = HistoryManager().fit(messages, policy="compress", token_limit=200)
    assert estimate_tokens(sent) <= 200
    assert any("cat big.log" in message["content"] for message in sent)
    assert sent[-1]["role"] == "user"
    assert "truncated to the token limit" in sent[-1]["content"]


def test_bash_read_and_tool_write_name_the_same_file():
    messages = bash_turn("cat /testbed/src/app.py", "STALE_SOURCE")
    messages += tool_turn("replace", "src/app.py", 0, "replaced")
    note = HistoryManager().evidence_note(messages)
    assert "STALE_SOURCE" not in note
    assert "Modified src/app.py" in note


def test_scoped_heredoc_write_is_not_a_read_and_only_touches_its_target():
    messages = bash_turn("cat app.py", "UNIQUE_SOURCE")
    messages += bash_turn("cat > repro.py <<'EOF'\nprint(1)\nEOF", "")
    note = HistoryManager().evidence_note(messages)
    assert "Read" not in note  # A heredoc is a write, never evidence about the heredoc body.
    assert "UNIQUE_SOURCE" in note  # But it only wrote repro.py.
    assert "Modified repro.py" in note


def test_interpreter_heredoc_expires_every_earlier_read():
    messages = bash_turn("cat app.py", "UNIQUE_SOURCE")
    messages += bash_turn("python - <<'EOF'\nopen('app.py', 'w')\nEOF", "")
    note = HistoryManager().evidence_note(messages)
    assert "UNIQUE_SOURCE" not in note
    assert "unknown targets" in note


def test_token_fit_leaves_short_history_unchanged_and_clips_one_huge_message():
    short = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
    assert HistoryManager().fit(short, policy="truncate", token_limit=8000) == short
    huge = [{"role": "system", "content": "system"}, {"role": "user", "content": "z" * 5000}]
    original = huge[1]["content"]
    for policy in ("truncate", "compress"):
        sent = HistoryManager().fit(huge, policy=policy, token_limit=80)
        assert estimate_tokens(sent) <= 80
    assert huge[1]["content"] == original
