"""A test-execution tool that returns classified evidence, not just an exit code."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from minisweagent.repair.testrun import execute_test_command


@dataclass
class RunTests:
    name: str = "run_tests"
    description: str = (
        "Run a test command inside the workspace and return a classified summary "
        "(passed/test_failed/collection_error/no_tests/timeout/infra_error), counts, "
        "failed test IDs, and the current diff fingerprint. Use it to reproduce a bug "
        "before patching and to verify the patch afterward."
    )
    parameters: dict = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Test command to run, e.g. 'python -m pytest -q tests/test_config.py'.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 120, maximum 600).",
                    "default": 120,
                },
                "max_output": {
                    "type": "integer",
                    "description": "Maximum characters of command output to return (default 20000).",
                    "default": 20000,
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        }
    )

    def __call__(self, args: dict, env: Any | None = None) -> dict:
        if env is None:
            return {
                "output": "run_tests requires an environment; refusing to execute on the host.",
                "returncode": 1,
            }
        command = str(args.get("command", "")).strip()
        if not command:
            return {"output": "Missing 'command' for run_tests.", "returncode": 2}
        try:
            timeout = max(1, min(600, int(args.get("timeout", 120))))
        except (TypeError, ValueError):
            timeout = 120
        try:
            max_output = max(1000, min(100_000, int(args.get("max_output", 20000))))
        except (TypeError, ValueError):
            max_output = 20000
        run, display = execute_test_command(env, command, timeout=timeout, max_output=max_output)
        return {
            "output": display,
            "returncode": run.exit_code if run.exit_code is not None else (124 if run.timed_out else 1),
            "test_run": run.to_dict(),
        }
