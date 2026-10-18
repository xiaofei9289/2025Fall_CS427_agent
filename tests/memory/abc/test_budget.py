from __future__ import annotations

from minisweagent.memory.abc.budget import (
    BudgetError,
    PromptView,
    estimate_message_tokens,
    estimate_text_tokens,
    estimate_tokens,
    fit_text_to_tokens,
    message_text,
)


def test_estimator_is_character_based_with_message_overhead():
    assert estimate_text_tokens("") == 0
    assert estimate_text_tokens("a") == 1
    assert estimate_text_tokens("abcd") == 1
    assert estimate_text_tokens("abcde") == 2
    assert estimate_message_tokens({"role": "user", "content": "abcd"}) == 5
    assert estimate_tokens([{"role": "user", "content": "abcd"}, {"role": "system", "content": ""}]) == 9


def test_message_text_handles_non_string_content():
    assert message_text({"role": "user", "content": [{"type": "text"}]}) == "[{'type': 'text'}]"


def test_fit_text_respects_the_limit_and_keeps_a_note():
    text = "x" * 4000
    fitted = fit_text_to_tokens(text, 100)
    assert estimate_text_tokens(fitted) <= 100
    assert "truncated" in fitted
    assert fit_text_to_tokens("short", 100) == "short"


def test_fit_text_zero_limit_is_empty():
    assert fit_text_to_tokens("anything", 0) == ""


def test_prompt_view_metadata_is_compact_and_auditable():
    view = PromptView(
        messages=[],
        policy="summary",
        total_tokens=123,
        pinned_tokens=50,
        summary_tokens=40,
        retrieval_tokens=0,
        max_retrieval_tokens=0,
        sent_indices=(0, 1),
        dropped_indices=(2, 3, 4),
        summary_text="[memory] x",
        task_index=1,
        task_present=True,
        summary_present=True,
        clipped=False,
    )
    metadata = view.metadata()
    assert metadata["policy"] == "summary"
    assert metadata["sent_messages"] == 2
    assert metadata["dropped_messages"] == 3
    assert metadata["task_present"] is True


def test_budget_error_is_a_value_error():
    assert issubclass(BudgetError, ValueError)
