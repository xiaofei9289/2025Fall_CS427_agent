"""Turn-aware view of an agent transcript.

A *turn* is one assistant action followed by every user message that belongs to
it (normally one observation; format-error feedback can add another).  Turns are
the atomic unit of history retention.  Keeping whole turns is what prevents the
"observation whose action was dropped" failure that a message-level sliding
window produces.

The agent tags its own messages in ``extra.kind`` (``task``, ``observation``,
``feedback``, ``terminal``, ``summary``).  The parser has a conservative fallback
for untagged transcripts so it can also inspect older runs, but the experiment
always uses the tagged path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .budget import estimate_tokens, message_text

_FEEDBACK_PREFIXES = (
    "Observation:",
    "FINALIZATION:",
    "The last command",
    "Please always provide",
    "Command not executed",
    "Model response was",
    "Budget exhausted",
)
_NON_TASK_KINDS = {"observation", "feedback", "terminal", "summary"}


class ConversationError(ValueError):
    """The transcript cannot be represented as one task plus complete turns."""


@dataclass(frozen=True)
class Segment:
    """One retained unit: a complete turn, or a loose user message."""

    kind: str  # "turn" | "loose"
    indices: tuple[int, ...]
    messages: tuple[dict[str, Any], ...]

    @property
    def tokens(self) -> int:
        return estimate_tokens(list(self.messages))

    @property
    def first_index(self) -> int:
        return self.indices[0]

    @property
    def last_index(self) -> int:
        return self.indices[-1]


@dataclass(frozen=True)
class Conversation:
    """Pinned messages plus the chronologically ordered, retainable segments."""

    system_indices: tuple[int, ...]
    task_index: int
    segments: tuple[Segment, ...]
    steps: dict[int, int]

    @property
    def pinned_indices(self) -> tuple[int, ...]:
        return self.system_indices + (self.task_index,)

def _kind(message: dict[str, Any]) -> str:
    extra = message.get("extra")
    return str(extra.get("kind", "")) if isinstance(extra, dict) else ""


def _looks_like_task(message: dict[str, Any], previous: dict[str, Any] | None) -> bool:
    """Fallback task detector for untagged transcripts.

    Observations always follow an assistant action; feedback starts with a
    known prefix.  The remaining user message is the task.
    """
    if message.get("role") != "user":
        return False
    if _kind(message) == "task":
        return True
    if _kind(message) in _NON_TASK_KINDS:
        return False
    if previous is not None and previous.get("role") == "assistant":
        return False
    return not message_text(message).startswith(_FEEDBACK_PREFIXES)


def _find_task(messages: list[dict[str, Any]]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if _kind(messages[index]) == "task":
            return index
    for index in range(len(messages) - 1, -1, -1):
        previous = messages[index - 1] if index else None
        if _looks_like_task(messages[index], previous):
            return index
    raise ConversationError("no task message found")


def parse_conversation(messages: list[dict[str, Any]]) -> Conversation:
    """Split ``messages`` into pinned messages and complete retainable segments.

    The supported shape is exactly what one agent run produces: zero or more
    system messages, one task message, then alternating assistant turns and user
    observations.  A second task (continued-session shape) is rejected because
    the experiment deliberately has no cross-run memory.
    """
    if not messages:
        raise ConversationError("empty transcript")

    system_indices = tuple(index for index, message in enumerate(messages) if message.get("role") == "system")
    task_index = _find_task(messages)

    if any(_kind(message) == "task" for index, message in enumerate(messages) if index != task_index):
        raise ConversationError("multiple task messages are not supported")
    before = [index for index in range(task_index) if messages[index].get("role") != "system"]
    if before:
        raise ConversationError("history before the current task is not supported")

    steps: dict[int, int] = {}
    step = 0
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            step += 1
            steps[index] = step

    segments: list[Segment] = []
    index = task_index + 1
    while index < len(messages):
        message = messages[index]
        if message.get("role") == "system":
            # A late system message is pinned like the first one; it is never
            # part of a summarizable turn.
            system_indices = system_indices + (index,)
            index += 1
            continue

        if message.get("role") == "assistant":
            indices = [index]
            index += 1
            while index < len(messages) and messages[index].get("role") == "user":
                if _kind(messages[index]) == "task":
                    raise ConversationError("multiple task messages are not supported")
                indices.append(index)
                index += 1
            segments.append(
                Segment(
                    kind="turn",
                    indices=tuple(indices),
                    messages=tuple(messages[i] for i in indices),
                )
            )
            continue

        # A user message with no preceding assistant is a loose feedback block.
        indices = [index]
        index += 1
        while index < len(messages) and messages[index].get("role") == "user":
            if _kind(messages[index]) == "task":
                raise ConversationError("multiple task messages are not supported")
            indices.append(index)
            index += 1
        segments.append(
            Segment(
                kind="loose",
                indices=tuple(indices),
                messages=tuple(messages[i] for i in indices),
            )
        )

    return Conversation(
        system_indices=tuple(sorted(set(system_indices))),
        task_index=task_index,
        segments=tuple(segments),
        steps=steps,
    )
