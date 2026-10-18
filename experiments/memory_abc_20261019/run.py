"""Clean generation, official grading, and comparison for the A/B/C study.

Run inside the desktop Linux container:

    python experiments/memory_abc_20261019/run.py generation --arm a
    python experiments/memory_abc_20261019/run.py grading --arm a
    python experiments/memory_abc_20261019/run.py compare

``all`` runs both phases for a, b, and c, then the paired report.  Use a new
``--tag`` for pilot, repeat, or task-set changes; the manifest refuses to mix
them in one directory.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from pathlib import Path

from analysis import build_report  # noqa: E402
from study_config import ARMS, STUDY, load_arm, load_tasks, study_digest  # noqa: E402

# Register the ordinary tools.  The SWE-bench helpers import the legacy
# memory_search module, so the clean agent explicitly removes that registry entry
# and installs its own current-run-only tool only for C.
import minisweagent.tools.basic  # noqa: E402,F401
import minisweagent.tools.find_definition  # noqa: E402,F401
import minisweagent.tools.read  # noqa: E402,F401
import minisweagent.tools.read_many  # noqa: E402,F401
import minisweagent.tools.replace  # noqa: E402,F401
import minisweagent.tools.search  # noqa: E402,F401
from minisweagent.memory.abc import MemoryAgent
from minisweagent.models import get_model
from minisweagent.run.extra.experiment import write_manifest
from minisweagent.run.extra.hf_dataset import load_hf_dataset
from minisweagent.run.extra.swebench import (
    finalize_submission,
    get_sb_environment,
    recover_tracked_patch,
)
from minisweagent.run.utils.save import save_traj
from minisweagent.utils.log import add_file_handler, logger

DATASET = "princeton-nlp/SWE-Bench_Verified"
DEFAULT_WORKERS = 2


def selected_instances(tasks: list[str]) -> list[dict]:
    """Load the pinned SWE-bench instances in the requested order."""
    instances = list(load_hf_dataset(DATASET, "test"))
    by_id = {instance["instance_id"]: instance for instance in instances}
    missing = [task for task in tasks if task not in by_id]
    if missing:
        raise SystemExit(f"tasks missing from {DATASET}: {missing[:5]}")
    return [by_id[task] for task in tasks]


def manifest_tasks(instances: list[dict]) -> list[dict]:
    keys = ("instance_id", "repo", "base_commit", "version", "problem_statement")
    return sorted(
        [{key: instance.get(key) for key in keys} for instance in instances],
        key=lambda task: task["instance_id"],
    )


def process_instance(instance: dict, output_dir: Path, config: dict, run_id: str) -> None:
    """One task: fresh Docker env, clean memory agent, official-ready submission."""
    instance_id = instance["instance_id"]
    instance_dir = output_dir / instance_id
    trace_path = instance_dir / "memory_trace.jsonl"
    instance_dir.mkdir(parents=True, exist_ok=True)
    trace_path.unlink(missing_ok=True)
    (instance_dir / f"{instance_id}.traj.json").unlink(missing_ok=True)
    remove_prediction(output_dir, instance_id)

    task_config = copy.deepcopy(config)
    task_config.setdefault("agent", {})["memory_trace_path"] = str(trace_path)
    model = None
    env = None
    agent = None
    exit_status = "NotStarted"
    result = ""
    extra_info: dict = {}
    started = time.monotonic()

    try:
        model = get_model(config=task_config.get("model", {}))
        env = get_sb_environment(task_config, instance)
        agent = MemoryAgent(model, env, **task_config["agent"])
        exit_status, result = agent.run(instance["problem_statement"])
        extra_info = {"agent_exit_status": exit_status}
        result, exit_status = finalize_submission(result, env, exit_status)
        if exit_status == "MemoryBudgetError":
            # finalize_submission does not know this status; keep any worktree
            # patch for grading, but the analysis still marks the run invalid.
            recovered = recover_tracked_patch(env)
            result = recovered
            exit_status = "RecoveredPatch" if recovered else "MemoryBudgetError"
    except Exception as error:  # noqa: BLE001
        logger.error("Error processing %s: %s", instance_id, error, exc_info=True)
        exit_status = type(error).__name__
        result = ""
        extra_info = {"agent_exit_status": exit_status, "traceback": traceback.format_exc()}
        if env is not None:
            try:
                recovered = recover_tracked_patch(env)
            except Exception:  # noqa: BLE001
                recovered = ""
            if recovered:
                result, exit_status = recovered, "RecoveredPatch"
    finally:
        save_traj(
            agent,
            instance_dir / f"{instance_id}.traj.json",
            exit_status=exit_status,
            result=result,
            extra_info=extra_info,
            instance_id=instance_id,
            run_id=run_id,
        )
        update_prediction(output_dir, instance_id, task_config["model"]["model_name"], result)
        if env is not None:
            try:
                env.cleanup()
            except Exception:  # noqa: BLE001
                logger.warning("Failed to clean up environment for %s", instance_id)
        logger.info("%s finished in %.1fs with %s", instance_id, time.monotonic() - started, exit_status)


def update_prediction(output_dir: Path, instance_id: str, model_name: str, result: str) -> None:
    """Thread-safe prediction update; the runner can use several workers."""
    from minisweagent.run.extra.swebench import update_preds_file

    update_preds_file(output_dir / "preds.json", instance_id, model_name, result)


def remove_prediction(output_dir: Path, instance_id: str) -> None:
    from minisweagent.run.extra.swebench import remove_from_preds_file

    remove_from_preds_file(output_dir / "preds.json", instance_id)


def run_generation(study: Path, arm: str, tag: str, tasks: list[str], workers: int, redo: bool) -> None:
    output = study / tag
    instances = selected_instances(tasks)
    config = load_arm(arm)
    manifest = write_manifest(output, config, [instance["instance_id"] for instance in instances], workers, manifest_tasks(instances))
    digest = study_digest()
    manifest_path = output / "run_manifest.json"
    stored = json.loads(manifest_path.read_text())
    if stored.get("study_source") not in (None, digest):
        raise SystemExit("study code/config changed since this run started; use a new tag")
    if stored.get("study_source") != digest:
        stored["study_source"] = digest
        manifest_path.write_text(json.dumps(stored, indent=2) + "\n")
    logger.info("Generation %s: %d tasks, %d workers, run %s, study %s", tag, len(instances), workers, manifest["run_id"], digest[:16])

    existing = set()
    if not redo and (output / "preds.json").is_file():
        existing = set(json.loads((output / "preds.json").read_text()))
    pending = [instance for instance in instances if instance["instance_id"] not in existing]
    if not pending:
        logger.info("Generation %s is already complete", tag)
        return

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(process_instance, instance, output, config, manifest["run_id"]) for instance in pending]
        for future in futures:
            future.result()

    predictions = json.loads((output / "preds.json").read_text())
    trajectories = list(output.rglob("*.traj.json"))
    expected = {instance["instance_id"] for instance in instances}
    if set(predictions) != expected:
        raise SystemExit(f"incomplete predictions: missing {sorted(expected - set(predictions))}")
    if len(trajectories) != len(expected):
        raise SystemExit(f"incomplete trajectories: {len(trajectories)} != {len(expected)}")
    bad = []
    for trajectory in trajectories:
        status = json.loads(trajectory.read_text()).get("info", {}).get("exit_status")
        if status not in {"Submitted", "RecoveredPatch", "LimitsExceeded", "MemoryBudgetError"}:
            bad.append((trajectory.name, status))
    if bad:
        raise SystemExit(f"generation errors: {bad[:5]}")


def _run_command(command: list[str], *, cwd: Path, log_path: Path, env: dict[str, str] | None = None) -> None:
    started = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
    if process.returncode:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-6000:]
        print(tail, file=sys.stderr)
        raise SystemExit(f"command failed ({process.returncode}); see {log_path}")
    print(f"{log_path.name} finished in {time.monotonic() - started:.1f}s")


def verify_study_source(output: Path) -> None:
    manifest_path = output / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    stored = manifest.get("study_source")
    if stored and stored != study_digest():
        raise SystemExit("study code/config changed since generation; use a new tag for a clean comparison")


def run_grading(study: Path, arm: str, tag: str, workers: int) -> None:
    output = study / tag
    verify_study_source(output)
    manifest = json.loads((output / "run_manifest.json").read_text())
    predictions = json.loads((output / "preds.json").read_text())
    tasks = list(manifest["instance_ids"])
    if set(predictions) != set(tasks):
        raise SystemExit("predictions do not match the manifest task set")
    sanitized = {
        task: row | {"model_patch": row["model_patch"] if row["model_patch"].startswith("diff --git ") else ""}
        for task, row in predictions.items()
    }
    (output / "preds.empty_on_errors.json").write_text(json.dumps(sanitized, indent=2))
    evaluation = output / "evaluation"
    evaluation.mkdir(parents=True, exist_ok=True)
    parameters = {
        "dataset_name": DATASET,
        "split": "test",
        "instance_ids": tasks,
        "predictions_path": str(output / "preds.empty_on_errors.json"),
        "max_workers": workers,
        "force_rebuild": False,
        "cache_level": "instance",
        "clean": False,
        "open_file_limit": 4096,
        "run_id": f"memory-abc-{tag}",
        "timeout": 300,
        "namespace": "swebench",
        "rewrite_reports": False,
        "modal": False,
    }
    (evaluation / "parameters.json").write_text(json.dumps(parameters, indent=2))
    script = (
        "from pathlib import Path\n"
        "from swebench.harness.run_evaluation import main\n"
        f"report = main(**{parameters!r})\n"
        "Path(report).replace('grading_summary.json')\n"
    )
    _run_command(
        [sys.executable, "-c", script],
        cwd=evaluation,
        log_path=output / "grading.log",
        env=os.environ.copy(),
    )
    summary = json.loads((evaluation / "grading_summary.json").read_text())
    if summary["completed_instances"] + summary.get("empty_patch_instances", 0) != len(tasks) or summary.get("error_instances"):
        raise SystemExit(f"official grading incomplete or errored: {summary.get('error_ids')}")


def _suffix(args) -> str:
    parts = []
    if args.pilot:
        parts.append("pilot")
    if args.round:
        parts.append(args.round)
    return ("_" + "_".join(parts)) if parts else ""


def _tags(args) -> dict[str, str]:
    suffix = _suffix(args)
    return {
        "a": args.a_tag or f"a{suffix}",
        "b": args.b_tag or f"b{suffix}",
        "c": args.c_tag or f"c{suffix}",
    }


def _tasks(args) -> list[str]:
    if args.tasks:
        tasks = json.loads(Path(args.tasks).read_text())
        if not isinstance(tasks, list) or not all(isinstance(task, str) for task in tasks):
            raise SystemExit("--tasks must be a JSON list of instance ids")
        return tasks
    return load_tasks(pilot=args.pilot)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("generation", "grading", "compare", "all"))
    parser.add_argument("--arm", choices=("a", "b", "c", "all"), default="all")
    parser.add_argument("--tag", default=None, help="output tag; defaults to the arm name")
    parser.add_argument("--round", default=None, help="round suffix, e.g. r1; all arms become a_r1, b_r1, c_r1")
    parser.add_argument("--rounds", default=None, help="comma-separated rounds for compare, e.g. r1,r2")
    parser.add_argument("--arms", default="a,b,c", help="compare only these arms, e.g. b,c")
    parser.add_argument("--a-tag", default=None, help="tag for the A arm (compare)")
    parser.add_argument("--b-tag", default=None, help="tag for the B arm (compare)")
    parser.add_argument("--c-tag", default=None, help="tag for the C arm (compare)")
    parser.add_argument("--pilot", action="store_true", help="use pilot.json and pilot tags")
    parser.add_argument("--tasks", type=Path, default=None, help="override the task JSON list")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--redo", action="store_true")
    args = parser.parse_args()

    study = STUDY
    arms = list(ARMS) if args.arm == "all" else [args.arm]
    if args.phase in {"generation", "grading"} and platform.system() != "Linux":
        raise SystemExit("Generation and official grading run in the desktop Linux container.")
    if args.tag and len(arms) > 1:
        raise SystemExit("--tag is only valid for a single arm")
    if args.workers <= 0:
        raise SystemExit("--workers must be positive")

    if os.environ.get("DEEPSEEK_API_KEY") and not os.environ.get("MSWEA_MODEL_API_KEY"):
        os.environ["MSWEA_MODEL_API_KEY"] = os.environ["DEEPSEEK_API_KEY"]
    add_file_handler(study / f"{args.phase}_{args.arm}.log")
    if args.phase == "compare":
        requested = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
        if args.rounds:
            rounds = [round.strip() for round in args.rounds.split(",") if round.strip()]
            for round_name in rounds:
                for arm in requested:
                    verify_study_source(study / f"{arm}_{round_name}")
            from analysis import build_multi_report

            multi = build_multi_report(study, rounds)
            print(f"valid={multi['valid']} tasks={multi['tasks']}")
            return
        tags = _tags(args)
        for arm in requested:
            verify_study_source(study / tags[arm])
        report = build_report(study, {arm: tags[arm] for arm in requested}, suffix=_suffix(args))
        print(
            f"valid={report['valid']} "
            + ", ".join(f"{arm}={report['arms'][arm]['resolved']}/{report['arms'][arm]['tasks']}" for arm in ARMS)
        )
        return

    tasks = _tasks(args)
    for arm in arms:
        tag = args.tag or f"{arm}{_suffix(args)}"
        if args.phase in {"generation", "all"}:
            run_generation(study, arm, tag, tasks, args.workers, args.redo)
        if args.phase in {"grading", "all"}:
            run_grading(study, arm, tag, args.workers)
    if args.phase == "all" and set(arms) == set(ARMS):
        tags = {arm: args.tag or f"{arm}{_suffix(args)}" for arm in arms}
        report = build_report(study, tags, suffix=_suffix(args))
        print(
            f"valid={report['valid']} "
            + ", ".join(f"{arm}={report['arms'][arm]['resolved']}/{report['arms'][arm]['tasks']}" for arm in ARMS)
        )


if __name__ == "__main__":
    main()
