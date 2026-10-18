from minisweagent.repair.state import (
    RepairPhase,
    RepairState,
    local_verification,
    new_failures,
    record_test_run,
)
from minisweagent.repair.testrun import TestRun, TestStatus


def _run(
    status,
    *,
    failed_ids=(),
    error_ids=(),
    tests=1,
    passed=0,
    failed=0,
    errors=0,
    command_hash="cmd",
    fingerprint="",
    tests_changed=False,
    mutated=False,
):
    return TestRun(
        run_id="run",
        command="pytest",
        command_hash=command_hash,
        exit_code=0 if status is TestStatus.PASSED else 1,
        status=status,
        counts={"tests": tests, "passed": passed, "failed": failed, "errors": errors},
        failed_ids=tuple(failed_ids),
        error_ids=tuple(error_ids),
        diff_fingerprint=fingerprint,
        tests_changed=tests_changed,
        workspace_mutated_during_test=mutated,
    )


def _verified_state():
    state = RepairState(pristine_fingerprint="", diff_ok=True)
    record_test_run(
        state,
        _run(TestStatus.TEST_FAILED, failed_ids=("tests/test_app.py::test_add",), failed=1),
    )
    record_test_run(
        state,
        _run(TestStatus.PASSED, passed=1, fingerprint="patch-fp"),
    )
    return state


def test_failed_baseline_then_passing_verification_is_verified():
    state = _verified_state()
    assert state.phase is RepairPhase.VERIFY
    assert local_verification(state, "patch-fp") == (
        "verified",
        "baseline failures now pass; no new failures",
    )


def test_no_baseline_is_inconclusive():
    state = RepairState(pristine_fingerprint="", diff_ok=True)
    assert local_verification(state, "fp")[0] == "inconclusive"


def test_passing_baseline_does_not_verify_a_fix():
    state = RepairState(pristine_fingerprint="", diff_ok=True)
    record_test_run(state, _run(TestStatus.PASSED, passed=1))
    assert local_verification(state, "fp")[0] == "inconclusive"


def test_changed_test_files_invalidate_verification():
    state = _verified_state()
    state.tests_changed = True
    assert local_verification(state, "patch-fp")[0] == "inconclusive"


def test_new_failure_is_a_regression():
    state = RepairState(pristine_fingerprint="", diff_ok=True)
    record_test_run(state, _run(TestStatus.TEST_FAILED, failed_ids=("test_a",), failed=1))
    record_test_run(
        state,
        _run(TestStatus.TEST_FAILED, failed_ids=("test_b",), tests=2, failed=1, passed=1, fingerprint="fp2"),
    )
    assert new_failures(state) == ("test_b",)
    assert local_verification(state, "fp2")[0] == "regression"


def test_changed_command_is_inconclusive():
    state = _verified_state()
    state.last_run = _run(TestStatus.PASSED, passed=1, command_hash="other", fingerprint="patch-fp")
    assert local_verification(state, "patch-fp")[0] == "inconclusive"


def test_stale_workspace_is_not_verified():
    state = _verified_state()
    assert local_verification(state, "changed-after-test")[0] == "stale"


def test_fewer_tests_than_baseline_is_inconclusive():
    state = RepairState(pristine_fingerprint="", diff_ok=True)
    record_test_run(state, _run(TestStatus.TEST_FAILED, failed_ids=("a",), tests=2, failed=1, passed=1))
    record_test_run(state, _run(TestStatus.PASSED, tests=1, passed=1, fingerprint="fp2"))
    assert local_verification(state, "fp2")[0] == "inconclusive"


def test_environment_and_no_test_baselines_are_inconclusive():
    for status in (TestStatus.TIMEOUT, TestStatus.INFRA_ERROR, TestStatus.COLLECTION_ERROR, TestStatus.NO_TESTS):
        state = RepairState(pristine_fingerprint="", diff_ok=True)
        record_test_run(state, _run(status))
        record_test_run(state, _run(TestStatus.PASSED, passed=1, fingerprint="fp2"))
        assert local_verification(state, "fp2")[0] == "inconclusive", status


def test_still_failing_is_unverified():
    state = RepairState(pristine_fingerprint="", diff_ok=True)
    record_test_run(state, _run(TestStatus.TEST_FAILED, failed_ids=("a",), failed=1))
    record_test_run(state, _run(TestStatus.TEST_FAILED, failed_ids=("a",), failed=1, fingerprint="fp2"))
    assert local_verification(state, "fp2")[0] == "unverified"


def test_workspace_mutation_during_test_is_inconclusive():
    state = _verified_state()
    state.last_run = _run(TestStatus.PASSED, passed=1, fingerprint="patch-fp", mutated=True)
    assert local_verification(state, "patch-fp")[0] == "inconclusive"


def test_phase_moves_to_patch_when_verification_fails():
    state = _verified_state()
    record_test_run(state, _run(TestStatus.TEST_FAILED, failed_ids=("a",), failed=1, fingerprint="fp3"))
    assert state.phase is RepairPhase.PATCH


def test_baseline_must_be_clean():
    state = RepairState(pristine_fingerprint="", diff_ok=True)
    record_test_run(state, _run(TestStatus.TEST_FAILED, failed_ids=("a",), failed=1, fingerprint="dirty"))
    record_test_run(state, _run(TestStatus.PASSED, passed=1, fingerprint="fp2"))
    assert local_verification(state, "fp2")[0] == "inconclusive"
