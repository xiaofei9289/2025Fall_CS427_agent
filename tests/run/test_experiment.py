import json
import shlex
import subprocess
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from minisweagent.memory.search import get_search_context, set_search_context
from minisweagent.run.extra.experiment import write_manifest


def test_run_manifest_freezes_config_tasks_and_sources(tmp_path):
    config = {"model": {"model_name": "deterministic"}, "agent": {"step_limit": 50, "enable_memory": False}}
    manifest = write_manifest(tmp_path, config, ["b", "a"], 1)
    assert manifest["instance_ids"] == ["a", "b"]
    assert manifest["config"] == config
    assert manifest["source"]["sha256"]
    assert json.loads((tmp_path / "run_manifest.json").read_text())["run_id"] == manifest["run_id"]
    with zipfile.ZipFile(tmp_path / "source.zip") as archive:
        assert "src/minisweagent/agents/default.py" in archive.namelist()
        assert not any(path.endswith(".env") or "__pycache__" in path for path in archive.namelist())
    assert write_manifest(tmp_path, config, ["a", "b"], 1)["run_id"] == manifest["run_id"]
    with pytest.raises(ValueError, match="including workers"):
        write_manifest(tmp_path, config, ["a", "b"], 2)
    with pytest.raises(ValueError, match="configuration or task IDs changed"):
        write_manifest(tmp_path, {**config, "agent": {"step_limit": 100}}, ["a", "b"], 1)
    with pytest.raises(ValueError, match="configuration or task IDs changed"):
        write_manifest(tmp_path, config, ["a"], 1)
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "preds.json").write_text("{}")
    with pytest.raises(ValueError, match="no run manifest"):
        write_manifest(legacy, config, ["a"], 1)


def test_memory_search_is_isolated_across_parallel_tasks():
    barrier = Barrier(2)

    def search_context(task):
        set_search_context([{"role": "user", "content": task}], task)
        barrier.wait(timeout=5)
        return get_search_context()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(search_context, name) for name in ("first", "second")]
        assert [future.result() for future in futures] == [
            ([{"role": "user", "content": "first"}], "first"),
            ([{"role": "user", "content": "second"}], "second"),
        ]


def test_local_run_links_manifest_trajectory_prediction_and_ast_tools(tmp_path, reset_global_stats):
    from minisweagent.run.extra.swebench import process_instance
    from minisweagent.run.extra.utils.batch_progress import RunBatchProgressManager

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("def add(a, b):\n    return a - b\n")
    for command in (
        ["git", "init", "-q"],
        ["git", "add", "app.py"],
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "fixture"],
    ):
        subprocess.run(command, cwd=repo, check=True)
    script = "from pathlib import Path; Path('app.py').write_text('def add(a, b):\\n    return a + b\\n')"
    outputs = [
        '```tool\n{"name":"repo_map","args":{"query":"add"}}\n```',
        '```tool\n{"name":"code_search","args":{"query":"add"}}\n```',
        f"```bash\n{shlex.quote(sys.executable)} -c {shlex.quote(script)}\n```",
        "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && git diff HEAD\n```",
    ]
    config = {
        "agent": {"enabled_tools": ["repo_map", "code_search"], "step_limit": 5},
        "model": {"model_class": "deterministic", "model_name": "fixture", "outputs": outputs, "cost_per_call": 0.0},
        "environment": {
            "environment_class": "local",
            "cwd": str(repo),
            "env": {"PATH": str(Path(sys.executable).parent) + ":/usr/bin:/bin"},
        },
    }
    output = tmp_path / "run"
    manifest = write_manifest(output, config, ["fixture-1"], 1)
    process_instance(
        {"instance_id": "fixture-1", "problem_statement": "Fix addition"},
        output,
        config,
        RunBatchProgressManager(1, output / "status.yaml"),
        manifest["run_id"],
    )
    trajectory = json.loads((output / "fixture-1" / "fixture-1.traj.json").read_text())
    prediction = json.loads((output / "preds.json").read_text())["fixture-1"]
    assert trajectory["run_id"] == manifest["run_id"]
    assert prediction["model_patch"] == trajectory["info"]["submission"]
    assert "+    return a + b" in prediction["model_patch"]
    assert trajectory["info"]["model_stats"]["api_calls"] == 4
    assert "app.py:1-2" in trajectory["messages"][3]["content"]
    assert '"name": "add"' in trajectory["messages"][5]["content"]
    assert "image" not in config["environment"]
