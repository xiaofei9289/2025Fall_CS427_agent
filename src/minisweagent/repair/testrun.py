"""Execute a test command and classify its result, without trusting an exit code alone."""

from __future__ import annotations

import hashlib
import re
import shlex
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class TestStatus(str, Enum):
    __test__ = False
    PASSED = "passed"
    TEST_FAILED = "test_failed"
    COLLECTION_ERROR = "collection_error"
    NO_TESTS = "no_tests"
    TIMEOUT = "timeout"
    INFRA_ERROR = "infra_error"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TestRun:
    __test__ = False
    run_id: str
    command: str
    command_hash: str
    exit_code: int | None
    status: TestStatus
    counts: dict[str, int] = field(default_factory=dict)
    failed_ids: tuple[str, ...] = ()
    error_ids: tuple[str, ...] = ()
    duration_s: float = 0.0
    diff_fingerprint: str = ""
    tests_changed: bool = False
    workspace_mutated_during_test: bool = False
    timed_out: bool = False
    output_chars: int = 0
    output_tail: str = ""
    reason: str = ""

    @property
    def all_failed_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.failed_ids, *self.error_ids)))

    @property
    def tests(self) -> int:
        return int(self.counts.get("tests", 0))

    @property
    def failed(self) -> int:
        return int(self.counts.get("failed", 0)) + int(self.counts.get("errors", 0))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["failed_ids"] = list(self.failed_ids)
        data["error_ids"] = list(self.error_ids)
        data["counts"] = dict(self.counts)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestRun:
        try:
            status = TestStatus(str(data.get("status", "unknown")))
        except ValueError:
            status = TestStatus.UNKNOWN
        return cls(
            run_id=str(data.get("run_id", "")),
            command=str(data.get("command", "")),
            command_hash=str(data.get("command_hash", "")),
            exit_code=data.get("exit_code") if isinstance(data.get("exit_code"), int) else None,
            status=status,
            counts={str(k): int(v) for k, v in (data.get("counts") or {}).items()},
            failed_ids=tuple(str(value) for value in (data.get("failed_ids") or ())),
            error_ids=tuple(str(value) for value in (data.get("error_ids") or ())),
            duration_s=float(data.get("duration_s") or 0.0),
            diff_fingerprint=str(data.get("diff_fingerprint", "")),
            tests_changed=bool(data.get("tests_changed", False)),
            workspace_mutated_during_test=bool(data.get("workspace_mutated_during_test", False)),
            timed_out=bool(data.get("timed_out", False)),
            output_chars=int(data.get("output_chars") or 0),
            output_tail=str(data.get("output_tail", "")),
            reason=str(data.get("reason", "")),
        )


def command_hash(command: str) -> str:
    return hashlib.sha256(command.encode("utf-8")).hexdigest()[:16]


_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|warnings?)\b", re.I)
_COLLECTED_RE = re.compile(r"collected\s+(\d+)\s+items?", re.I)
_FAILED_RE = re.compile(r"^FAILED\s+(?!\()(\S+)", re.M)
_ERROR_RE = re.compile(r"^ERROR\s+(?!\()(\S+)", re.M)
_UNITTEST_RE = re.compile(r"^(?:FAIL|ERROR):\s+(\w+)\s+\(([^)]+)\)", re.M)
_RAN_RE = re.compile(r"^Ran\s+(\d+)\s+tests?", re.M)
_INFRA_RE = re.compile(
    r"(command not found|Cannot connect to the Docker daemon|No space left on device|"
    r"OCI runtime|exec format error|Killed|MemoryError|docker: Error response|permission denied)",
    re.I,
)
_COLLECTION_RE = re.compile(r"(?:error|errors) during collection|Interrupted:\s+\d+\s+error", re.I)
_NO_TESTS_RE = re.compile(r"no tests ran|collected 0 items|Ran 0 tests", re.I)
_INTERRUPT_RE = re.compile(r"KeyboardInterrupt|Interrupted", re.I)


def parse_test_output(output: str, returncode: int | None, *, timed_out: bool = False) -> dict[str, Any]:
    """Return status, counts, failed node IDs, and a short reason.

    This handles pytest and unittest output. Other runners still get a conservative
    classification: a non-zero exit without a known summary is ``unknown``, and a
    zero exit with no test summary is ``no_tests`` rather than ``passed``.
    """
    text = output or ""
    counts = {
        "tests": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "xfailed": 0,
        "xpassed": 0,
        "collected": 0,
    }
    for value, name in _COUNT_RE.findall(text):
        key = "errors" if name.lower().startswith("error") else name.lower()
        if key in counts:
            counts[key] = int(value)
    collected = _COLLECTED_RE.search(text)
    if collected:
        counts["collected"] = int(collected.group(1))

    failed_ids = list(dict.fromkeys(_FAILED_RE.findall(text)))
    error_ids = list(dict.fromkeys(_ERROR_RE.findall(text)))
    unittest_ids = [f"{module}.{name}" for name, module in _UNITTEST_RE.findall(text)]
    if unittest_ids:
        failed_ids = list(dict.fromkeys([*failed_ids, *unittest_ids]))
        counts["failed"] = max(counts["failed"], len(unittest_ids))
    ran = _RAN_RE.search(text)
    if ran and counts["tests"] == 0:
        counts["tests"] = int(ran.group(1))

    if counts["collected"]:
        counts["tests"] = counts["collected"]
    if counts["tests"] == 0:
        counts["tests"] = sum(counts[key] for key in ("passed", "failed", "errors", "skipped", "xfailed", "xpassed"))

    collection_error = bool(_COLLECTION_RE.search(text)) or (
        bool(error_ids) and not any("::" in node for node in error_ids) and counts["tests"] == 0
    )
    no_tests = bool(_NO_TESTS_RE.search(text)) or (counts["tests"] == 0 and returncode == 0)
    infra_error = bool(_INFRA_RE.search(text))
    interrupted = bool(_INTERRUPT_RE.search(text)) and not collection_error

    if timed_out:
        status, reason = TestStatus.TIMEOUT, "test command timed out"
    elif infra_error:
        status, reason = TestStatus.INFRA_ERROR, "environment or command failure"
    elif collection_error:
        status, reason = TestStatus.COLLECTION_ERROR, "collection/import error"
    elif no_tests:
        status, reason = TestStatus.NO_TESTS, "no tests ran"
    elif interrupted:
        status, reason = TestStatus.INTERRUPTED, "test run interrupted"
    elif counts["failed"] or counts["errors"] or failed_ids or error_ids:
        status, reason = (
            TestStatus.TEST_FAILED,
            (f"{counts['failed']} failed, {counts['errors']} errors, {counts['passed']} passed"),
        )
    elif returncode == 0 and counts["tests"] > 0:
        status, reason = TestStatus.PASSED, f"{counts['passed']} passed"
    elif returncode == 0:
        status, reason = TestStatus.NO_TESTS, "no tests ran"
    else:
        status, reason = TestStatus.UNKNOWN, f"unparsed exit code {returncode}"
    return {"status": status, "counts": counts, "failed_ids": failed_ids, "error_ids": error_ids, "reason": reason}


def _decode_output(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _execute(env: Any, command: str, timeout: int) -> dict[str, Any]:
    # A same-size edit within the same second can leave a stale .pyc that CPython
    # still accepts, so the verification run would test the old bytecode.
    prepared = "find . -name '*.pyc' -delete 2>/dev/null || true; export PYTHONDONTWRITEBYTECODE=1; " + command
    wrapped = f"timeout -k 5 {int(timeout)} bash -lc {shlex.quote(prepared)}"
    result = env.execute(wrapped, timeout=timeout + 5)
    output = result.get("output") or ""
    # macOS and minimal images often lack GNU timeout; retry without the wrapper.
    if result.get("returncode") == 127 and "timeout" in output.lower() and "not found" in output.lower():
        result = env.execute(prepared, timeout=timeout + 5)
    return result


def execute_test_command(env: Any, command: str, *, timeout: int = 120, max_output: int = 20000) -> tuple[TestRun, str]:
    """Run ``command`` in ``env``, classify it, and return a bounded display string."""
    from minisweagent.repair.diff import compute_diff, diff_fingerprint, summarize_diff

    started = time.monotonic()
    before = compute_diff(env)
    before_summary = summarize_diff(before.patch)
    timed_out = False
    exit_code: int | None = None
    output = ""
    try:
        result = _execute(env, command, timeout)
        output = result.get("output") or ""
        exit_code = result.get("returncode")
        if exit_code == 124 or (exit_code == 137 and time.monotonic() - started >= timeout - 1):
            timed_out = True
    except subprocess.TimeoutExpired as error:
        timed_out = True
        output = _decode_output(error.output)
    except Exception as error:  # noqa: BLE001
        output = f"{type(error).__name__}: {error}"
        exit_code = None

    after = compute_diff(env)
    parsed = parse_test_output(output, exit_code, timed_out=timed_out)
    duration = time.monotonic() - started
    counts = parsed["counts"]
    status = parsed["status"]
    tail = output[-2000:] if len(output) > 2000 else output
    run = TestRun(
        run_id=uuid.uuid4().hex,
        command=command,
        command_hash=command_hash(command),
        exit_code=exit_code,
        status=status,
        counts=counts,
        failed_ids=tuple(parsed["failed_ids"]),
        error_ids=tuple(parsed["error_ids"]),
        duration_s=round(duration, 3),
        diff_fingerprint=diff_fingerprint(before.patch) if before.ok else "",
        tests_changed=before_summary.test_files_changed,
        workspace_mutated_during_test=before.ok and after.ok and before.patch != after.patch,
        timed_out=timed_out,
        output_chars=len(output),
        output_tail=tail,
        reason=parsed["reason"],
    )
    display = (
        f"[run_tests] status={run.status.value} exit={run.exit_code} tests={counts['tests']} "
        f"passed={counts['passed']} failed={counts['failed']} errors={counts['errors']} "
        f"duration={run.duration_s:.2f}s"
    )
    if run.timed_out:
        display += " timed_out=true"
    if run.tests_changed:
        display += " test_files_changed=true"
    if run.workspace_mutated_during_test:
        display += " workspace_changed_during_test=true"
    if run.diff_fingerprint:
        display += f" diff={run.diff_fingerprint[:12]}"
    display += f"\n{output[:max_output]}"
    if len(output) > max_output:
        display += f"\n... ({len(output) - max_output} characters truncated; full tail is in the artifact)"
    return run, display
