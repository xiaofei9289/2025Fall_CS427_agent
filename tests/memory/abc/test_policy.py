from __future__ import annotations

import pytest

from minisweagent.memory.abc.budget import BudgetError, estimate_tokens
from minisweagent.memory.abc.policy import PolicyLimits, build_policy


def transcript(turns=12, observation_chars=700):
    messages = [
        {"role": "system", "content": "SYSTEM " * 40, "extra": {"kind": "system"}},
        {"role": "user", "content": "TASK STATEMENT " * 30, "extra": {"kind": "task"}},
    ]
    for index in range(turns):
        messages.append({"role": "assistant", "content": f"```bash\ncat src/file{index}.py\n```"})
        messages.append(
            {
                "role": "user",
                "content": f"Observation: <returncode>0</returncode><output>{'x' * observation_chars}</output>",
                "extra": {"kind": "observation", "returncode": 0},
            }
        )
    return messages


def kinds(view):
    return [message.get("extra", {}).get("kind") for message in view.messages]


def assert_no_orphans(view):
    messages = view.messages
    tags = kinds(view)
    for index, message in enumerate(messages):
        role = message.get("role")
        tag = tags[index]
        if role == "user" and tag not in {"task", "summary", "feedback", "terminal"}:
            assert index > 0 and messages[index - 1].get("role") == "assistant", (
                f"observation at {index} has no action before it: {[m.get('role') for m in messages]}"
            )
        if role == "assistant":
            assert index + 1 < len(messages) and messages[index + 1].get("role") == "user", (
                f"action at {index} has no observation after it"
            )


def test_window_keeps_task_and_complete_turns():
    messages = transcript()
    policy = build_policy("window", PolicyLimits(total_tokens=1400, summary_tokens=300, retrieval_tokens=300))
    view = policy.build(messages)
    assert view.total_tokens <= 1400
    assert view.task_present
    assert not view.summary_present
    assert view.summary_tokens == 0
    assert_no_orphans(view)
    assert any("TASK STATEMENT" in message["content"] for message in view.messages)


def test_summary_contains_omitted_evidence_and_respects_caps():
    messages = transcript()
    policy = build_policy("summary", PolicyLimits(total_tokens=1400, summary_tokens=300, retrieval_tokens=300))
    view = policy.build(messages)
    assert view.total_tokens <= 1400
    assert view.task_present
    assert view.summary_present
    assert view.summary_tokens <= 300
    assert view.summary_text.startswith("[memory]")
    assert view.dropped_indices
    assert_no_orphans(view)


def test_summary_and_summary_search_build_the_same_prompt():
    messages = transcript()
    limits = PolicyLimits(total_tokens=1600, summary_tokens=250, retrieval_tokens=200)
    summary = build_policy("summary", limits).build(messages)
    search = build_policy("summary_search", limits).build(messages)
    assert summary.messages == search.messages
    assert summary.total_tokens == search.total_tokens
    assert summary.summary_text == search.summary_text


def test_latest_turn_is_clipped_only_when_it_cannot_fit():
    messages = transcript(turns=2)
    messages[-1]["content"] = "Observation: <returncode>0</returncode><output>" + "Z" * 20000 + "</output>"
    policy = build_policy("window", PolicyLimits(total_tokens=1000, summary_tokens=200, retrieval_tokens=200))
    view = policy.build(messages)
    assert view.total_tokens <= 1000
    assert view.clipped
    assert view.task_present
    assert "cat src/file1.py" in view.messages[-2]["content"]
    assert "truncated" in view.messages[-1]["content"]


def test_oversized_action_is_clipped_instead_of_fatal():
    messages = transcript(turns=2)
    messages[-2]["content"] = "```bash\n" + "A" * 20000 + "\n```"
    view = build_policy("window", PolicyLimits(total_tokens=1000, summary_tokens=200, retrieval_tokens=200)).build(messages)
    assert view.total_tokens <= 1000
    assert view.clipped
    assert view.task_present
    assert len(view.messages[-1]["content"]) < 20000


def test_task_is_pinned_even_when_the_budget_binds():
    messages = transcript()
    view = build_policy("window", PolicyLimits(total_tokens=500, summary_tokens=100, retrieval_tokens=100)).build(messages)
    assert view.task_present
    assert any("TASK STATEMENT" in message["content"] for message in view.messages)
    assert view.total_tokens <= 500


def test_budget_error_when_the_task_itself_cannot_fit():
    messages = transcript(turns=1)
    messages[1]["content"] = "T" * 4000
    with pytest.raises(BudgetError):
        build_policy("window", PolicyLimits(total_tokens=100, summary_tokens=10, retrieval_tokens=10)).build(messages)


def test_retrieval_over_cap_is_a_hard_error():
    messages = transcript(turns=2)
    messages[-1]["extra"]["retrieval_tokens"] = 500
    with pytest.raises(BudgetError, match="retrieval"):
        build_policy("summary_search", PolicyLimits(total_tokens=8000, summary_tokens=1000, retrieval_tokens=300)).build(messages)


def test_summary_budget_is_a_hard_cap_at_large_scale():
    messages = transcript(turns=30, observation_chars=1500)
    policy = build_policy("summary", PolicyLimits(total_tokens=8000, summary_tokens=100, retrieval_tokens=1500))
    view = policy.build(messages)
    assert view.total_tokens <= 8000
    assert view.summary_tokens <= 100
    assert view.summary_text


def test_dropped_messages_are_not_in_the_sent_indices():
    messages = transcript()
    view = build_policy("summary", PolicyLimits(total_tokens=1500, summary_tokens=300, retrieval_tokens=300)).build(messages)
    assert set(view.sent_indices).isdisjoint(view.dropped_indices)
    assert len(view.sent_indices) + len(view.dropped_indices) == len(messages)
    assert estimate_tokens(view.messages) == view.total_tokens


def test_summary_is_invalidated_by_a_write_in_the_retained_window():
    def message(action, observation):
        return [
            {"role": "assistant", "content": action},
            {
                "role": "user",
                "content": f"<returncode>0</returncode><output>{observation}{'x' * 80}</output>",
                "extra": {"kind": "observation", "returncode": 0},
            },
        ]

    messages = [
        {"role": "system", "content": "SYSTEM", "extra": {"kind": "system"}},
        {"role": "user", "content": "TASK", "extra": {"kind": "task"}},
    ]
    messages += message("```bash\ncat src/config.py\n```", "OLD_SOURCE")
    for index in range(4):
        messages += message(f"```bash\ncat src/f{index}.py\n```", f"filler {index}")
    messages += message("```bash\nsed -i 's/a/b/' src/config.py\n```", "edited")
    for index in range(2):
        messages += message(f"```bash\ncat src/g{index}.py\n```", f"tail {index}")

    view = build_policy(
        "summary",
        PolicyLimits(total_tokens=300, summary_tokens=120, retrieval_tokens=60),
    ).build(messages)
    assert "OLD_SOURCE" not in view.summary_text
    assert "Superseded by later edits:" in view.summary_text
    assert "modified src/config.py after the summarized read" in view.summary_text


def test_full_policy_sends_every_message_and_does_not_enforce_the_budget():
    messages = transcript()
    view = build_policy(
        "full",
        PolicyLimits(total_tokens=100, summary_tokens=10, retrieval_tokens=10),
    ).build(messages)
    assert view.policy == "full"
    assert view.sent_indices == tuple(range(len(messages)))
    assert view.dropped_indices == ()
    assert view.total_tokens == estimate_tokens(messages)
    assert view.total_tokens > 100
    assert view.budget_enforced is False
    assert view.summary_present is False
