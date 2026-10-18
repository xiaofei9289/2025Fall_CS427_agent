"""A thin agent adapter around the evidence-driven repair workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from minisweagent.agents.default import AgentConfig, DefaultAgent, NonTerminatingException
from minisweagent.repair.artifacts import ArtifactWriter
from minisweagent.repair.diff import compute_diff, diff_fingerprint, sanitize_patch, summarize_diff
from minisweagent.repair.state import (
    RepairPhase,
    RepairState,
    local_verification,
    new_failures,
    record_test_run,
)
from minisweagent.repair.testrun import TestRun, TestStatus, command_hash, execute_test_command
from minisweagent.tools.run_tests import RunTests
from minisweagent.utils.log import logger

_FINAL_MARKERS = {"MINI_SWE_AGENT_FINAL_OUTPUT", "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}
_ALLOWED_STATUSES = {"verified", "acceptance_passed"}


@dataclass
class RepairAgentConfig(AgentConfig):
    workflow_enabled: bool = False
    workflow_mode: str = "advisory"
    acceptance_command: str = ""
    test_timeout: int = 120
    max_test_runs: int = 6
    max_verify_attempts: int = 2
    artifact_dir: str = ""
    action_observation_template: str = "Observation: {{output.output}}"

    def __post_init__(self):
        if self.workflow_mode not in {"advisory", "strict"}:
            raise ValueError(f"workflow_mode must be 'advisory' or 'strict', got {self.workflow_mode!r}")


class SubmissionBlocked(NonTerminatingException):
    """Raised when the workflow refuses a submission and asks the model to continue."""


@dataclass(frozen=True)
class SubmissionDecision:
    allow: bool
    status: str
    reason: str
    message: str = ""
    patch: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow": self.allow,
            "status": self.status,
            "reason": self.reason,
            "patch_chars": len(self.patch),
        }


class RepairWorkflow:
    """Owns the evidence ledger and the submit gate.

    The model may choose actions, but it cannot decide that a test passed or that
    an unverified patch is verified. Those decisions come from this object.
    """

    def __init__(self, config: RepairAgentConfig):
        self.config = config
        self.enabled = config.workflow_enabled
        self.state = RepairState()
        self.writer = ArtifactWriter(config.artifact_dir)
        self.last_decision: SubmissionDecision | None = None

    def begin(self, env: Any) -> None:
        if not self.enabled:
            return
        diff = compute_diff(env)
        self.state = RepairState(pristine_fingerprint=diff_fingerprint(diff.patch), diff_ok=diff.ok)
        self.last_decision = None
        self._write_state(diff_fingerprint(diff.patch) if diff.ok else "")

    def may_run_test(self) -> bool:
        return not self.enabled or self.state.test_runs < self.config.max_test_runs

    def record_tool_output(self, output: dict, env: Any) -> None:
        if not self.enabled:
            return
        data = output.get("test_run")
        if not isinstance(data, dict):
            return
        run = TestRun.from_dict(data)
        diff = compute_diff(env)
        summary = summarize_diff(diff.patch)
        record_test_run(
            self.state,
            run,
            diff_ok=diff.ok,
            tests_changed=summary.test_files_changed,
        )
        self._write_verification(run, summary)
        self._write_state(diff_fingerprint(diff.patch) if diff.ok else "")

    def before_submit(self, env: Any, submission: dict | None = None) -> SubmissionDecision:
        if not self.enabled:
            return SubmissionDecision(True, "disabled", "workflow disabled")
        try:
            return self._before_submit(env)
        except Exception as error:  # noqa: BLE001
            logger.warning(f"Repair workflow failed during submission; failing open: {error}")
            decision = SubmissionDecision(True, "workflow_error", f"{type(error).__name__}: {error}")
            self.last_decision = decision
            self._write_state("")
            return decision

    def _before_submit(self, env: Any) -> SubmissionDecision:
        diff = compute_diff(env)
        summary = summarize_diff(diff.patch)
        current_fingerprint = diff_fingerprint(diff.patch) if diff.ok else ""
        self.state.diff_ok = diff.ok
        self.state.tests_changed = summary.test_files_changed

        if not diff.ok:
            decision = SubmissionDecision(True, "workflow_error", f"workspace diff unavailable: {diff.error}")
            self._record_decision(decision, diff, summary, current_fingerprint)
            return decision

        if summary.is_empty:
            self.state.empty_blocks += 1
            if self.state.empty_blocks <= max(0, self.config.max_verify_attempts):
                decision = SubmissionDecision(
                    False,
                    "empty_patch",
                    "the sanitized patch is empty",
                    message=(
                        "WORKFLOW: submission blocked (empty_patch). The sanitized patch is empty. "
                        "Implement the fix in a tracked source file; reproduction scripts and junk "
                        f"files are not submitted. Blocked attempt {self.state.empty_blocks}/"
                        f"{max(0, self.config.max_verify_attempts)}."
                    ),
                )
                self._record_decision(decision, diff, summary, current_fingerprint)
                return decision

        acceptance = self._run_acceptance(env, current_fingerprint)
        after = compute_diff(env)
        after_summary = summarize_diff(after.patch)
        after_fingerprint = diff_fingerprint(after.patch) if after.ok else ""
        if after_fingerprint != current_fingerprint:
            diff, summary, current_fingerprint = after, after_summary, after_fingerprint
            self.state.diff_ok = after.ok
            self.state.tests_changed = after_summary.test_files_changed

        status, reason = local_verification(self.state, current_fingerprint)
        if acceptance is not None:
            if acceptance.status is TestStatus.TEST_FAILED:
                status, reason = "acceptance_failed", "the configured test command failed"
            elif acceptance.status is TestStatus.PASSED and status != "regression":
                status = "verified" if status == "verified" else "acceptance_passed"
                reason = "the configured test command passed"
            elif acceptance.status in {
                TestStatus.TIMEOUT,
                TestStatus.INFRA_ERROR,
                TestStatus.COLLECTION_ERROR,
                TestStatus.NO_TESTS,
                TestStatus.INTERRUPTED,
                TestStatus.UNKNOWN,
            }:
                status, reason = (
                    "inconclusive",
                    (
                        f"configured test command was {acceptance.status.value}; "
                        "environment errors are not treated as code failures"
                    ),
                )

        patch = sanitize_patch(diff.patch)
        if status in _ALLOWED_STATUSES:
            decision = SubmissionDecision(True, status, reason, patch=patch)
        else:
            self.state.verify_attempts += 1
            if self.config.workflow_mode == "strict" and self.state.verify_attempts <= max(
                0, self.config.max_verify_attempts
            ):
                decision = SubmissionDecision(
                    False,
                    status,
                    reason,
                    message=self._block_message(status, reason, summary),
                )
            else:
                decision = SubmissionDecision(True, status, reason, patch=patch)

        self._record_decision(decision, diff, summary, current_fingerprint)
        return decision

    def _block_message(self, status: str, reason: str, summary) -> str:
        runs = f"{self.state.test_runs}/{self.config.max_test_runs}"
        return (
            f"WORKFLOW: submission blocked ({status}: {reason}). "
            f"Changed files: {len(summary.changed_files)}; test runs: {runs}. "
            "Run the relevant test with the run_tests tool, fix the failures, then submit again. "
            f"After {max(0, self.config.max_verify_attempts)} blocked attempts, submission is allowed "
            "with an unverified record."
        )

    def _run_acceptance(self, env: Any, current_fingerprint: str) -> TestRun | None:
        command = self.config.acceptance_command.strip()
        if not command or self.state.test_runs >= self.config.max_test_runs:
            return None
        if (
            self.state.last_run is not None
            and self.state.last_run.command_hash == command_hash(command)
            and self.state.last_run.diff_fingerprint == current_fingerprint
        ):
            return self.state.last_run
        run, _display = execute_test_command(env, command, timeout=self.config.test_timeout, max_output=20000)
        diff = compute_diff(env)
        summary = summarize_diff(diff.patch)
        record_test_run(
            self.state,
            run,
            diff_ok=diff.ok,
            tests_changed=summary.test_files_changed,
        )
        self._write_verification(run, summary)
        return run

    def _record_decision(self, decision: SubmissionDecision, diff, summary, current_fingerprint: str) -> None:
        self.last_decision = decision
        if decision.allow:
            self.state.phase = RepairPhase.FINALIZE
        self.state.last_decision = decision.to_dict()
        self._write_diff(diff, summary, decision)
        self._write_state(current_fingerprint)

    def _write_diff(self, diff, summary, decision: SubmissionDecision | None = None) -> None:
        if not self.writer.enabled or not diff.ok:
            return
        patch = sanitize_patch(diff.patch)
        if not patch.strip():
            return
        self.writer.write_text("repair_diff.patch", patch)
        payload = summary.to_dict()
        if decision is not None:
            payload["decision"] = decision.to_dict()
        self.writer.write_json("repair_diff.json", payload)

    def _write_verification(self, run: TestRun, summary) -> None:
        if not self.writer.enabled:
            return
        if self.state.baseline is run:
            status, reason = "baseline_recorded", run.reason
        else:
            status, reason = local_verification(self.state, run.diff_fingerprint)
        self.writer.append_jsonl(
            "verification.jsonl",
            {
                "run": run.to_dict(),
                "diff": summary.to_dict(),
                "phase": self.state.phase.value,
                "local_verification": {"status": status, "reason": reason},
            },
        )

    def _write_state(self, current_fingerprint: str) -> None:
        if not self.writer.enabled:
            return
        status, reason = local_verification(self.state, current_fingerprint)
        payload = self.state.to_dict({"status": status, "reason": reason})
        payload["new_failures"] = list(new_failures(self.state))
        self.writer.write_json("repair_state.json", payload)

    def finalize(self, env: Any, exit_status: str, result: str | None) -> None:
        if not self.enabled:
            return
        try:
            diff = compute_diff(env)
            summary = summarize_diff(diff.patch)
            current_fingerprint = diff_fingerprint(diff.patch) if diff.ok else ""
            self.state.diff_ok = diff.ok
            self.state.tests_changed = summary.test_files_changed
            self.state.phase = RepairPhase.DONE
            self._write_diff(diff, summary, self.last_decision)
            self._write_state(current_fingerprint)
            status, reason = local_verification(self.state, current_fingerprint)
            if self.last_decision is not None:
                verification = {
                    "status": self.last_decision.status,
                    "reason": self.last_decision.reason,
                    "local": {"status": status, "reason": reason},
                }
            else:
                verification = {"status": status, "reason": reason}
            self.writer.write_json(
                "run_summary.json",
                {
                    "exit_status": exit_status,
                    "result_chars": len(result or ""),
                    "verification": verification,
                    "new_failures": list(new_failures(self.state)),
                    "state": self.state.to_dict({"status": status, "reason": reason}),
                },
            )
        except Exception as error:  # noqa: BLE001
            logger.warning(f"Failed to finalize repair artifacts: {error}")


class RepairAgent(DefaultAgent):
    """DefaultAgent plus an evidence gate on submission."""

    def __init__(self, *args, config_class=RepairAgentConfig, **kwargs):
        enabled = kwargs.get("enabled_tools")
        if isinstance(enabled, list) and "run_tests" in enabled:
            # Installed locally by the workflow; keeping it in the global filter
            # would make DefaultAgent reject an otherwise valid config.
            kwargs["enabled_tools"] = [name for name in enabled if name != "run_tests"]
        super().__init__(*args, config_class=config_class, **kwargs)
        self.workflow = RepairWorkflow(self.config)
        self._active_action: dict | None = None
        if self.config.workflow_enabled:
            self._install_run_tests()

    def _install_run_tests(self) -> None:
        tool = RunTests()
        self.tools = {**self.tools, tool.name: tool}
        self.extra_template_vars["tool_specs"] = [
            {"name": item.name, "description": item.description, "parameters": item.parameters}
            for item in self.tools.values()
        ]

    def run(self, task: str, **kwargs) -> tuple[str, str]:
        self.workflow.begin(self.env)
        try:
            exit_status, result = super().run(task, **kwargs)
        except BaseException as error:
            self.workflow.finalize(self.env, type(error).__name__, str(error))
            raise
        self.workflow.finalize(self.env, exit_status, result)
        return exit_status, result

    def execute_action(self, action: dict) -> dict:
        is_test_tool = action.get("kind") == "tool" and action.get("tool_name") == "run_tests"
        if self.config.workflow_enabled and is_test_tool and not self.workflow.may_run_test():
            output = {
                "output": (
                    f"run_tests budget exhausted: {self.workflow.state.test_runs}/"
                    f"{self.config.max_test_runs} runs used. Use the remaining budget to fix and submit."
                ),
                "returncode": 1,
            }
            self.has_finished(output)
            return output
        if self.config.workflow_enabled and is_test_tool and self.config.time_limit > 0:
            remaining = self.budget_state().get("remaining_seconds") or 0
            if remaining <= 3:
                output = {
                    "output": "Time budget too low for run_tests; submit the current patch instead.",
                    "returncode": 1,
                }
                self.has_finished(output)
                return output
            args = action.setdefault("tool_args", {})
            try:
                requested = int(args.get("timeout", 120))
            except (TypeError, ValueError):
                requested = 120
            args["timeout"] = max(1, min(requested, int(remaining) - 5))
        self._active_action = action
        try:
            output = super().execute_action(action)
        finally:
            self._active_action = None
        if self.config.workflow_enabled and is_test_tool:
            self.workflow.record_tool_output(output, self.env)
        return output

    def has_finished(self, output: dict[str, str]) -> None:
        if self.config.workflow_enabled:
            action = self._active_action
            # A tool output (for example a test that prints the marker) must not submit.
            if action is not None and action.get("kind") == "tool":
                return
            if action is not None and action.get("kind") == "bash" and self._is_submission(output):
                decision = self.workflow.before_submit(self.env, output)
                if not decision.allow:
                    raise SubmissionBlocked(decision.message)
                if decision.patch:
                    # Submit exactly the sanitized worktree diff that was gated,
                    # so new untracked source files are not silently lost.
                    output["output"] = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n" + decision.patch
        super().has_finished(output)

    @staticmethod
    def _is_submission(output: dict[str, str]) -> bool:
        lines = (output.get("output") or "").lstrip().splitlines()
        return bool(lines and lines[0].strip() in _FINAL_MARKERS)
