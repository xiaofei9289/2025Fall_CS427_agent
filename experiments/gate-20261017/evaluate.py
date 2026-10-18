"""Grade the retrieval-gate rerun with the bundled SWE-bench harness."""

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    if platform.system() != "Linux":
        raise SystemExit("Run evaluation on the desktop's Linux environment. Local macOS evaluation is disabled.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    environment = os.environ | {
        "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root / "SWE-bench"))),
        "DOCKER_HOST": subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True
        ).strip(),
    }
    tasks = json.loads((root / "experiments" / "pilot_20261017" / "tasks.json").read_text())
    for task_id in tasks:
        image = f"swebench/sweb.eval.x86_64.{task_id.replace('__', '_1776_')}:latest"
        subprocess.run(["docker", "pull", "--platform", "linux/amd64", image], env=environment, check=True)
    incomplete = []
    for arm in ("baseline", "retrieval"):
        output = study / arm / "evaluation"
        output.mkdir(parents=True, exist_ok=True)
        parameters = {
            "dataset_name": "princeton-nlp/SWE-bench_Verified", "split": "test",
            "instance_ids": tasks,
            "predictions_path": str(study / arm / "preds.json"), "max_workers": 1,
            "force_rebuild": False, "cache_level": "instance", "clean": False, "open_file_limit": 4096,
            "run_id": f"gate-20261017-{arm}", "timeout": 300, "namespace": "swebench",
            "rewrite_reports": False, "modal": False,
        }
        (output / "parameters.json").write_text(json.dumps(parameters, indent=2))
        script = (
            "from pathlib import Path\nfrom swebench.harness.run_evaluation import main\n"
            f"report = main(**{parameters!r})\n"
            "Path(report).replace('grading_summary.json')\n"
        )
        started = time.monotonic()
        with (study / f"{arm}_grading.log").open("w") as log:
            process = subprocess.run([sys.executable, "-c", script], cwd=output, env=environment,
                                     stdout=log, stderr=subprocess.STDOUT)
        (study / f"{arm}_grading_execution.json").write_text(json.dumps({
            "exit_code": process.returncode, "wall_seconds": time.monotonic() - started,
        }, indent=2))
        print(f"{arm} grading finished: {process.returncode}", flush=True)
        summary_file = output / "grading_summary.json"
        if process.returncode or not summary_file.exists():
            incomplete.append(arm)
            continue
        summary = json.loads(summary_file.read_text())
        finished = summary["completed_instances"] + summary.get("empty_patch_instances", 0)
        if finished != len(tasks) or summary.get("error_instances"):
            incomplete.append(arm)
    if incomplete:
        raise SystemExit(f"Official test execution incomplete for: {', '.join(incomplete)}. Inspect per-task logs.")
    from minisweagent.run.extra.compare import main as compare_main

    compare_main(study / "baseline", study / "retrieval", study)


if __name__ == "__main__":
    main()
