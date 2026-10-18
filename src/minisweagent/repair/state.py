"""Pure repair state and evidence gates. No model calls and no environment access."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from minisweagent.repair.testrun import TestRun, TestStatus


class RepairPhase(str, Enum):
    INVESTIGATE = "investigate"
    REPRODUCED = "reproduced"
    PATCH = "patch"
    VERIFY = "verify"
    FINALIZE = "finalize"
    DONE = "done"


@dataclass
class RepairState:
    phase: RepairPhase = RepairPhase.INVESTIGATE
    pristine_fingerprint: str = ""
    diff_ok: bool = False
    baseline: TestRun | None = None
    last_run: TestRun | None = None
    test_runs: int = 0
    verify_attempts: int = 0
    empty_blocks: int = 0
    tests_changed: bool = False
    last_decision: dict[str, Any] | None = None

    def to_dict(self, verification: dict[str, str] | None = None) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "pristine_fingerprint": self.pristine_fingerprint,
            "diff_ok": self.diff_ok,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "last_run": self.last_run.to_dict() if self.last_run else None,
            "test_runs": self.test_runs,
            "verify_attempts": self.verify_attempts,
            "empty_blocks": self.empty_blocks,
            "tests_changed": self.tests_changed,
            "verification": verification,
            "last_decision": self.last_decision,
        }


def record_test_run(
    state: RepairState, run: TestRun, *, diff_ok: bool | None = None, tests_changed: bool | None = None
) -> None:
    """The first run is the baseline; later runs are verification attempts."""
    state.test_runs += 1
    if diff_ok is not None:
        state.diff_ok = diff_ok
    if tests_changed is not None:
        state.tests_changed = tests_changed
    if state.baseline is None:
        state.baseline = run
        state.phase = RepairPhase.REPRODUCED if run.status is TestStatus.TEST_FAILED else RepairPhase.INVESTIGATE
        return
    state.last_run = run
    state.phase = RepairPhase.VERIFY if run.status is TestStatus.PASSED else RepairPhase.PATCH


def new_failures(state: RepairState) -> tuple[str, ...]:
    if state.baseline is None or state.last_run is None:
        return ()
    baseline = set(state.baseline.all_failed_ids)
    return tuple(sorted(set(state.last_run.all_failed_ids) - baseline))


def local_verification(state: RepairState, current_fingerprint: str) -> tuple[str, str]:
    """Return (status, reason) for local verification, never official resolution.

    Statuses: verified, regression, unverified, stale, inconclusive.
    """
    if not state.diff_ok:
        return "inconclusive", "workspace diff unavailable"
    if state.baseline is None:
        return "inconclusive", "no baseline test run"
    if state.baseline.diff_fingerprint != state.pristine_fingerprint:
        return "inconclusive", "baseline was not taken on a clean workspace"
    if state.tests_changed:
        return "inconclusive", "test files changed; self-verification is not trustworthy"
    if state.baseline.status is TestStatus.NO_TESTS:
        return "inconclusive", "baseline ran no tests"
    if state.baseline.status is TestStatus.TIMEOUT:
        return "inconclusive", "baseline test run timed out"
    if state.baseline.status is TestStatus.INFRA_ERROR:
        return "inconclusive", "baseline hit an environment error"
    if state.baseline.status is TestStatus.COLLECTION_ERROR:
        return "inconclusive", "baseline had a collection/import error"
    if state.baseline.status is not TestStatus.TEST_FAILED:
        return "inconclusive", f"baseline was {state.baseline.status.value}, not a failing test"

    if state.last_run is None:
        return "stale", "no test run after the baseline"
    if state.last_run.command_hash != state.baseline.command_hash:
        return "inconclusive", "test command changed between baseline and verification"
    if state.last_run.workspace_mutated_during_test:
        return "inconclusive", "workspace changed while the test was running"
    if current_fingerprint != state.last_run.diff_fingerprint:
        return "stale", "workspace changed since the last test run"

    failures = new_failures(state)
    if failures:
        return "regression", f"new failing tests: {', '.join(failures[:3])}"
    if state.last_run.status is TestStatus.TEST_FAILED:
        return "unverified", f"{state.last_run.failed} test(s) still failing"
    if state.last_run.status is not TestStatus.PASSED:
        return "unverified", f"verification run was {state.last_run.status.value}"
    if not state.baseline.tests or not state.last_run.tests:
        return "inconclusive", "test counts unavailable"
    if state.last_run.tests < state.baseline.tests:
        return "inconclusive", (f"fewer tests ran after the patch ({state.last_run.tests} < {state.baseline.tests})")
    if state.last_run.counts.get("skipped", 0) > state.baseline.counts.get("skipped", 0):
        return "inconclusive", "more tests were skipped after the patch"
    expected_passes = state.baseline.counts.get("passed", 0) + state.baseline.counts.get("failed", 0)
    if state.last_run.counts.get("passed", 0) < expected_passes:
        return "inconclusive", "fewer passing tests than the baseline required"
    if not state.baseline.all_failed_ids:
        return "inconclusive", "baseline failure IDs unavailable"
    return "verified", "baseline failures now pass; no new failures"
