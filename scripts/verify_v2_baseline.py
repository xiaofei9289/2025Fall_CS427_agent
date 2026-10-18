#!/usr/bin/env python3
"""Verify the reproducible V2 baseline without calling a model or Docker.

The script checks the four acceptance criteria for the baseline:

1. the package is installed from this checkout and the agent imports;
2. the tool registry and basic/retrieval tools execute independently;
3. the SWE-bench entry point and the frozen experiment configs load;
4. the default offline test suite passes.

Slow tests (Docker, Singularity, a terminal, or Hugging Face network access) are
not part of the default suite. Pass ``--slow`` to run them explicitly.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_PYTHON = (3, 10)
# Keep import-time config writes inside the repository instead of the user's home.
os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")
os.environ.setdefault("MSWEA_GLOBAL_CONFIG_DIR", str(ROOT / ".cache" / "v2-baseline-config"))


def report(status: str, message: str) -> None:
    print(f"[{status}] {message}")


def fail(message: str) -> None:
    report("FAIL", message)
    raise SystemExit(1)


def check_python_and_install() -> None:
    if sys.version_info < MIN_PYTHON:
        fail(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, got {sys.version.split()[0]}")
    try:
        import minisweagent
    except ModuleNotFoundError:
        fail('package is not installed; run `python -m pip install -e ".[dev]"`')
    package = Path(minisweagent.__file__).resolve()
    expected = (ROOT / "src" / "minisweagent").resolve()
    if expected not in package.parents:
        fail(f"imported {package}, expected the editable checkout under {expected}")
    report("ok", f"Python {sys.version.split()[0]} imports the editable package at {package.parent}")


def check_interfaces() -> None:
    from minisweagent.agents.default import DefaultAgent  # noqa: F401
    from minisweagent.memory import HistoryManager, MemorySearch, SessionMemory, TrajectoryReplayer  # noqa: F401
    from minisweagent.memory.search import set_search_context
    from minisweagent.run.extra import audit, compare, experiment, localization_eval, swebench  # noqa: F401

    if not callable(set_search_context):
        fail("minisweagent.memory.search.set_search_context is not callable")
    for method in ("prompt_messages", "fit", "compress_salient"):
        if not hasattr(HistoryManager, method):
            fail(f"HistoryManager.{method} is missing")
    report("ok", "DefaultAgent, memory/search, audit, localization_eval, and swebench import")


def check_tools() -> None:
    import minisweagent.tools.basic  # noqa: F401
    import minisweagent.tools.code_search  # noqa: F401
    import minisweagent.tools.find_definition  # noqa: F401
    import minisweagent.tools.find_references  # noqa: F401
    import minisweagent.tools.memory_search  # noqa: F401
    import minisweagent.tools.read  # noqa: F401
    import minisweagent.tools.read_many  # noqa: F401
    import minisweagent.tools.replace  # noqa: F401
    import minisweagent.tools.search  # noqa: F401
    from minisweagent.tools import REGISTRY
    from minisweagent.tools.basic import ReadFile, WriteFile
    from minisweagent.tools.code_search import CodeContextTool, CodeSearchTool

    expected = {
        "read_file",
        "write_file",
        "code_search",
        "repo_map",
        "code_context",
        "find_definition",
        "find_references",
        "memory_search",
    }
    missing = expected - REGISTRY.keys()
    if missing:
        fail(f"tools not registered: {sorted(missing)}")

    with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
        path = Path(tmp) / "smoke.txt"
        written = WriteFile()({"path": str(path), "content": "v2-baseline\n"})
        read = ReadFile()({"path": str(path)})
    if written["returncode"] != 0 or "v2-baseline" not in read["output"]:
        fail(f"basic tool smoke test failed: write={written}, read={read}")

    search = CodeSearchTool()({"query": "HistoryManager prompt_messages", "limit": 5})
    if search["returncode"] != 0 or "src/minisweagent/memory/history.py" not in search["output"]:
        fail(f"code_search smoke test failed: {search['output'][:500]}")
    context = CodeContextTool()({"query": "HistoryManager prompt_messages", "max_chars": 1200})
    if context["returncode"] != 0 or "src/minisweagent/memory/history.py" not in context["output"]:
        fail(f"code_context smoke test failed: {context['output'][:500]}")
    report("ok", f"{len(REGISTRY)} tools registered; read/write, code_search and code_context execute")


def check_swebench_config() -> None:
    import yaml

    from minisweagent.config import get_config_path

    for name in ("baseline", "brief_only", "retrieval", "retrieval_gate"):
        config = yaml.safe_load(get_config_path(ROOT / "experiments" / "configs" / f"{name}.yaml").read_text())
        if not {"agent", "environment", "model"} <= config.keys():
            fail(f"{name}.yaml is missing agent/environment/model sections")
    retrieval = yaml.safe_load(get_config_path(ROOT / "experiments" / "configs" / "retrieval.yaml").read_text())
    tools = set(retrieval["agent"].get("enabled_tools", []))
    if not {"code_search", "repo_map", "code_context", "find_references"} <= tools:
        fail("retrieval.yaml does not enable all retrieval tools")
    if retrieval["agent"].get("retrieval_policy") != "brief" or not retrieval["agent"].get("repo_brief"):
        fail("retrieval.yaml does not use the brief retrieval policy")
    gate = yaml.safe_load(get_config_path(ROOT / "experiments" / "configs" / "retrieval_gate.yaml").read_text())
    if gate["agent"].get("retrieval_policy") != "gate":
        fail("retrieval_gate.yaml does not preserve the gate policy")

    result = subprocess.run(
        [sys.executable, "-m", "minisweagent.run.extra.swebench", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env=os.environ,
    )
    if result.returncode != 0 or "--config" not in result.stdout:
        fail(f"swebench entry point failed:\n{result.stdout}\n{result.stderr}")
    report("ok", "SWE-bench entry point and baseline/retrieval configs load")


def run_tests(slow: bool, skip: bool) -> None:
    if skip:
        report("skip", "pytest (requested with --skip-tests)")
        return
    command = [sys.executable, "-m", "pytest", "-q"]
    if slow:
        command += ["-m", "slow"]
    print("$ " + " ".join(command))
    result = subprocess.run(command, cwd=ROOT, env=os.environ)
    if result.returncode != 0:
        fail("pytest failed")
    scope = "slow integration suite" if slow else "offline suite (slow tests deselected)"
    report("ok", f"pytest {scope} passed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slow", action="store_true", help="run only @pytest.mark.slow tests (needs Docker/network)")
    parser.add_argument("--skip-tests", action="store_true", help="check imports/tools/config but do not run pytest")
    args = parser.parse_args()

    print("V2 baseline verification")
    check_python_and_install()
    check_interfaces()
    check_tools()
    check_swebench_config()
    run_tests(args.slow, args.skip_tests)
    print("\nV2 baseline checks passed.")


if __name__ == "__main__":
    main()
