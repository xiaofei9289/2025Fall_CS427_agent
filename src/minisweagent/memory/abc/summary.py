"""Deterministic evidence summary for the ``summary`` and ``summary_search`` arms.

The summary is a pure function of the turns no longer in view, plus a small
invalidation pass over the turns that *are* still in view.  It is rebuilt from
the transcript on every model call, which makes it exactly reproducible and
avoids stale-summary state.  It records only what the agent actually executed and
observed:

* successful file reads, with the source step and a short excerpt;
* modifications, which make earlier reads stale;
* passing test runs, kept separate from other actions so an old pass is never
  presented as verification of a later patch;
* nonzero exits that a later identical execution did not supersede;
* other successful actions, as a small recent-actions list.

The invalidation pass is important.  Summarizing only the omitted prefix is not
enough: a write can be in the retained window while the read it invalidates is
in the summary.  ``later_segments`` lets the policy hand the summarizer the
retained turns, so those writes still remove the summarized read and mark any
summarized test pass as "before a later edit, not verification".

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
_TEST_TOOLS = {"run_tests"}
# A deliberately conservative detector: it only needs to separate a test pass
# from "other executed actions", not to understand every test runner.  A command
# that writes and runs tests in one step is recorded as a write and as a test;
# the test is treated as pre-edit unless it is in a later turn (see below).
_TEST_QUERY_RE = re.compile(r"(?:^|\s)(?:--version|--help|--collect-only|--co|--fixtures|-h)(?:\s|$)")
_TEST_RE = re.compile(
    r"(?:^|[;&|]\s*)(?:sudo\s+)?(?:(?:uv|poetry|pdm|pipenv)\s+run\s+)?"
    r"(?:python(?:\d+(?:\.\d+)?)?\s+-m\s+)?"
    r"(?:[^\s;&|]*/)?(?:pytest|py\.test|unittest)\b"
    r"|(?:^|[;&|]\s*)(?:tox|nox|ctest|rspec|phpunit)\b"
    r"|(?:^|[;&|]\s*)(?:make|npm|yarn|pnpm|go|cargo|mvn|gradle)\s+(?:run\s+)?test\b",
    re.IGNORECASE,
)

_EPHEMERAL_SUFFIXES = (".log", ".out", ".err", ".tmp")
_MAX_READS = 4
_MAX_WRITES = 5
_MAX_FAILURES = 3
_MAX_ACTIONS = 4
_MAX_TESTS = 3
_MAX_SUPERSEDED = 5
_EXCERPT_CHARS = 240
_TEST_EXCERPT_CHARS = 120


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


def _clean_observation(text: str) -> str:
    body = " ".join(_TAG_RE.sub(" ", text).split())
    body = re.sub(r"^Observation:\s*", "", body)
    # The template emits <returncode>N</returncode> before <output>; stripping
    # the tags leaves that bare number at the head.
    return re.sub(r"^-?\d{1,3}\s+", "", body)


def _excerpt(text: str, limit: int = _EXCERPT_CHARS) -> str:
    return _clean_observation(text)[:limit]


def _tail_excerpt(text: str, limit: int = _TEST_EXCERPT_CHARS) -> str:
    return _clean_observation(text)[-limit:]


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


def _is_ephemeral_target(path: str) -> bool:
    """A redirect to a log/temp file is not a source edit."""
    normalized = _normalize(path)
    if not normalized:
        return False
    if normalized.startswith(("/tmp/", "/var/tmp/", "/dev/")):
        return True
    return normalized.endswith(_EPHEMERAL_SUFFIXES)


def _source_targets(targets: set[str]) -> set[str]:
    return {target for target in targets if not _is_ephemeral_target(target)}


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


def _is_test_action(kind: str, name: str, command: str) -> bool:
    if kind == "tool":
        return name in _TEST_TOOLS or name.endswith("_tests")
    if _TEST_QUERY_RE.search(command):
        return False
    return bool(_TEST_RE.search(command))


def _test_label(kind: str, name: str, command: str, args: dict[str, Any]) -> str:
    if kind == "tool":
        command = str(args.get("command", "")).strip()
        return f"{name} {command}".strip()[:120] or name
    return command[:120] or "test"


@dataclass(frozen=True)
class _TestFact:
    step: int
    label: str
    excerpt: str

    def line(self, *, stale: bool = False) -> str:
        suffix = " (exit 0; before a later change)" if stale else " (exit 0)"
        detail = f" — {self.excerpt}" if self.excerpt else ""
        return f"- step {self.step}: {self.label}{suffix}{detail}"


def _write_action(segment: Segment) -> tuple[set[str], bool]:
    """Return the files a later turn may write, without recording its actions."""
    parsed = _parse_action(segment.messages[0])
    if parsed is None:
        return set(), False
    kind, name, args = parsed
    if kind == "tool":
        if name not in _WRITE_TOOLS:
            return set(), False
        path = _normalize(str(args.get("path", "")))
        return ({path} if path else set()), not path
    command = str(args.get("command", "")).strip()
    targets, unknown = _write_targets(command)
    return _source_targets(targets), unknown


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
    verification_facts: int = 0
    stale_verification_facts: int = 0
    superseded_read_facts: int = 0
    truncated: bool = False

    def message(self) -> dict[str, Any]:
        return {"role": "user", "content": self.text, "extra": {"kind": "summary"}}


def build_evidence_summary(
    segments: list[Segment] | tuple[Segment, ...],
    steps: dict[int, int],
    *,
    token_limit: int,
    later_segments: list[Segment] | tuple[Segment, ...] = (),
) -> EvidenceSummary:
    """Build a bounded evidence digest from omitted segments.

    ``segments`` must be the whole omitted prefix, in chronological order.
    ``later_segments`` are the retained turns after that prefix (the window and
    the latest turn).  They are not rendered; they are used only to invalidate a
    summarized read or test pass that a later write has superseded.  The function
    is pure: same inputs and limit -> same text.
    """
    if token_limit <= 0 or not segments:
        return EvidenceSummary(text="", tokens=0, turns=0)

    reads: dict[str, str] = {}
    writes: dict[str, str] = {}
    failures: dict[tuple, str] = {}
    tests: dict[tuple, _TestFact] = {}
    actions: list[str] = []
    turn_count = 0
    step_values: list[int] = []
    last_write_step = 0

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
            excerpt = _tail_excerpt(text) if _is_test_action(kind, name, "") else _excerpt(text)
            if code != 0:
                failures.pop(key, None)
                tests.pop(key, None)
                failures[key] = f"- step {step}: {label} (exit {code}) — {excerpt}"
                continue
            failures.pop(key, None)
            if name in _READ_TOOLS and path:
                reads.pop(path, None)
                reads[path] = f"- step {step}: read {path} — {excerpt}"
            elif name in _WRITE_TOOLS and path:
                reads.pop(path, None)
                writes.pop(path, None)
                writes[path] = f"- step {step}: modified {path}; earlier reads may be stale"
                last_write_step = max(last_write_step, step)
            elif _is_test_action(kind, name, ""):
                tests.pop(key, None)
                tests[key] = _TestFact(step=step, label=label, excerpt=excerpt)
            else:
                actions.append(f"- step {step}: {label or name} (exit 0)")
            continue

        command = str(args.get("command", "")).strip()
        label = command[:120] or "bash"
        key = ("bash", command, "")
        if code != 0:
            excerpt = _tail_excerpt(text) if _is_test_action(kind, name, command) else _excerpt(text)
            failures.pop(key, None)
            tests.pop(key, None)
            failures[key] = f"- step {step}: {label} (exit {code}) — {excerpt}"
            continue
        failures.pop(key, None)

        read_paths = _read_paths(command) or []
        targets, unknown = _write_targets(command)
        targets = _source_targets(targets)
        is_test = _is_test_action(kind, name, command)
        excerpt = _tail_excerpt(text) if is_test else _excerpt(text)
        test = _TestFact(step=step, label=_test_label(kind, name, command, args), excerpt=excerpt)

        if unknown:
            reads.clear()
            writes.clear()
            writes["*"] = (
                f"- step {step}: bash edit with unknown targets may have modified sources; "
                "earlier reads were dropped as stale"
            )
            last_write_step = max(last_write_step, step)
            if is_test:
                tests.pop(key, None)
                tests[key] = test
            continue
        if targets:
            target_paths = {_normalize(target) for target in targets if _normalize(target)}
            for path in target_paths:
                reads.pop(path, None)
                writes.pop(path, None)
                writes[path] = f"- step {step}: modified {path} via bash; earlier reads may be stale"
            last_write_step = max(last_write_step, step)
            # A mixed command can read one file and write another.  Do not throw
            # away the read merely because the command also writes.
            for path in read_paths:
                normalized = _normalize(path)
                if normalized and normalized not in target_paths:
                    reads.pop(normalized, None)
                    reads[normalized] = f"- step {step}: read {normalized} — {_excerpt(text)}"
            if is_test:
                tests.pop(key, None)
                tests[key] = test
            continue
        if read_paths:
            for path in read_paths:
                normalized = _normalize(path)
                if normalized:
                    reads.pop(normalized, None)
                    reads[normalized] = f"- step {step}: read {normalized} — {excerpt}"
            if is_test:
                tests.pop(key, None)
                tests[key] = test
            continue
        if is_test:
            tests.pop(key, None)
            tests[key] = test
        else:
            actions.append(f"- step {step}: {label} (exit 0)")

    # A write in the retained window cannot be summarized (the model sees it),
    # but it must still invalidate a read or test pass that is now in the summary.
    later_writes: dict[str, int] = {}
    later_unknown = 0
    later_test_failure = 0
    for segment in later_segments:
        if segment.kind != "turn":
            continue
        step = steps.get(segment.first_index)
        if not isinstance(step, int) or step <= 0:
            continue
        targets, unknown = _write_action(segment)
        if unknown:
            later_unknown = max(later_unknown, step)
        for target in targets:
            path = _normalize(target)
            if path:
                later_writes[path] = max(later_writes.get(path, 0), step)
        parsed = _parse_action(segment.messages[0])
        if parsed is not None:
            kind, name, args = parsed
            command = str(args.get("command", "")).strip()
            _text, _role, code = _observation(segment)
            if code not in (None, 0) and _is_test_action(kind, name, command):
                later_test_failure = max(later_test_failure, step)

    superseded: dict[str, int] = {}
    if later_unknown:
        if reads or superseded:
            superseded = {"*": later_unknown}
        reads.clear()
    else:
        for path, step in later_writes.items():
            if path in reads:
                reads.pop(path, None)
                superseded[path] = step

    latest_change = max(
        last_write_step,
        later_unknown,
        later_test_failure,
        max(later_writes.values(), default=0),
    )
    current_tests = [fact for fact in tests.values() if fact.step > latest_change]
    stale_tests = [fact for fact in tests.values() if fact.step <= latest_change]

    header = f"[memory] Omitted {turn_count} earlier turn(s)"
    if step_values:
        header += f" (steps {min(step_values)}-{max(step_values)})"
    header += "."

    test_lines = [fact.line() for fact in current_tests[-_MAX_TESTS:]]
    stale_test_lines = [fact.line(stale=True) for fact in stale_tests[-_MAX_TESTS:]]
    read_lines = list(reads.values())[-_MAX_READS:]
    write_lines = list(writes.values())[-_MAX_WRITES:]
    failure_lines = list(failures.values())[-_MAX_FAILURES:]
    action_lines = actions[-_MAX_ACTIONS:]
    superseded_lines: list[str] = []
    for path, step in list(superseded.items())[-_MAX_SUPERSEDED:]:
        if path == "*":
            superseded_lines.append(
                f"- step {step}: a later edit with unknown targets may have modified sources; "
                "the earlier read was dropped as stale"
            )
        else:
            superseded_lines.append(
                f"- step {step}: modified {path} after the summarized read; that read was dropped as stale"
            )

    # Section order is for the reader; the third value is the trim priority
    # (lower is dropped first).  Writes and verification outlive reads, so a
    # read can never survive without the invalidation fact that supersedes it.
    sections: list[tuple[str, list[str], int]] = [
        ("Verification (tests passing after the latest edit):", test_lines, 6),
        ("Modified files (from omitted steps; later edits may supersede):", write_lines, 5),
        ("Confirmed reads (source step):", read_lines, 2),
        ("Superseded by later edits:", superseded_lines, 3),
        ("Failures / open issues:", failure_lines, 4),
        ("Earlier test runs (before a later change; not verification):", stale_test_lines, 1),
        ("Other executed actions:", action_lines, 0),
    ]

    def render() -> str:
        parts = [header]
        for title, lines, _priority in sections:
            if lines:
                parts.append(title)
                parts.extend(lines)
        return "\n".join(parts)

    dropped = False
    while estimate_text_tokens(render()) > token_limit:
        candidates = [
            (priority, index)
            for index, (_title, lines, priority) in enumerate(sections)
            if lines
        ]
        if not candidates:
            break
        _priority, index = min(candidates)
        sections[index][1].pop(0)
        dropped = True

    text = render()
    if estimate_text_tokens(text) > token_limit:
        text = fit_text_to_tokens(text, token_limit)
        dropped = True
    return EvidenceSummary(
        text=text,
        tokens=estimate_text_tokens(text),
        turns=turn_count,
        read_facts=len(read_lines),
        write_facts=len(write_lines),
        failure_facts=len(failure_lines),
        action_facts=len(action_lines),
        verification_facts=len(test_lines),
        stale_verification_facts=len(stale_test_lines),
        superseded_read_facts=len(superseded_lines),
        truncated=dropped,
    )
