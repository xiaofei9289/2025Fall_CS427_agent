import subprocess
import sys

from minisweagent.environments.local import LocalEnvironment
from minisweagent.repair.testrun import (
    TestStatus,
    execute_test_command,
    parse_test_output,
)
from minisweagent.tools.run_tests import RunTests


def test_pytest_failure_keeps_node_id_and_counts():
    output = "FAILED tests/test_config.py::test_none - AssertionError\n1 failed, 2 passed in 0.10s\n"
    parsed = parse_test_output(output, 1)
    assert parsed["status"] is TestStatus.TEST_FAILED
    assert parsed["counts"]["tests"] == 3
    assert parsed["failed_ids"] == ["tests/test_config.py::test_none"]


def test_pytest_success_counts_tests():
    parsed = parse_test_output("3 passed in 0.02s\n", 0)
    assert parsed["status"] is TestStatus.PASSED
    assert parsed["counts"]["tests"] == 3


def test_pytest_no_tests_is_not_a_pass():
    parsed = parse_test_output("no tests ran in 0.01s\n", 4)
    assert parsed["status"] is TestStatus.NO_TESTS


def test_collection_error_is_distinct():
    output = "ERROR tests/test_broken.py\n!!!! Interrupted: 1 error during collection !!!!\n1 error in 0.05s\n"
    parsed = parse_test_output(output, 2)
    assert parsed["status"] is TestStatus.COLLECTION_ERROR
    assert parsed["error_ids"] == ["tests/test_broken.py"]


def test_environment_error_is_distinct():
    parsed = parse_test_output("bash: python: command not found\n", 127)
    assert parsed["status"] is TestStatus.INFRA_ERROR


def test_timeout_is_distinct():
    parsed = parse_test_output("", None, timed_out=True)
    assert parsed["status"] is TestStatus.TIMEOUT


def test_unittest_failure_keeps_identifier():
    output = "FAIL: test_add (test_mod.TestClass)\nRan 1 test in 0.001s\nFAILED (failures=1)\n"
    parsed = parse_test_output(output, 1)
    assert parsed["status"] is TestStatus.TEST_FAILED
    assert parsed["counts"]["tests"] == 1
    assert parsed["failed_ids"] == ["test_mod.TestClass.test_add"]


def test_zero_tests_with_zero_exit_is_not_a_pass():
    parsed = parse_test_output("Ran 0 tests in 0.000s\nOK\n", 0)
    assert parsed["status"] is TestStatus.NO_TESTS


def test_unknown_nonzero_exit_is_not_a_test_failure():
    parsed = parse_test_output("error: unrecognized arguments: --bogus\n", 4)
    assert parsed["status"] is TestStatus.UNKNOWN


def test_timeout_exception_returns_partial_output(monkeypatch):
    class TimeoutEnv:
        def execute(self, command, cwd="", *, timeout=None):
            if command.startswith("git "):
                return {"output": "", "returncode": 0}
            raise subprocess.TimeoutExpired(command, timeout, output=b"partial failure")

    run, display = execute_test_command(TimeoutEnv(), "pytest -q", timeout=1)
    assert run.status is TestStatus.TIMEOUT
    assert run.timed_out is True
    assert run.output_tail == "partial failure"
    assert "status=timeout" in display


def test_run_tests_refuses_to_execute_without_environment():
    result = RunTests()({"command": "pytest -q"}, None)
    assert result["returncode"] == 1
    assert "requires an environment" in result["output"]


def test_stale_pyc_is_removed_before_verification(tmp_path):
    """A same-size edit within the same second must not reuse old bytecode."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "test_app.py").write_text("from app import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "base"],
        check=True,
        capture_output=True,
    )
    command = f"{sys.executable} -m pytest -q test_app.py"
    env = LocalEnvironment(cwd=str(repo))
    first, _ = execute_test_command(env, command, timeout=30)
    assert first.status is TestStatus.TEST_FAILED
    (repo / "app.py").write_text("def add(a, b):\n    return a + b\n")
    second, _ = execute_test_command(env, command, timeout=30)
    assert second.status is TestStatus.PASSED
