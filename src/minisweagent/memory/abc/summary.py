"""Deterministic evidence summary for the ``summary`` and ``summary_search`` arms.

The summary is a pure function of the turns that are no longer in view.  It is
rebuilt from the omitted turns on every model call, which makes it exactly
reproducible and avoids stale-summary state.  It records only what the agent
actually executed and observed:

* successful file reads, with the source step and a short excerpt;
* modifications, which make earlier reads stale;
* nonzero exits that a later identical execution did not supersede;
* other successful actions, as a small recent-actions list.

It never reads the task's gold patch, the grader, or another run.  The hard
token cap is enforced here, before the summary competes for prompt budget.
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass
from typing import Any

from .budget import estimate_text_tokens, fit_text_to_tokens, message_text
from .conversation import Segment

_ACTION_RE = re.compile(r"```(bash|tool)\n(.*?)\n```", re.DOTALL)
_RETURN_RE = re.compile(r"<returncode>(-?\d+)</returncode>")
_TAG_RE = re.compile(r"</?(?:returncode|output|output_head|output_tail|elided_chars|warning)[^>]*>")
_REDIRECT_RE = re.compile(r"^\d?(?:>{1,2})(?!&)")
_READ_HEADS = {"cat", "head", "tail", "nl"}
_READ_TOOLS = {"read_file", "refined_read_file"}
_WRITE_TOOLS = {"write_file", "replace"}

_MAX_READS = 4
_MAX_WRITES = 5
_MAX_FAILURES = 3
_MAX_ACTIONS = 4
_EXCERPT_CHARS = 240


def _segments(command: str) -> list[list[str]]:
    return [tokens for tokens in (part.split() for part in re.split(r"[;&|]+", command)) if tokens]


def _head(tokens: list[str]) -> tuple[str, list[str]]:
    if tokens[0] == "sudo" and len(tokens) > 1:
        return tokens[1], tokens[2:]
    return tokens[0], tokens[1:]


def _normalize(path: str) -> str:
    path = path.strip().strip("'\"")
    if not path:
        return ""
    return posixpath.normpath(path.removeprefix("/testbed/"))


def _excerpt(text: str, limit: int = _EXCERPT_CHARS) -> str:
    body = " ".join(_TAG_RE.sub(" ", text).split())
    body = re.sub(r"^Observation:\s*", "", body)
    return body[:limit]


def _read_paths(command: str) -> list[str] | None:
    """Paths printed by a pure read command, or ``None`` when it is not one."""
    if "<<" in command or any(_REDIRECT_RE.match(token) for token in command.split()):
        return None
    paths: list[str] = []
    for tokens in _segments(command):
        head, rest = _head(tokens)
        if head in _READ_HEADS:
            paths.extend(token for token in rest if not token.startswith("-"))
        elif head == "sed" and not any(
            re.fullmatch(r"-[a-zA-Z]*i[a-zA-Z]*(?:\.\w+)?", token) or token == "--in-place" for token in rest
        ):
            positional = [token for token in rest if not token.startswith("-")]
            paths.extend(positional[1:])  # The first positional is the sed script.
    return paths or None


def _write_targets(command: str) -> tuple[set[str], bool]:
    """Files a bash command may modify, and whether it may modify unknown files."""
    targets: set[str] = set()
    unknown = False
    for tokens in _segments(command):
        head, rest = _head(tokens)
        positional = [token for token in rest if not token.startswith("-")]
        if head in {"sed", "perl"} and any(
            re.fullmatch(r"-[a-zA-Z]*i[a-zA-Z]*(?:\.\w+)?", token) or token == "--in-place" for token in rest
        ):
            targets.update(positional[1:])
        elif head in {"mv", "rm", "touch"}:
            targets.update(positional)
        elif head in {"tee", "cp", "truncate", "install", "dd"} and positional:
            targets.add(positional[-1])
        elif (
            head in {"patch", "xargs"}
            or head == "find" and any(token.startswith("-exec") or token in {"-delete", "-fprint", "-fprintf"} for token in rest)
            or head in {"python", "python3"} and ("-c" in rest or "<<-" in rest)
            or head == "git"
            and len(rest) > 1
            and rest[0]
            in {"apply", "checkout", "restore", "stash", "reset", "clean", "merge", "rebase", "cherry-pick"}
        ):
            unknown = True

        heredoc = "<<" in " ".join(tokens)
        redirected = any(_REDIRECT_RE.match(token) for token in tokens)
        if heredoc and (
            head in {"python", "python3", "sh", "bash", "zsh", "perl", "ruby", "node"} or not redirected
        ):
            unknown = True

        for index, token in enumerate(tokens):
            redirect = re.match(r"^\d?(>{1,2})(.*)$", token)
            if not redirect or redirect.group(2).startswith("&"):
                continue
            target = redirect.group(2) or (tokens[index + 1] if index + 1 < len(tokens) else "")
            if target and target != "/dev/null":
                targets.add(target)
    return targets, unknown


def _parse_action(message: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    blocks = _ACTION_RE.findall(message_text(message))
    if len(blocks) != 1:
        return None
    kind, content = blocks[0]
    if kind == "bash":
        return "bash", "bash", {"command": content.strip()}
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("name"), str):
        return None
    args = payload.get("args", {})
    if not isinstance(args, dict):
        return None
    return "tool", payload["name"], args


def _observation(segment: Segment) -> tuple[str, str | None, int | None]:
    """Return the action's observation text and return code.

    Prefer the last user message tagged as an observation; a trailing feedback
    message is not the command's result and must not replace it.
    """
    user_messages = [message for message in segment.messages if message.get("role") == "user"]
    if not user_messages:
        return "", None, None
    observations = [
        message
        for message in user_messages
        if isinstance(message.get("extra"), dict) and message["extra"].get("kind") == "observation"
    ]
    message = (observations or user_messages)[-1]
    text = message_text(message)
    extra = message.get("extra") if isinstance(message.get("extra"), dict) else {}
    code = extra.get("returncode")
    if not isinstance(code, int):
        match = _RETURN_RE.search(text)
        code = int(match.group(1)) if match else None
    return text, message.get("role"), code


@dataclass
class EvidenceSummary:
    """Rendered evidence digest plus the counts the report needs."""

    text: str
    tokens: int
    turns: int
    read_facts: int = 0
    write_facts: int = 0
    failure_facts: int = 0
    action_facts: int = 0
    truncated: bool = False

    def message(self) -> dict[str, Any]:
        return {"role": "user", "content": self.text, "extra": {"kind": "summary"}}


def build_evidence_summary(
    segments: list[Segment] | tuple[Segment, ...],
    steps: dict[int, int],
    *,
    token_limit: int,
) -> EvidenceSummary:
    """Build a bounded evidence digest from omitted segments.

    ``segments`` must be the whole omitted prefix, in chronological order.  The
    function is pure: same segments, same steps, same limit -> same text.
    """
    if token_limit <= 0 or not segments:
        return EvidenceSummary(text="", tokens=0, turns=0)

    reads: dict[str, str] = {}
    writes: dict[str, str] = {}
    failures: dict[tuple, str] = {}
    actions: list[str] = []
    turn_count = 0
    step_values: list[int] = []

    for segment in segments:
        if segment.kind != "turn":
            continue
        turn_count += 1
        assistant_index = segment.first_index
        step = steps.get(assistant_index, turn_count)
        step_values.append(step)
        assistant = segment.messages[0]
        parsed = _parse_action(assistant)
        if parsed is None:
            continue
        kind, name, args = parsed
        text, _role, code = _observation(segment)
        if code is None:
            continue

        if kind == "tool":
            raw_path = args.get("path", "")
            path = _normalize(raw_path) if isinstance(raw_path, str) else ""
            operation = json.dumps({key: value for key, value in args.items() if key != "path"}, sort_keys=True)
            key = (name, path, operation)
            label = f"{name} {path}".strip()
            excerpt = _excerpt(text)
            if code != 0:
                failures.pop(key, None)
                failures[key] = f"- step {step}: {label} (exit {code}) — {excerpt}"
                continue
            failures.pop(key, None)
            if name in _READ_TOOLS and path:
                reads[path] = f"- step {step}: read {path} — {excerpt}"
            elif name in _WRITE_TOOLS and path:
                reads.pop(path, None)
                writes[path] = f"- step {step}: modified {path}; earlier reads may be stale"
            else:
                actions.append(f"- step {step}: {label or name} (exit 0)")
            continue

        command = str(args.get("command", "")).strip()
        label = command[:120] or "bash"
        key = ("bash", command, "")
        excerpt = _excerpt(text)
        if code != 0:
            failures.pop(key, None)
            failures[key] = f"- step {step}: {label} (exit {code}) — {excerpt}"
            continue
        failures.pop(key, None)

        read_paths = _read_paths(command)
        if read_paths:
            for path in read_paths:
                normalized = _normalize(path)
                if normalized:
                    reads[normalized] = f"- step {step}: read {normalized} — {excerpt}"
            continue

        targets, unknown = _write_targets(command)
        if unknown:
            reads.clear()
            writes["*"] = (
                f"- step {step}: bash edit with unknown targets may have modified sources; "
                "earlier reads were dropped as stale"
            )
        elif targets:
            for target in targets:
                normalized = _normalize(target)
                if normalized:
                    reads.pop(normalized, None)
                    writes[normalized] = (
                        f"- step {step}: modified {normalized} via bash; earlier reads may be stale"
                    )
        else:
            actions.append(f"- step {step}: {label} (exit 0)")

    header = f"[memory] Omitted {turn_count} earlier turn(s)"
    if step_values:
        header += f" (steps {min(step_values)}-{max(step_values)})"
    header += "."

    read_lines = list(reads.values())[-_MAX_READS:]
    write_lines = list(writes.values())[-_MAX_WRITES:]
    failure_lines = list(failures.values())[-_MAX_FAILURES:]
    action_lines = actions[-_MAX_ACTIONS:]

    # Display in the order a reader needs: facts, modifications, failures,
    # other actions.  Trim in the reverse order of importance.
    sections: list[tuple[str, list[str]]] = [
        ("Confirmed reads (source step):", read_lines),
        ("Modified files (earlier reads may be stale):", write_lines),
        ("Failures / open issues:", failure_lines),
        ("Other executed actions:", action_lines),
    ]

    def render() -> str:
        parts = [header]
        for title, lines in sections:
            if lines:
                parts.append(title)
                parts.extend(lines)
        return "\n".join(parts)

    while estimate_text_tokens(render()) > token_limit:
        for section_index in (3, 2, 0, 1):  # actions, writes, reads, failures
            title, lines = sections[section_index]
            if lines:
                lines.pop(0)
                break
        else:
            break

    text = render()
    if estimate_text_tokens(text) > token_limit:
        text = fit_text_to_tokens(text, token_limit)
    return EvidenceSummary(
        text=text,
        tokens=estimate_text_tokens(text),
        turns=turn_count,
        read_facts=len(read_lines),
        write_facts=len(write_lines),
        failure_facts=len(failure_lines),
        action_facts=len(action_lines),
        truncated=estimate_text_tokens(render()) > token_limit,
    )
