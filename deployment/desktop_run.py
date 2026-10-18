"""Windows desktop validation using Docker's Linux engine; never runs on the editing Mac."""

import argparse
import json
import os
import platform
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["build", "refresh", "checks", "slow-checks", "demo", "grading"])
    parser.add_argument("--official-mirror", action="store_true", help="Use Docker's official ECR Public distribution")
    args = parser.parse_args()
    if platform.system() != "Windows":
        raise SystemExit("Run this script on desktop-pc (Windows), not the local editing Mac.")
    root = Path(__file__).resolve().parents[1]
    output = root / "desktop_validation"
    output.mkdir(exist_ok=True)
    docker_config = output / "docker-config"
    docker_config.mkdir(exist_ok=True)
    (docker_config / "config.json").write_text(json.dumps({
        "auths": {"https://index.docker.io/v1/": {}}, "credsStore": "",
        "cliPluginsExtraDirs": [str(Path(shutil.which("docker")).parent.parent / "cli-plugins")],
    }))
    os.environ["DOCKER_CONFIG"] = str(docker_config)
    os.environ["DOCKER_HOST"] = "npipe:////./pipe/dockerDesktopLinuxEngine"

    def run(name: str, command: list[str]) -> None:
        started = time.monotonic()
        print(f"Starting {name}; log: {output / (name + '.log')}", flush=True)
        with (output / f"{name}.log").open("w", encoding="utf-8") as log:
            process = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT)
        (output / f"{name}.json").write_text(json.dumps({
            "host": platform.node(), "platform": platform.platform(), "phase": name,
            "exit_code": process.returncode, "wall_seconds": time.monotonic() - started,
        }, indent=2))
        if process.returncode:
            print((output / f"{name}.log").read_text(encoding="utf-8", errors="replace")[-5000:], flush=True)
            raise RuntimeError(f"{name} failed with exit code {process.returncode}")
        print(f"Finished {name}", flush=True)

    container = ["docker", "run", "--rm", "--entrypoint=", "--mount", f"type=bind,source={root},target=/workspace",
                 "-w", "/workspace", "-e", "PYTHONPATH=/workspace/src", "-e", "MSWEA_SILENT_STARTUP=1",
                 "-e", "MSWEA_GLOBAL_CONFIG_DIR=/tmp/cs427-config"]
    if args.phase == "build":
        for name, dockerfile, image in (
            ("build_service", "Dockerfile.service", "miniswe-agent-service:local"),
            ("build_sandbox", "Dockerfile.sandbox", "miniswe-sandbox:local"),
            ("build_validation", "Dockerfile.validation", "cs427-validation:local"),
        ):
            command = ["docker", "build", "-f", f"deployment/{dockerfile}", "-t", image]
            if args.official_mirror and name != "build_validation":
                command += ["--build-arg", "PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.11-slim"]
                if name == "build_service":
                    command += ["--build-arg", "DOCKER_CLI_IMAGE=public.ecr.aws/docker/library/docker:29-cli"]
            run(name, [*command, "."])
    elif args.phase == "refresh":
        dockerfile = output / "Dockerfile.refresh"
        dockerfile.write_text("FROM miniswe-agent-service:local\nCOPY src /app/src\n"
                              "RUN pip install --no-cache-dir --no-deps /app\n")
        run("refresh_service", ["docker", "build", "-f", str(dockerfile), "-t", "miniswe-agent-service:local", "."])
    elif args.phase == "checks":
        run("pytest", [*container, "--network", "none", "cs427-validation:local", "python", "-m", "pytest",
                       "tests/service", "tests/tools", "tests/memory", "tests/run/test_audit.py",
                       "tests/run/test_experiment.py", "tests/run/test_compare.py", "tests/run/test_localization_eval.py",
                       "tests/run/test_swebench.py", "tests/agents/test_default.py", "tests/agents/test_time_budget.py",
                       "tests/run/test_save.py",
                       "tests/run/test_memory_abc_config.py",
                       "tests/run/test_memory_abc_analysis.py",
                       "tests/run/test_memory_abc_agent_config.py",
                       "tests/run/test_memory_abc_runner.py",
                       "tests/run/test_patch_export.py",
                       "tests/agents/test_finalization.py",
                       "tests/agents/test_tools_integration.py", "tests/config/test_swebench_template.py",
                       "-k", "not slow", "-q"])
        run("ruff", [*container, "--network", "none", "cs427-validation:local", "ruff", "check",
                     "src/minisweagent/service", "src/minisweagent/run/service.py", "src/minisweagent/run/extra/compare.py",
                     "src/minisweagent/memory/abc", "experiments/memory_abc_20261019",
                     "tests/service", "tests/memory/abc", "tests/run/test_memory_abc_config.py",
                     "tests/run/test_memory_abc_analysis.py", "tests/run/test_memory_abc_agent_config.py",
                     "tests/run/test_memory_abc_runner.py", "tests/run/test_compare.py", "deployment/demo_service.py",
                     "deployment/desktop_run.py", "tests/agents/test_time_budget.py",
                     "tests/agents/test_finalization.py",
                     "tests/run/test_patch_export.py",
                     "experiments/budget_20261017/run.py",
                     "experiments/pilot_20261017/evaluate.py"])
    elif args.phase == "slow-checks":
        run("pytest_slow", [*container,
                            "--mount", "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock",
                            "--mount", "type=volume,source=cs427-hf-cache,target=/hf-cache", "-e", "HF_HOME=/hf-cache",
                            "cs427-validation:local", "python", "-m", "pytest", "tests/run/test_swebench.py",
                            "-m", "slow", "-q"])
    elif args.phase == "grading":
        run("official_grading", [*container, "--mount", "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock",
                                 "--mount", "type=volume,source=cs427-hf-cache,target=/hf-cache", "-e", "HF_HOME=/hf-cache",
                                 "cs427-validation:local", "python", "experiments/pilot_20261017/evaluate.py"])
        run("comparison", [*container, "cs427-validation:local", "python", "-m", "minisweagent.run.extra.compare",
                           "experiments/pilot_20261017/baseline", "experiments/pilot_20261017/retrieval",
                           "experiments/pilot_20261017"])
    elif args.phase == "demo":
        fixture = root / "desktop_demo"
        if not fixture.exists():
            run("demo_prepare", [*container, "miniswe-agent-service:local", "python", "deployment/demo_service.py",
                                 "prepare", "/workspace/desktop_demo"])
        name, volume = "cs427-api-demo-20261017", "cs427-agent-demo-20261017"
        run("demo_start", ["docker", "run", "-d", "--name", name, "-p", "127.0.0.1:18027:8000",
                           "--mount", f"type=volume,source={volume},target=/agent-data",
                           "--mount", f"type=bind,source={fixture / 'input'},target=/repos,readonly",
                           "--mount", f"type=bind,source={fixture / 'service-demo.yaml'},target=/config.yaml,readonly",
                           "--mount", "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock",
                           "-e", "MSWEA_SERVICE_DATA_DIR=/agent-data", "-e", "MSWEA_SERVICE_REPO_ROOT=/repos",
                           "-e", f"MSWEA_SERVICE_WORKSPACE_VOLUME={volume}", "-e", "MSWEA_SERVICE_CONFIG=/config.yaml",
                           "miniswe-agent-service:local"])
        def wait_healthy() -> None:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen("http://127.0.0.1:18027/health", timeout=2) as response:
                        if response.status == 200:
                            return
                except OSError:
                    time.sleep(0.5)
            raise TimeoutError("API did not become healthy")

        try:
            wait_healthy()
            run("demo_http", [*container, "--network", f"container:{name}", "miniswe-agent-service:local", "python",
                              "deployment/demo_service.py", "exercise", "--url", "http://127.0.0.1:8000",
                              "--output", "/workspace/desktop_validation/demo"])
            task_id = json.loads((output / "demo/result.json").read_text())["task"]["id"]
            run("demo_restart", ["docker", "restart", name])
            wait_healthy()
            with urllib.request.urlopen(f"http://127.0.0.1:18027/tasks/{task_id}", timeout=5) as response:
                task = json.load(response)
            (output / "demo/restarted_task.json").write_text(json.dumps(task, indent=2))
            if task["status"] != "succeeded" or task["result"]["n_calls"] != 2:
                raise RuntimeError("Task result did not persist across the API container restart")
        finally:
            run("demo_server_log", ["docker", "logs", name])
            run("demo_stop", ["docker", "rm", "-f", name])


if __name__ == "__main__":
    main()
