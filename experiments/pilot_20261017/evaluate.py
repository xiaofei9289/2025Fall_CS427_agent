"""Run the bundled official harness, preserving grading logs beside each arm."""

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


def main() -> None:
    if platform.system() != "Linux":
        raise SystemExit("Run evaluation on the desktop's Linux/WSL environment. Local macOS evaluation is disabled.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    environment = os.environ | {
        "PYTHONPATH": str(root / "SWE-bench"),
        "DOCKER_HOST": subprocess.check_output(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"], text=True
        ).strip(),
    }
    tasks = json.loads((study / "tasks.json").read_text())
    for task_id in tasks:
        image = f"swebench/sweb.eval.x86_64.{task_id.replace('__', '_1776_')}:latest"
        subprocess.run(["docker", "pull", "--platform", "linux/amd64", image], env=environment, check=True)
    incomplete = []
    for arm in ("baseline", "retrieval"):
        output = study / arm / "evaluation"
        output.mkdir(exist_ok=True)
        parameters = {
            "dataset_name": "princeton-nlp/SWE-bench_Verified", "split": "test",
            "instance_ids": tasks,
            "predictions_path": str(study / arm / "preds.json"), "max_workers": 1,
            "force_rebuild": False, "cache_level": "instance", "clean": False, "open_file_limit": 4096,
            "run_id": f"pilot-20261017-{arm}", "timeout": 300, "namespace": "swebench",
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
        elif json.loads(summary_file.read_text())["completed_instances"] != len(tasks):
            incomplete.append(arm)
    if incomplete:
        raise SystemExit(f"Official test execution incomplete for: {', '.join(incomplete)}. Inspect per-task logs.")


if __name__ == "__main__":
    main()
