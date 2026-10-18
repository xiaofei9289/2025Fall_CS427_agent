"""The prompt policies: window, summary, summary+search, and the optional full arm.

Every policy builds one ``PromptView`` from the full transcript.  The invariants
are enforced in one place:

* the system prompt and the current task are always present;
* the newest turn is present (clipped only if it alone exceeds the budget);
* history is retained as complete turns, never as orphaned messages;
* the total estimated prompt is at most the shared budget;
* the summary is at most its own budget, and is dropped rather than starving the
  newest turn;
* a retrieval observation larger than its budget is a hard error, not silently
  truncated by the history policy (the tool caps it first).

No policy can read another run, a future message, or the grading feedback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .budget import (
    DEFAULT_RETRIEVAL_TOKENS,
    DEFAULT_SUMMARY_TOKENS,
    DEFAULT_TOTAL_TOKENS,
    MESSAGE_OVERHEAD_TOKENS,
    BudgetError,
    PromptView,
    estimate_message_tokens,
    estimate_tokens,
    fit_text_to_tokens,
    message_text,
)
from .conversation import Conversation, Segment, parse_conversation
from .summary import EvidenceSummary, build_evidence_summary


@dataclass(frozen=True)
class PolicyLimits:
    total_tokens: int = DEFAULT_TOTAL_TOKENS
    summary_tokens: int = DEFAULT_SUMMARY_TOKENS
    retrieval_tokens: int = DEFAULT_RETRIEVAL_TOKENS

    def __post_init__(self) -> None:
        if self.total_tokens <= 0:
            raise ValueError("total_tokens must be positive")
        if self.summary_tokens < 0 or self.retrieval_tokens < 0:
            raise ValueError("component budgets must be non-negative")
        if self.summary_tokens >= self.total_tokens:
            raise ValueError("summary_tokens must leave room for the task and newest turn")
        if self.retrieval_tokens >= self.total_tokens:
            raise ValueError("retrieval_tokens must leave room for the task and newest turn")


@dataclass(frozen=True)
class _Latest:
    messages: list[dict[str, Any]]
    indices: tuple[int, ...]
    tokens: int
    clipped: bool
    dropped_indices: tuple[int, ...]


def _copy_message(message: dict[str, Any], content: str, *, clipped: bool = False) -> dict[str, Any]:
    copy = dict(message)
    copy["content"] = content
    extra = dict(copy.get("extra") or {})
    if clipped:
        extra["clipped"] = True
    copy["extra"] = extra
    return copy


def _clip_message(message: dict[str, Any], available: int) -> dict[str, Any]:
    if available <= MESSAGE_OVERHEAD_TOKENS:
        raise BudgetError("no room for a non-empty message")
    content_limit = available - MESSAGE_OVERHEAD_TOKENS
    content = fit_text_to_tokens(message_text(message), content_limit)
    if not content:
        raise BudgetError("message content cannot fit the remaining budget")
    return _copy_message(message, content, clipped=True)


def _fit_latest(segment: Segment, available: int) -> _Latest:
    """Keep the newest action and observation, clipping only the observation."""
    if available <= 0:
        raise BudgetError("the fixed prefix leaves no room for the newest turn")
    tokens = estimate_tokens(list(segment.messages))
    if tokens <= available:
        return _Latest(list(segment.messages), segment.indices, tokens, False, ())

    messages = list(segment.messages)
    indices = list(segment.indices)
    if segment.kind == "loose" or messages[0].get("role") != "assistant":
        last = messages[-1]
        dropped = tuple(indices[:-1])
        clipped = _clip_message(last, available)
        return _Latest([clipped], (indices[-1],), estimate_message_tokens(clipped), True, dropped)

    action = messages[0]
    action_tokens = estimate_message_tokens(action)
    if action_tokens >= available:
        # A malformed or runaway model response can be larger than the whole
        # remaining budget.  Treat it as clipped history instead of a fatal
        # budget error: the next model call still gets the task and can recover.
        try:
            clipped_action = _clip_message(action, available)
        except BudgetError:
            return _Latest([], (), 0, True, tuple(indices))
        return _Latest(
            [clipped_action],
            (indices[0],),
            estimate_message_tokens(clipped_action),
            True,
            tuple(indices[1:]),
        )
    users = [index for index, message in enumerate(messages) if message.get("role") == "user"]
    if not users:
        return _Latest([action], (indices[0],), action_tokens, True, tuple(indices[1:]))

    last_user = users[-1]
    observation = messages[last_user]
    available_for_observation = available - action_tokens
    if available_for_observation <= MESSAGE_OVERHEAD_TOKENS:
        return _Latest(
            [action],
            (indices[0],),
            action_tokens,
            True,
            tuple(indices[1:]),
        )
    try:
        clipped_observation = _clip_message(observation, available_for_observation)
    except BudgetError:
        # There is room for the action but not for a non-empty observation.
        return _Latest([action], (indices[0],), action_tokens, True, tuple(indices[1:]))
    clipped_messages = [action, clipped_observation]
    clipped_indices = (indices[0], indices[last_user])
    dropped = tuple(index for position, index in enumerate(indices) if position not in {0, last_user})
    return _Latest(
        clipped_messages,
        clipped_indices,
        estimate_tokens(clipped_messages),
        True,
        dropped,
    )


def _as_segment(latest: _Latest) -> Segment | None:
    """Represent the latest turn as a Segment for the invalidation pass."""
    if not latest.messages:
        return None
    kind = "turn" if latest.messages[0].get("role") == "assistant" else "loose"
    return Segment(kind=kind, indices=latest.indices, messages=tuple(latest.messages))


def _retrieval_tokens(message: dict[str, Any]) -> int:
    extra = message.get("extra")
    if not isinstance(extra, dict):
        return 0
    value = extra.get("retrieval_tokens", 0)
    return int(value) if isinstance(value, int) and value > 0 else 0


class MemoryPolicy:
    """Base class for the memory policies."""

    name = "base"
    include_summary = False

    def __init__(self, limits: PolicyLimits | None = None):
        self.limits = limits or PolicyLimits()

    def build(self, messages: list[dict[str, Any]]) -> PromptView:
        raise NotImplementedError

    # -- shared construction ------------------------------------------------

    def _pinned(self, conversation: Conversation, messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], tuple[int, ...], int]:
        indices = tuple(sorted(set(conversation.system_indices + (conversation.task_index,))))
        pinned = [messages[index] for index in indices]
        return pinned, indices, estimate_tokens(pinned)

    def _summary(
        self,
        segments: list[Segment],
        conversation: Conversation,
        cap: int,
        *,
        later_segments: list[Segment] | tuple[Segment, ...] = (),
    ) -> EvidenceSummary:
        if not self.include_summary or cap <= 0 or not segments:
            return EvidenceSummary(text="", tokens=0, turns=0)
        text_cap = cap - MESSAGE_OVERHEAD_TOKENS
        if text_cap <= 0:
            return EvidenceSummary(text="", tokens=0, turns=0)
        return build_evidence_summary(
            segments,
            conversation.steps,
            token_limit=text_cap,
            later_segments=later_segments,
        )

    def _assemble(
        self,
        *,
        messages: list[dict[str, Any]],
        conversation: Conversation,
        pinned: list[dict[str, Any]],
        pinned_indices: tuple[int, ...],
        pinned_tokens: int,
        summary: EvidenceSummary,
        kept: list[Segment],
        latest: _Latest,
        clipped: bool,
    ) -> PromptView:
        summary_message = summary.message() if summary.text else None
        summary_tokens = estimate_message_tokens(summary_message) if summary_message else 0
        kept_indices = tuple(index for segment in kept for index in segment.indices)
        sent_indices = pinned_indices + kept_indices + latest.indices
        sent_set = set(sent_indices)
        dropped = tuple(sorted(index for index in range(len(messages)) if index not in sent_set))
        view = list(pinned)
        if summary_message is not None:
            view.append(summary_message)
        view.extend(messages[index] for index in kept_indices)
        view.extend(latest.messages)
        total = estimate_tokens(view)
        if total > self.limits.total_tokens:
            raise BudgetError(
                f"policy {self.name} produced {total} tokens, over the {self.limits.total_tokens} budget"
            )
        retrieval_per_message = [_retrieval_tokens(message) for message in view]
        over = [tokens for tokens in retrieval_per_message if tokens > self.limits.retrieval_tokens]
        if over:
            raise BudgetError(
                f"a retrieval result is {max(over)} tokens, over the {self.limits.retrieval_tokens} cap"
            )
        retrieval = sum(retrieval_per_message)
        return PromptView(
            messages=view,
            policy=self.name,
            total_tokens=total,
            pinned_tokens=pinned_tokens,
            summary_tokens=summary_tokens,
            retrieval_tokens=retrieval,
            max_retrieval_tokens=max(retrieval_per_message, default=0),
            sent_indices=tuple(sent_indices),
            dropped_indices=tuple(index for index in dropped if index not in conversation.system_indices),
            summary_text=summary.text,
            task_index=conversation.task_index,
            task_present=conversation.task_index in sent_set,
            summary_present=summary_message is not None,
            clipped=clipped or latest.clipped,
        )


class WindowPolicy(MemoryPolicy):
    """A: keep the newest complete turns that fit; no summary, no search."""

    name = "window"

    def build(self, messages: list[dict[str, Any]]) -> PromptView:
        conversation = parse_conversation(messages)
        pinned, pinned_indices, pinned_tokens = self._pinned(conversation, messages)
        segments = list(conversation.segments)
        if not segments:
            return self._assemble(
                messages=messages,
                conversation=conversation,
                pinned=pinned,
                pinned_indices=pinned_indices,
                pinned_tokens=pinned_tokens,
                summary=EvidenceSummary(text="", tokens=0, turns=0),
                kept=[],
                latest=_Latest([], (), 0, False, ()),
                clipped=False,
            )
        available = self.limits.total_tokens - pinned_tokens
        latest = _fit_latest(segments[-1], available)
        remaining = self.limits.total_tokens - pinned_tokens - latest.tokens
        kept: list[Segment] = []
        used = 0
        for segment in reversed(segments[:-1]):
            if used + segment.tokens <= remaining:
                kept.insert(0, segment)
                used += segment.tokens
            else:
                break
        return self._assemble(
            messages=messages,
            conversation=conversation,
            pinned=pinned,
            pinned_indices=pinned_indices,
            pinned_tokens=pinned_tokens,
            summary=EvidenceSummary(text="", tokens=0, turns=0),
            kept=kept,
            latest=latest,
            clipped=False,
        )


class SummaryPolicy(MemoryPolicy):
    """B: keep a bounded evidence summary of the dropped turns, plus the window."""

    name = "summary"
    include_summary = True

    def _build_summary_view(
        self,
        *,
        messages: list[dict[str, Any]],
        conversation: Conversation,
        pinned: list[dict[str, Any]],
        pinned_indices: tuple[int, ...],
        pinned_tokens: int,
        latest: _Latest,
        older: list[Segment],
    ) -> PromptView:
        remaining = self.limits.total_tokens - pinned_tokens - latest.tokens
        summary_cap = min(self.limits.summary_tokens, remaining)
        kept: list[Segment] = []
        used = 0
        summary = EvidenceSummary(text="", tokens=0, turns=0)
        latest_segment = _as_segment(latest)

        def later_from(index: int) -> list[Segment]:
            return list(older[index:]) + ([latest_segment] if latest_segment is not None else [])

        for index in range(len(older) - 1, -1, -1):
            candidate_summary = self._summary(
                older[:index],
                conversation,
                summary_cap,
                later_segments=later_from(index),
            )
            candidate_used = used + older[index].tokens
            candidate_total = pinned_tokens + latest.tokens + candidate_summary.tokens + MESSAGE_OVERHEAD_TOKENS * bool(candidate_summary.text) + candidate_used
            if candidate_total <= self.limits.total_tokens:
                kept.insert(0, older[index])
                used = candidate_used
                summary = candidate_summary
            else:
                break

        if not kept:
            summary = self._summary(
                older,
                conversation,
                summary_cap,
                later_segments=[latest_segment] if latest_segment is not None else [],
            )
        # If the summary was dropped by the cap, recompute with no summary so the
        # view remains legal; this only happens for pathological component limits.
        if pinned_tokens + latest.tokens + used + (summary.tokens + MESSAGE_OVERHEAD_TOKENS if summary.text else 0) > self.limits.total_tokens:
            summary = EvidenceSummary(text="", tokens=0, turns=0)
            kept = []
            used = 0
            for segment in reversed(older):
                if used + segment.tokens <= remaining:
                    kept.insert(0, segment)
                    used += segment.tokens
                else:
                    break

        return self._assemble(
            messages=messages,
            conversation=conversation,
            pinned=pinned,
            pinned_indices=pinned_indices,
            pinned_tokens=pinned_tokens,
            summary=summary,
            kept=kept,
            latest=latest,
            clipped=False,
        )

    def build(self, messages: list[dict[str, Any]]) -> PromptView:
        conversation = parse_conversation(messages)
        pinned, pinned_indices, pinned_tokens = self._pinned(conversation, messages)
        segments = list(conversation.segments)
        if not segments:
            return self._assemble(
                messages=messages,
                conversation=conversation,
                pinned=pinned,
                pinned_indices=pinned_indices,
                pinned_tokens=pinned_tokens,
                summary=EvidenceSummary(text="", tokens=0, turns=0),
                kept=[],
                latest=_Latest([], (), 0, False, ()),
                clipped=False,
            )
        available = self.limits.total_tokens - pinned_tokens
        latest = _fit_latest(segments[-1], available)
        return self._build_summary_view(
            messages=messages,
            conversation=conversation,
            pinned=pinned,
            pinned_indices=pinned_indices,
            pinned_tokens=pinned_tokens,
            latest=latest,
            older=segments[:-1],
        )


class SummarySearchPolicy(SummaryPolicy):
    """C: the summary policy plus access to the current run's transcript."""

    name = "summary_search"


class FullPolicy(MemoryPolicy):
    """No compression: send the complete transcript.

    This is not part of the pre-registered A/B/C contrast.  It exists for a
    separate product question ("is compression worth it at all?") and therefore
    deliberately does not enforce ``total_tokens``.  The trace records
    ``budget_enforced=false`` so an analysis cannot mistake it for a budget
    violation.
    """

    name = "full"
    enforces_budget = False

    def build(self, messages: list[dict[str, Any]]) -> PromptView:
        conversation = parse_conversation(messages)
        pinned_indices = tuple(sorted(set(conversation.system_indices + (conversation.task_index,))))
        pinned = [messages[index] for index in pinned_indices]
        sent_indices = tuple(range(len(messages)))
        return PromptView(
            messages=list(messages),
            policy=self.name,
            total_tokens=estimate_tokens(messages),
            pinned_tokens=estimate_tokens(pinned),
            summary_tokens=0,
            retrieval_tokens=0,
            max_retrieval_tokens=0,
            sent_indices=sent_indices,
            dropped_indices=(),
            summary_text="",
            task_index=conversation.task_index,
            task_present=True,
            summary_present=False,
            clipped=False,
            budget_enforced=False,
        )


def build_policy(name: str, limits: PolicyLimits | None = None) -> MemoryPolicy:
    policies = {
        "window": WindowPolicy,
        "summary": SummaryPolicy,
        "summary_search": SummarySearchPolicy,
        "full": FullPolicy,
    }
    try:
        return policies[name](limits)
    except KeyError as error:
        raise ValueError(f"unknown memory policy: {name!r}; choose from {sorted(policies)}") from error
