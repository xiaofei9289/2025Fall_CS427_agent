"""Offline replay of a transcript through a memory policy.

This makes no model or environment calls.  For every assistant action it builds
the view the policy would have sent, then classifies each earlier successful
read as fully visible, summarized, or lost.  It also counts *recovery re-reads*:
a read of a path whose previous read is no longer fully visible and where no
write to that path intervened.  That is the cheapest deterministic proxy for
"the model lost evidence and had to spend a step to get it back".

The replay is deliberately conservative:

* it only counts successful reads (return code 0);
* a write to the path between two reads makes the second read legitimate, not a
  recovery read;
* a read that is present in the view but is a clipped latest observation is
  counted as visible; clipping is reported separately by the policy trace.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .budget import message_text
from .conversation import parse_conversation
from .policy import MemoryPolicy
from .summary import _normalize, _parse_action, _read_paths, _write_targets

_RETURN_RE = re.compile(r"<returncode>(-?\d+)</returncode>")
_READ_TOOLS = {"read_file", "refined_read_file"}


@dataclass
class ReadEvent:
    step: int
    action_index: int
    observation_index: int
    path: str


@dataclass
class ReplayStats:
    calls: int = 0
    view_errors: int = 0
    read_events: int = 0
    write_events: int = 0
    repeat_reads: int = 0
    recovery_reads: int = 0
    summary_recovery_reads: int = 0
    lost_recovery_reads: int = 0
    full_read_exposures: int = 0
    summary_read_exposures: int = 0
    lost_read_exposures: int = 0

    @property
    def read_exposures(self) -> int:
        return self.full_read_exposures + self.summary_read_exposures + self.lost_read_exposures

    def as_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "view_errors": self.view_errors,
            "read_events": self.read_events,
            "write_events": self.write_events,
            "repeat_reads": self.repeat_reads,
            "recovery_reads": self.recovery_reads,
            "summary_recovery_reads": self.summary_recovery_reads,
            "lost_recovery_reads": self.lost_recovery_reads,
            "read_exposures": self.read_exposures,
            "full_read_exposures": self.full_read_exposures,
            "summary_read_exposures": self.summary_read_exposures,
            "lost_read_exposures": self.lost_read_exposures,
        }


def _observation(messages: list[dict[str, Any]], index: int) -> tuple[str, int | None, int | None]:
    """Return the observation text, return code, and message index for an action."""
    cursor = index + 1
    users: list[tuple[int, dict[str, Any]]] = []
    while cursor < len(messages) and messages[cursor].get("role") == "user":
        users.append((cursor, messages[cursor]))
        cursor += 1
    if not users:
        return "", None, None
    observations = [
        (number, message)
        for number, message in users
        if isinstance(message.get("extra"), dict) and message["extra"].get("kind") == "observation"
    ]
    number, message = (observations or users)[-1]
    text = message_text(message)
    extra = message.get("extra") if isinstance(message.get("extra"), dict) else {}
    code = extra.get("returncode")
    if not isinstance(code, int):
        match = _RETURN_RE.search(text)
        code = int(match.group(1)) if match else None
    return text, code, number


def _read_paths_for(kind: str, name: str, args: dict[str, Any]) -> list[str]:
    if kind == "tool":
        if name in _READ_TOOLS:
            path = _normalize(str(args.get("path", "")))
            return [path] if path else []
        if name == "read_many_files":
            paths = args.get("paths")
            if isinstance(paths, list):
                return [path for path in (_normalize(str(item)) for item in paths) if path]
        return []
    paths = _read_paths(str(args.get("command", "")).strip()) or []
    return [path for path in (_normalize(item) for item in paths) if path]


def _write_paths_for(kind: str, name: str, args: dict[str, Any]) -> tuple[list[str], bool]:
    if kind == "tool":
        if name not in {"write_file", "replace"}:
            return [], False
        path = _normalize(str(args.get("path", "")))
        return ([path] if path else []), not path
    targets, unknown = _write_targets(str(args.get("command", "")).strip())
    return [path for path in (_normalize(item) for item in targets) if path], unknown


def _state(event: ReadEvent, view: Any) -> str:
    if event.observation_index in view.sent_indices:
        return "full"
    if f"step {event.step}:" in view.summary_text and event.path in view.summary_text:
        return "summary"
    return "lost"


def replay_transcript(messages: list[dict[str, Any]], policy: MemoryPolicy) -> ReplayStats:
    """Replay ``messages`` through ``policy`` and return deterministic counters.

    A malformed transcript raises ``ConversationError``; the caller may record
    that as an analysis error.  Individual views that cannot be built (for
    example a budget error on an unusually large prefix) increment
    ``view_errors`` instead of aborting the replay.
    """
    conversation = parse_conversation(messages)
    steps = conversation.steps
    stats = ReplayStats()

    views: dict[int, Any] = {}
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        try:
            views[index] = policy.build(messages[:index])
        except Exception:  # noqa: BLE001 - a replay is diagnostic, not a run
            stats.view_errors += 1
    stats.calls = len(views)

    reads: list[ReadEvent] = []
    last_read: dict[str, ReadEvent] = {}
    last_write: dict[str, int] = {}
    unknown_write = 0

    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        parsed = _parse_action(message)
        if parsed is None:
            continue
        kind, name, args = parsed
        step = steps.get(index, 0)
        text, code, observation_index = _observation(messages, index)
        write_paths, write_unknown = _write_paths_for(kind, name, args)
        if code == 0:
            for path in write_paths:
                last_write[path] = max(last_write.get(path, 0), step)
                stats.write_events += 1
            if write_unknown:
                unknown_write = max(unknown_write, step)
                stats.write_events += 1

        read_paths = _read_paths_for(kind, name, args)
        if code != 0 or not read_paths:
            continue
        if observation_index is None:
            continue
        view = views.get(index)
        for path in read_paths:
            event = ReadEvent(
                step=step,
                action_index=index,
                observation_index=observation_index,
                path=path,
            )
            prior = last_read.get(path)
            if prior is not None:
                wrote = last_write.get(path, 0) > prior.step or unknown_write > prior.step
                if not wrote:
                    stats.repeat_reads += 1
                    if view is not None:
                        state = _state(prior, view)
                        if state != "full":
                            stats.recovery_reads += 1
                            if state == "summary":
                                stats.summary_recovery_reads += 1
                            else:
                                stats.lost_recovery_reads += 1
            # Exposure is about the current evidence, not every historical
            # read: a re-read replaces the older observation of the same path.
            reads = [prior for prior in reads if prior.path != path]
            reads.append(event)
            last_read[path] = event
            stats.read_events += 1

            if view is None:
                continue
            # Exposure counts only reads that are still current (no later write
            # to the same path), so the denominator is "evidence the model could
            # still use", not every read ever made.
            for earlier in reads:
                if earlier is event:
                    continue
                if last_write.get(earlier.path, 0) > earlier.step or unknown_write > earlier.step:
                    continue
                state = _state(earlier, view)
                if state == "full":
                    stats.full_read_exposures += 1
                elif state == "summary":
                    stats.summary_read_exposures += 1
                else:
                    stats.lost_read_exposures += 1
    return stats
