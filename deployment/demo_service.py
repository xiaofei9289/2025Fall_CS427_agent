"""Offline HTTP plumbing demo; deterministic responses are not an LLM benchmark."""

import argparse
import json
import subprocess
import time
from pathlib import Path

import requests
import yaml


def prepare(directory: Path) -> None:
    repo = directory / "input" / "add-fixture"
    repo.mkdir(parents=True)
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "test_add.py").write_text("from app import add\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    subprocess.run(["git", "init", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Demo", "-c", "user.email=demo@example.org",
                    "commit", "-m", "Demo fixture"], check=True)
    config = yaml.safe_load((Path(__file__).resolve().parents[1] / "src/minisweagent/config/service.yaml").read_text())
    config["model"] = {"model_name": "deterministic", "model_class": "deterministic", "cost_per_call": 0.0,
                       "outputs": ["```tool\n" + json.dumps({"name": "write_file", "args": {
                           "path": "app.py", "content": "def add(a, b):\n    return a + b\n",
                       }}) + "\n```", "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"]}
    (directory / "service-demo.yaml").write_text(yaml.safe_dump(config))


def exercise(url: str, repo: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    response = requests.post(f"{url}/tasks", json={
        "repo": repo, "issue": "add(2, 3) must return 5. Fix the subtraction bug.", "variant": "retrieval",
    }, timeout=10)
    response.raise_for_status()
    task_id = response.json()["id"]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        response = requests.get(f"{url}/tasks/{task_id}", timeout=10)
        response.raise_for_status()
        task = response.json()
        if task["status"] in {"succeeded", "failed", "interrupted", "cancelled"}:
            break
        time.sleep(0.2)
    else:
        raise TimeoutError(f"Demo task {task_id} did not finish")
    events = requests.get(f"{url}/tasks/{task_id}/events", timeout=10)
    events.raise_for_status()
    for name in ("patch.diff", "verification.txt", "trajectory.json"):
        artifact = requests.get(f"{url}/tasks/{task_id}/artifacts/{name}", timeout=10)
        artifact.raise_for_status()
        (output / name).write_bytes(artifact.content)
    (output / "result.json").write_text(json.dumps({
        "mode": "deterministic offline plumbing demo", "task": task, "events": events.json(),
    }, indent=2))
    if task["status"] != "succeeded":
        raise RuntimeError(f"Demo failed: {task}")
    print(f"Demo succeeded: {task_id}; artifacts: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("directory", type=Path)
    run_parser = commands.add_parser("exercise")
    run_parser.add_argument("--url", default="http://127.0.0.1:8000")
    run_parser.add_argument("--repo", default="/repos/add-fixture")
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.directory)
    else:
        exercise(args.url, args.repo, args.output)


if __name__ == "__main__":
    main()
