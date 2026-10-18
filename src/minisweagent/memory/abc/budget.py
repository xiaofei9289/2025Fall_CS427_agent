"""Shared prompt-budget accounting for the A/B/C memory experiment.

The estimator is deliberately simple and shared by every arm: four characters
per token plus a fixed per-message overhead.  It is an estimate, not a
tokenizer.  The experiment records the provider's ``usage.prompt_tokens`` next
to it so the report can state the calibration factor; no arm gets a different
estimator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_TOTAL_TOKENS = 8000
DEFAULT_SUMMARY_TOKENS = 1000
DEFAULT_RETRIEVAL_TOKENS = 1500

# Role markers, JSON quotes, and chat-template separators are not free.  A flat
# four-token allowance per message keeps the estimate slightly conservative.
MESSAGE_OVERHEAD_TOKENS = 4


def message_text(message: dict[str, Any]) -> str:
    """Return the textual content of a message without assuming it is a string."""
    content = message.get("content", "")
    return content if isinstance(content, str) else str(content)


def estimate_text_tokens(text: str) -> int:
    """Estimate tokens in a string as ``ceil(characters / 4)``."""
    if not text:
        return 0
    return (len(text) + 3) // 4


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate one message, including the fixed role/format overhead."""
    return estimate_text_tokens(message_text(message)) + MESSAGE_OVERHEAD_TOKENS


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate the prompt tokens of a message list with the shared estimator."""
    return sum(estimate_message_tokens(message) for message in messages)


class BudgetError(ValueError):
    """The fixed prefix and the newest turn cannot be made to fit the budget.

    This is a hard error rather than a silent fallback: dropping the task or the
    agent's own last action is a goal failure, not a memory policy.
    """


@dataclass
class PromptView:
    """The exact prompt sent to the model, plus auditable accounting.

    ``sent_indices`` indexes the real messages in the agent's full transcript.
    The evidence summary, when present, is synthetic and is not in that list;
    its text is carried separately in ``summary_text``.
    """

    messages: list[dict[str, Any]]
    policy: str
    total_tokens: int
    pinned_tokens: int
    summary_tokens: int
    retrieval_tokens: int
    max_retrieval_tokens: int
    sent_indices: tuple[int, ...]
    dropped_indices: tuple[int, ...]
    summary_text: str
    task_index: int
    task_present: bool
    summary_present: bool
    clipped: bool

    def metadata(self) -> dict[str, Any]:
        """Compact record stored on each assistant message for later analysis."""
        return {
            "policy": self.policy,
            "total_tokens": self.total_tokens,
            "pinned_tokens": self.pinned_tokens,
            "summary_tokens": self.summary_tokens,
            "retrieval_tokens": self.retrieval_tokens,
            "max_retrieval_tokens": self.max_retrieval_tokens,
            "sent_messages": len(self.sent_indices),
            "dropped_messages": len(self.dropped_indices),
            "summary_present": self.summary_present,
            "task_present": self.task_present,
            "clipped": self.clipped,
        }


def fit_text_to_tokens(text: str, limit: int, *, note: str = "\n[truncated to fit the memory budget]") -> str:
    """Shorten ``text`` until its estimate fits ``limit``, keeping a visible note.

    The binary search is over characters; it is deterministic and never returns
    a string whose estimate exceeds the limit (unless the note alone does, in
    which case the note is clipped too).
    """
    if limit <= 0:
        return ""
    if estimate_text_tokens(text) <= limit:
        return text
    if estimate_text_tokens(note) >= limit:
        return fit_text_to_tokens(note, limit, note="")

    lo, hi, best = 0, len(text), 0
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = text[:mid] + note
        if estimate_text_tokens(candidate) <= limit:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return text[:best] + note
