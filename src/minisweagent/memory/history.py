"""History management for conversation compression."""

import json
import posixpath
import re
from typing import Any

_RETURN_RE = re.compile(r"<returncode>(-?\d+)</returncode>")
_ACTION_RE = re.compile(r"```(bash|tool)\n(.*?)\n```", re.DOTALL)
_TAG_RE = re.compile(r"</?(?:returncode|output|output_head|output_tail|elided_chars|warning)[^>]*>")

# User messages that are agent feedback rather than a task statement.
_NOT_TASK_PREFIXES = (
    "Observation:",
    "FINALIZATION:",
    "The last command",
    "Please always provide",
    "Command not executed",
    "Model response was",
)


def _current_task_index(messages: list[dict[str, Any]]) -> int | None:
    """Index of the current task: the last user message that is not action feedback.

    Continuing a loaded session appends a new task after the old task's turns, so
    pinning the first user message would drop the current task during compression.
    Observations always follow an assistant action; feedback uses known prefixes.
    """
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("role") != "user":
            continue
        previous = messages[index - 1] if index else None
        content = str(message.get("content", ""))
        if (previous is None or previous.get("role") != "assistant") and not content.startswith(_NOT_TASK_PREFIXES):
            return index
    return next((i for i, m in enumerate(messages) if m.get("role") == "user"), None)


def _segments(command: str) -> list[list[str]]:
    """Split a bash command into ;/&/|-separated segments of tokens."""
    return [tokens for tokens in (segment.split() for segment in re.split(r"[;&|]+", command)) if tokens]


def _head_and_rest(tokens: list[str]) -> tuple[str, list[str]]:
    if tokens[0] == "sudo" and len(tokens) > 1:
        return tokens[1], tokens[2:]
    return tokens[0], tokens[1:]


def _bash_read_paths(command: str) -> list[str] | None:
    """Files printed by a pure read command, or None when it is not a plain read.

    In-place sed counts as a write, not a read, so it must not be recorded as
    source evidence.
    """
    paths: list[str] = []
    for tokens in _segments(command):
        head, rest = _head_and_rest(tokens)
        if head in {"cat", "nl", "head", "tail"}:
            paths.extend(t for t in rest if not t.startswith("-"))
        elif head == "sed" and not any(
            re.fullmatch(r"-[a-zA-Z]*i[a-zA-Z]*(?:\.\w+)?", t) or t == "--in-place" for t in rest
        ):
            positional = [t for t in rest if not t.startswith("-")]
            paths.extend(positional[1:])  # The first positional is the sed script.
    return paths or None


def _bash_write(command: str) -> tuple[set[str], bool]:
    """Return (files a bash command may modify, whether it may write to unknown files).

    Unknown-target writes (patch, git apply, heredocs) conservatively invalidate
    every earlier read; named targets invalidate only their own reads.
    """
    targets: set[str] = set()
    unknown = False
    for tokens in _segments(command):
        head, rest = _head_and_rest(tokens)
        positional = [t for t in rest if not t.startswith("-")]
        if head in {"sed", "perl"} and any(
            re.fullmatch(r"-[a-zA-Z]*i[a-zA-Z]*(?:\.\w+)?", t) or t == "--in-place" for t in rest
        ):
            targets.update(positional[1:])  # Skip the in-place script.
        elif head in {"mv", "rm", "touch"}:
            targets.update(positional)
        elif head in {"tee", "cp", "truncate", "install", "dd"} and positional:
            targets.add(positional[-1])
        elif (
            head in {"patch", "xargs"}
            or head == "find"
            and any(t.startswith("-exec") or t in {"-delete", "-fprint", "-fprintf"} for t in rest)
            or head in {"python", "python3"}
            and ("-c" in rest or "<<-" in rest)
            or head == "git"
            and len(rest) > 1
            and rest[0]
            in {
                "apply",
                "checkout",
                "restore",
                "stash",
                "reset",
                "clean",
                "merge",
                "rebase",
                "cherry-pick",
            }
        ):
            unknown = True
        if "<<" in " ".join(tokens):
            unknown = True
        for index, token in enumerate(tokens):
            redirect = re.match(r"^\d?(>{1,2})(.*)$", token)
            if not redirect or redirect.group(2).startswith("&"):
                continue
            target = redirect.group(2) or (tokens[index + 1] if index + 1 < len(tokens) else "")
            if target and target != "/dev/null":
                targets.add(target)
    return targets, unknown


def _excerpt(text: str, limit: int = 1000) -> str:
    body = " ".join(_TAG_RE.sub(" ", text).split())
    return body[:limit]


def message_text(message: dict[str, Any]) -> str:
    """Return message content as text."""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    return str(content)


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Approximate provider tokens from characters. Both experiment arms use this count."""
    return sum(len(message_text(message)) // 4 + 4 for message in messages)


class HistoryManager:
    """Manages conversation history with compression capabilities."""

    def __init__(self, max_messages: int = 50, keep_system: bool = True):
        """Initialize history manager.

        Args:
            max_messages: Maximum number of messages to keep
            keep_system: Whether to always keep system messages
        """
        self.max_messages = max_messages
        self.keep_system = keep_system

    def compress_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Compress message history by keeping only recent messages.

        Args:
            messages: List of message dictionaries

        Returns:
            Compressed list of messages
        """
        if len(messages) <= self.max_messages:
            return messages

        if not self.keep_system:
            return messages[-self.max_messages :]

        # Keep system messages and most recent user/assistant messages
        system_messages = [msg for msg in messages if msg.get("role") == "system"]
        other_messages = [msg for msg in messages if msg.get("role") != "system"]

        # Calculate how many non-system messages we can keep
        available_slots = max(0, self.max_messages - len(system_messages))
        recent_messages = other_messages[-available_slots:] if available_slots > 0 else []

        # If we have too many system messages, just return the limit
        if len(system_messages) >= self.max_messages:
            return system_messages[: self.max_messages]

        # Combine system messages with recent non-system messages
        return system_messages + recent_messages

    def compress_salient(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Keep the task and a contiguous suffix of complete action/observation turns.

        One summary of omitted execution evidence shares the message budget. Short
        histories are returned unchanged; no evidence is injected before compression.
        """
        if len(messages) <= self.max_messages:
            return messages

        system = [m for m in messages if m.get("role") == "system"] if self.keep_system else []
        task_index = _current_task_index(messages)
        task = [messages[task_index]] if task_index is not None else []
        turns: list[list[tuple[int, dict[str, Any]]]] = []
        for index, message in enumerate(messages):
            if message.get("role") == "system" or index == task_index:
                continue
            if message.get("role") == "assistant" or not turns:
                turns.append([])
            turns[-1].append((index, message))

        prefix = system + task
        budget = self.max_messages - len(prefix)
        if not turns or len(turns[-1]) > budget:
            raise ValueError("memory_max_messages is too small to retain the task and latest complete turn")

        # Prefer complete recent turns over a summary if the newest turn fills the budget.
        remaining = budget - int(budget > len(turns[-1]))
        start = len(turns)
        while start and len(turns[start - 1]) <= remaining:
            start -= 1
            remaining -= len(turns[start])
        recent = [message for turn in turns[start:] for _index, message in turn]
        dropped_count = sum(len(turn) for turn in turns[:start])
        if dropped_count and len(prefix) + len(recent) < self.max_messages:
            note = self.evidence_note(messages, before_index=turns[start][0][0])
            summary = f"[memory] Omitted {dropped_count} earlier messages. Full history remains searchable."
            if note:
                summary += "\n" + note
            return prefix + [{"role": "user", "content": summary}] + recent
        return prefix + recent

    def evidence_note(self, messages: list[dict[str, Any]], *, before_index: int | None = None) -> str:
        """Describe executed tools and pending nonzero exits, with source steps.

        Later successful executions supersede earlier failures. Reads are recorded
        only for successful read tools, never from paths mentioned in model prose.
        Evidence about modified files is dropped as stale: tool writes invalidate
        their own path, bash writes invalidate the files they name, and bash writes
        with unknown targets invalidate every earlier read.
        ``before_index`` limits the summary to evidence actually omitted from view.
        """
        # Each entry is (message index, summary line, files the line is about).
        files: dict[str, tuple[int, str, frozenset[str]]] = {}
        reads: dict[tuple, tuple[int, str, frozenset[str]]] = {}
        failures: dict[tuple, tuple[int, str, frozenset[str]]] = {}
        step = 0
        for index, message in enumerate(messages[:-1]):
            if message.get("role") != "assistant":
                continue
            step += 1
            action = self._action(message)
            observation = messages[index + 1]
            if action is None or observation.get("role") != "user":
                continue
            text = message_text(observation)
            code = observation.get("extra", {}).get("returncode")
            if code is None:
                match = _RETURN_RE.search(text)
                code = int(match.group(1)) if match else None
            if code is None:
                continue
            kind, name, args = action
            path = args.get("path", "")
            path = posixpath.normpath(path.removeprefix("/testbed/")) if isinstance(path, str) and path else ""
            operation = json.dumps({key: value for key, value in args.items() if key != "path"}, sort_keys=True)
            key = (kind, name, path, operation) if kind == "tool" else (kind, args["command"])
            label = f"{name} {path}" if kind == "tool" else args["command"]
            if code != 0:
                output = re.sub(r"</?(?:returncode|output)[^>]*>", " ", text)
                failures.pop(key, None)
                failures[key] = (
                    index + 1,
                    f"- step {step}, nonzero exit {code}, {label[:160]}: " + " ".join(output.split())[:200],
                    frozenset(),
                )
                continue
            failures.pop(key, None)
            if kind == "tool":
                failures.pop((kind, name, "", operation), None)  # Corrected missing-path call.
                excerpt = _excerpt(text)
                if path and name in {"write_file", "replace"}:
                    self._drop_reads(reads, {path})
                    files[path] = (
                        index + 1,
                        f"- step {step}: Modified {path}; earlier reads may be stale",
                        frozenset({path}),
                    )
                elif path and name in {"read_file", "refined_read_file"}:
                    files.pop(path, None)
                    selector = args.get("selector")
                    scope = f", selector={json.dumps(selector, sort_keys=True)}" if selector else ""
                    reads[("tool", path)] = (
                        index + 1,
                        f"- step {step}: Read {path}{scope}\n{excerpt}",
                        frozenset({path}),
                    )
                continue
            excerpt = _excerpt(text)
            if (read_paths := _bash_read_paths(args["command"])) is not None:
                reads[(kind, args["command"])] = (
                    index + 1,
                    f"- step {step}: {args['command'][:160]}\n{excerpt}",
                    frozenset(read_paths),
                )
                continue
            write_targets, unknown_write = _bash_write(args["command"])
            if unknown_write:
                reads.clear()
                reads[("bash-write", step)] = (
                    index + 1,
                    f"- step {step}: bash edits with unknown targets may have modified sources; "
                    "earlier reads were dropped as stale",
                    frozenset(),
                )
            elif write_targets:
                self._drop_reads(reads, write_targets)
                for target in write_targets:
                    files.pop(target, None)
                    files[target] = (
                        index + 1,
                        f"- step {step}: Modified {target} via bash; earlier reads may be stale",
                        frozenset({target}),
                    )

        def omitted(items):
            return [line for index, line, _paths in items if before_index is None or index < before_index]

        lines = (
            omitted(list(files.values()))[-5:]
            + omitted(list(reads.values()))[-4:]
            + omitted(list(failures.values()))[-3:]
        )
        return "\n".join(lines)

    @staticmethod
    def _drop_reads(reads: dict[tuple, tuple[int, str, frozenset[str]]], paths: set[str]) -> None:
        """Remove tool reads and bash reads whose files may have been modified."""
        for key in [key for key, (_index, _line, read_paths) in reads.items() if read_paths & set(paths)]:
            del reads[key]

    def _action(self, message: dict[str, Any]) -> tuple[str, str, dict] | None:
        """Parse only an executable action, excluding paths in reasoning text."""
        blocks = _ACTION_RE.findall(message_text(message))
        if len(blocks) != 1:
            return None
        kind, content = blocks[0]
        if kind == "bash":
            return "bash", "bash", {"command": content.strip()}
        try:
            payload = json.loads(content)
            if isinstance(payload, dict) and isinstance(payload.get("name"), str):
                args = payload.get("args", {})
                if isinstance(args, dict):
                    return "tool", payload["name"], args
        except (ValueError, TypeError):
            pass
        return None

    def prompt_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return the messages actually sent to the model."""
        return self.compress_salient(messages)

    def fit(self, messages: list[dict[str, Any]], *, policy: str, token_limit: int) -> list[dict[str, Any]]:
        """Keep the prompt inside a shared token limit.

        ``truncate`` drops the oldest non-system messages. ``compress`` keeps the
        task and a summary of omitted evidence, then the newest complete turns.
        """
        if token_limit <= 0 or estimate_tokens(messages) <= token_limit:
            return messages
        if policy == "truncate":
            return self.truncate_tokens(messages, token_limit)
        if policy == "compress":
            return self.compress_tokens(messages, token_limit)
        raise ValueError(f"Unknown history policy: {policy}")

    def truncate_tokens(self, messages: list[dict[str, Any]], token_limit: int) -> list[dict[str, Any]]:
        """Drop oldest non-system messages until the estimate fits, then clip the tail."""
        if estimate_tokens(messages) <= token_limit:
            return messages
        system_ids = {id(message) for message in messages if self.keep_system and message.get("role") == "system"}
        system = [message for message in messages if id(message) in system_ids]
        rest = [message for message in messages if id(message) not in system_ids]
        while rest and estimate_tokens(system + rest) > token_limit:
            rest.pop(0)
        return self._clip(system + rest, token_limit)

    def compress_tokens(self, messages: list[dict[str, Any]], token_limit: int) -> list[dict[str, Any]]:
        """Keep the task, an evidence summary, and as many recent turns as fit."""
        if estimate_tokens(messages) <= token_limit:
            return messages
        system = [message for message in messages if self.keep_system and message.get("role") == "system"]
        task_index = _current_task_index(messages)
        task = [messages[task_index]] if task_index is not None else []
        turns: list[list[dict[str, Any]]] = []
        for index, message in enumerate(messages):
            if (self.keep_system and message.get("role") == "system") or index == task_index:
                continue
            if message.get("role") == "assistant" or not turns:
                turns.append([])
            turns[-1].append(message)
        prefix = system + task
        if estimate_tokens(prefix) > token_limit:
            return self.truncate_tokens(messages, token_limit)
        recent: list[dict[str, Any]] = []
        for turn in reversed(turns):
            if estimate_tokens(prefix + turn + recent) <= token_limit:
                recent = turn + recent
            else:
                break
        dropped = sum(len(turn) for turn in turns) - len(recent)
        if not dropped:
            return self._clip(prefix + recent, token_limit)
        before = next(
            (index for index, message in enumerate(messages) if recent and message is recent[0]), len(messages)
        )
        note = self.evidence_note(messages, before_index=before)
        summary = f"[memory] Omitted {dropped} earlier messages. Full history remains searchable."
        if note:
            summary += "\n" + note
        fitted = prefix + [{"role": "user", "content": summary}] + recent
        if estimate_tokens(fitted) <= token_limit:
            return fitted
        if estimate_tokens(prefix + recent) <= token_limit:
            return prefix + recent
        return self.truncate_tokens(prefix + recent, token_limit)

    def _clip(self, messages: list[dict[str, Any]], token_limit: int) -> list[dict[str, Any]]:
        """Shorten the newest message until the estimate fits. Original messages stay unchanged."""
        if estimate_tokens(messages) <= token_limit:
            return messages
        if not messages:
            return messages
        head, last = messages[:-1], dict(messages[-1])
        text = message_text(last)
        note = "\n[truncated to the token limit]"
        lo, hi, best = 0, len(text), -1
        while lo <= hi:
            mid = (lo + hi) // 2
            last["content"] = text[:mid] + note
            if estimate_tokens(head + [last]) <= token_limit:
                best = mid
                lo = mid + 1
            else:
                hi = mid - 1
        if best >= 0:
            last["content"] = text[:best] + note
            return head + [last]
        return self._clip(head, token_limit)

    def get_summary_stats(self, messages: list[dict[str, Any]]) -> dict[str, int]:
        """Get statistics about message history.

        Args:
            messages: List of message dictionaries

        Returns:
            Dictionary with statistics
        """
        role_counts = {}
        total_chars = 0

        for msg in messages:
            role = msg.get("role", "unknown")
            role_counts[role] = role_counts.get(role, 0) + 1
            total_chars += len(msg.get("content", ""))

        return {
            "total_messages": len(messages),
            "total_characters": total_chars,
            "role_counts": role_counts,
            "compressed": len(messages) > self.max_messages,
        }
