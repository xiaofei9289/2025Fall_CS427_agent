#!/usr/bin/env python3

"""Run mini-SWE-agent on SWE-bench instances in batch mode."""
# Read this first: https://mini-swe-agent.com/latest/usage/swebench/  (usage docs)

import concurrent.futures
import copy
import json
import random
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Annotated

import typer
import yaml
from jinja2 import StrictUndefined, Template
from rich.live import Live

from minisweagent import Environment
from minisweagent.agents.default import DefaultAgent
from minisweagent.config import builtin_config_dir, get_config_path
from minisweagent.environments import get_environment
from minisweagent.models import get_model
from minisweagent.run.extra.experiment import write_manifest
from minisweagent.run.extra.hf_dataset import load_hf_dataset
from minisweagent.run.extra.utils.batch_progress import RunBatchProgressManager

try:  # pragma: no cover
    import minisweagent.tools.basic  # noqa: F401
    import minisweagent.tools.code_search  # noqa: F401
    import minisweagent.tools.find_definition  # noqa: F401
    import minisweagent.tools.memory_search  # noqa: F401
    import minisweagent.tools.read  # noqa: F401
    import minisweagent.tools.read_many  # noqa: F401
    import minisweagent.tools.replace  # noqa: F401
    import minisweagent.tools.search  # noqa: F401
except Exception:  # noqa: BLE001
    pass
from minisweagent.run.utils.save import save_traj
from minisweagent.utils.log import add_file_handler, logger

_HELP_TEXT = """Run mini-SWE-agent on SWEBench instances.

[not dim]
More information about the usage: [bold green]https://mini-swe-agent.com/latest/usage/swebench/[/bold green]
[/not dim]
"""

app = typer.Typer(rich_markup_mode="rich", add_completion=False)

DATASET_MAPPING = {
    "full": "princeton-nlp/SWE-Bench",
    "verified": "princeton-nlp/SWE-Bench_Verified",
    "verified-40": "verified-40",
    "verified-45": "verified-45",
    "verified-50": "verified-50",
    "verified-45-extra": "verified-45-extra",
    "verified-50-extra": "verified-50-extra",
    "lite": "princeton-nlp/SWE-Bench_Lite",
    "multimodal": "princeton-nlp/SWE-Bench_Multimodal",
    "multilingual": "swe-bench/SWE-Bench_Multilingual",
    "smith": "SWE-bench/SWE-smith",
    "_test": "klieret/swe-bench-dummy-test-dataset",
}

VERIFIED_40 = [
    "django__django-15315",
    "django__django-11333",
    "matplotlib__matplotlib-20826",
    "django__django-11532",
    "django__django-14855",
    "sphinx-doc__sphinx-8721",
    "sympy__sympy-13615",
    "django__django-13089",
    "django__django-15987",
    "pytest-dev__pytest-7982",
    "django__django-15280",
    "scikit-learn__scikit-learn-13142",
    "pytest-dev__pytest-5809",
    "matplotlib__matplotlib-23299",
    "django__django-16560",
    "django__django-15103",
    "django__django-14007",
    "psf__requests-2317",
    "django__django-11880",
    "django__django-16136",
    "django__django-16661",
    "sympy__sympy-17139",
    "sympy__sympy-14531",
    "sphinx-doc__sphinx-8595",
    "django__django-10880",
    "sympy__sympy-19346",
    "django__django-11265",
    "matplotlib__matplotlib-25332",
    "pydata__xarray-6461",
    "sympy__sympy-15017",
    "django__django-13417",
    "matplotlib__matplotlib-24870",
    "django__django-15368",
    "django__django-11095",
    "pydata__xarray-6992",
    "django__django-15863",
    "django__django-13363",
    "sympy__sympy-13852",
    "django__django-14017",
    "pylint-dev__pylint-4661",
]
VERIFIED_45_EXTRA = [
    "pylint-dev__pylint-4604",
    "django__django-14725",
    "pydata__xarray-6744",
    "django__django-16642",
    "sympy__sympy-22080",
]
VERIFIED_50_EXTRA = [
    "django__django-15554",
    "scikit-learn__scikit-learn-13135",
    "sphinx-doc__sphinx-9229",
    "sympy__sympy-14248",
    "sympy__sympy-16792",
]


_OUTPUT_FILE_LOCK = threading.Lock()


class ProgressTrackingAgent(DefaultAgent):
    """Simple wrapper around DefaultAgent that provides progress updates."""

    def __init__(self, *args, progress_manager: RunBatchProgressManager, instance_id: str = "", **kwargs):
        super().__init__(*args, **kwargs)
        self.progress_manager: RunBatchProgressManager = progress_manager
        self.instance_id = instance_id

    def step(self) -> dict:
        """Override step to provide progress updates."""
        self.progress_manager.update_instance_status(
            self.instance_id, f"Step {self.model.n_calls + 1:3d} (${self.model.cost:.2f})"
        )
        return super().step()


def get_swebench_docker_image_name(instance: dict) -> str:
    """Get the image name for a SWEBench instance."""
    image_name = instance.get("image_name", None)
    if image_name is None:
        # Docker doesn't allow double underscore, so we replace them with a magic token
        iid = instance["instance_id"]
        id_docker_compatible = iid.replace("__", "_1776_")
        image_name = f"docker.io/swebench/sweb.eval.x86_64.{id_docker_compatible}:latest".lower()
    return image_name


def get_sb_environment(config: dict, instance: dict) -> Environment:
    env_config = config.setdefault("environment", {})
    env_config["environment_class"] = env_config.get("environment_class", "docker")
    image_name = get_swebench_docker_image_name(instance)
    if env_config["environment_class"] == "docker":
        env_config["image"] = image_name
    elif env_config["environment_class"] == "singularity":
        env_config["image"] = "docker://" + image_name
    env = get_environment(env_config)
    if startup_command := config.get("run", {}).get("env_startup_command"):
        startup_command = Template(startup_command, undefined=StrictUndefined).render(**instance)
        out = env.execute(startup_command)
        if out["returncode"] != 0:
            raise RuntimeError(f"Error executing startup command: {out}")
    return env


_JUNK_NAME = re.compile(r"^(reproduce\w*|run_test|test_fix|apply_patch|mock_query)\.py$")


def _is_junk_diff_path(path: str, header: str) -> bool:
    """Drop reproduction scripts, generated files, and new files left at the repo root."""
    if path.startswith("_build/") or "/_build/" in path:
        return True
    if path.endswith((".doctree", ".pyc", ".png", ".so")):
        return True
    name = path.rsplit("/", 1)[-1]
    if _JUNK_NAME.match(name):
        return True
    new_file = any(line.startswith("new file mode ") for line in header.splitlines()[:8])
    return new_file and "/" not in path


def sanitize_submission_patch(text: str) -> str:
    """Keep source diffs and drop scratch files that make a submission fail to apply."""
    if not text or "diff --git " not in text:
        return ""
    parts = re.split(r"(?=^diff --git )", text, flags=re.M)
    kept: list[str] = []
    for part in parts:
        if not part.startswith("diff --git "):
            continue
        first = part.splitlines()[0]
        match = re.match(r"diff --git a/(.+?) b/(.+)$", first)
        path = match.group(1) if match else ""
        if _is_junk_diff_path(path, part):
            continue
        kept.append(part if part.endswith("\n") else part + "\n")
    return "".join(kept)


def recover_tracked_patch(env: Environment) -> str:
    """Read the diff of tracked files when the agent exits without a submission."""
    try:
        output = env.execute("git diff HEAD")
    except Exception:
        return ""
    if output.get("returncode") != 0:
        return ""
    return sanitize_submission_patch(output.get("output") or "")


def finalize_submission(result: str, env: Environment | None, exit_status: str) -> tuple[str, str]:
    """Return a source patch, recovering one from the worktree when the agent did not submit."""
    cleaned = sanitize_submission_patch(result)
    if cleaned:
        return cleaned, exit_status
    had_patch = "diff --git " in (result or "")
    stopped_early = exit_status in {"LimitsExceeded", "ModelResponseError"}
    should_recover = had_patch or not (result or "").strip() or stopped_early
    if not should_recover or env is None:
        return result, exit_status
    recovered = recover_tracked_patch(env)
    if recovered:
        return recovered, "RecoveredPatch"
    return ("" if had_patch or stopped_early else result), exit_status


def update_preds_file(output_path: Path, instance_id: str, model_name: str, result: str):
    """Update the output JSON file with results from a single instance."""
    with _OUTPUT_FILE_LOCK:
        output_data = {}
        if output_path.exists():
            output_data = json.loads(output_path.read_text())
        output_data[instance_id] = {
            "model_name_or_path": model_name,
            "instance_id": instance_id,
            "model_patch": result,
        }
        output_path.write_text(json.dumps(output_data, indent=2))


def remove_from_preds_file(output_path: Path, instance_id: str):
    """Remove an instance from the predictions file."""
    if not output_path.exists():
        return
    with _OUTPUT_FILE_LOCK:
        output_data = json.loads(output_path.read_text())
        if instance_id in output_data:
            del output_data[instance_id]
            output_path.write_text(json.dumps(output_data, indent=2))


def process_instance(
    instance: dict,
    output_dir: Path,
    config: dict,
    progress_manager: RunBatchProgressManager,
    run_id: str = "",
) -> None:
    """Process a single SWEBench instance."""
    instance_id = instance["instance_id"]
    instance_dir = output_dir / instance_id
    # avoid inconsistent state if something here fails and there's leftover previous files
    remove_from_preds_file(output_dir / "preds.json", instance_id)
    (instance_dir / f"{instance_id}.traj.json").unlink(missing_ok=True)
    config = copy.deepcopy(config)
    model = get_model(config=config.get("model", {}))
    task = instance["problem_statement"]

    progress_manager.on_instance_start(instance_id)
    progress_manager.update_instance_status(instance_id, "Pulling/starting docker")

    agent = None
    extra_info = None
    env = None

    try:
        env = get_sb_environment(config, instance)
        agent = ProgressTrackingAgent(
            model,
            env,
            progress_manager=progress_manager,
            instance_id=instance_id,
            **config.get("agent", {}),
        )
        exit_status, result = agent.run(task)
        extra_info = {"agent_exit_status": exit_status}
        result, exit_status = finalize_submission(result, env, exit_status)
    except Exception as e:
        logger.error(f"Error processing instance {instance_id}: {e}", exc_info=True)
        exit_status, result = type(e).__name__, str(e)
        extra_info = {"traceback": traceback.format_exc()}
        recovered, recovered_status = finalize_submission("", env, exit_status)
        if recovered:
            result, exit_status = recovered, recovered_status
    finally:
        save_traj(
            agent,
            instance_dir / f"{instance_id}.traj.json",
            exit_status=exit_status,
            result=result,
            extra_info=extra_info,
            instance_id=instance_id,
            run_id=run_id,
            print_fct=logger.info,
        )
        update_preds_file(output_dir / "preds.json", instance_id, model.config.model_name, result)
        progress_manager.on_instance_end(instance_id, exit_status)


def load_verified_instances(variant: str) -> list[dict]:
    """Load verified instances for the specified variant.

    Args:
        variant: One of "verified-40", "verified-45", "verified-50",
                "verified-45-extra", "verified-50-extra"
    """
    # Define the mapping of variants to instance lists
    variant_mapping = {
        "verified-40": VERIFIED_40,
        "verified-45": VERIFIED_40 + VERIFIED_45_EXTRA,
        "verified-50": VERIFIED_40 + VERIFIED_45_EXTRA + VERIFIED_50_EXTRA,
        "verified-45-extra": VERIFIED_45_EXTRA,
        "verified-50-extra": VERIFIED_50_EXTRA,
    }

    if variant not in variant_mapping:
        raise ValueError(f"Unknown variant: {variant}. Available variants: {list(variant_mapping.keys())}")

    instance_ids = variant_mapping[variant]
    verified_instances = list(load_hf_dataset("princeton-nlp/SWE-Bench_Verified", "test"))
    filtered_instances = [instance for instance in verified_instances if instance["instance_id"] in instance_ids]

    return filtered_instances


def filter_instances(
    instances: list[dict], *, filter_spec: str, slice_spec: str = "", shuffle: bool = False
) -> list[dict]:
    """Filter and slice a list of SWEBench instances."""
    if shuffle:
        instances = sorted(instances.copy(), key=lambda x: x["instance_id"])
        random.seed(42)
        random.shuffle(instances)
    before_filter = len(instances)
    instances = [instance for instance in instances if re.match(filter_spec, instance["instance_id"])]
    if (after_filter := len(instances)) != before_filter:
        logger.info(f"Instance filter: {before_filter} -> {after_filter} instances")
    if slice_spec:
        values = [int(x) if x else None for x in slice_spec.split(":")]
        instances = instances[slice(*values)]
        if (after_slice := len(instances)) != before_filter:
            logger.info(f"Instance slice: {before_filter} -> {after_slice} instances")
    return instances


# fmt: off
@app.command(help=_HELP_TEXT)
def main(
    subset: Annotated[str, typer.Option("--subset", help="SWEBench subset to use or path to a dataset", rich_help_panel="Data selection")] = "lite",
    split: Annotated[str, typer.Option("--split", help="Dataset split", rich_help_panel="Data selection")] = "dev",
    slice_spec: Annotated[str, typer.Option("--slice", help="Slice specification (e.g., '0:5' for first 5 instances)", rich_help_panel="Data selection")] = "",
    filter_spec: Annotated[str, typer.Option("--filter", help="Filter instance IDs by regex", rich_help_panel="Data selection")] = "",
    shuffle: Annotated[bool, typer.Option("--shuffle", help="Shuffle instances", rich_help_panel="Data selection")] = False,
    output: Annotated[str, typer.Option("-o", "--output", help="Output directory", rich_help_panel="Basic")] = "",
    workers: Annotated[int, typer.Option("-w", "--workers", help="Number of worker threads for parallel processing", rich_help_panel="Basic")] = 1,
    model: Annotated[str | None, typer.Option("-m", "--model", help="Model to use", rich_help_panel="Basic")] = None,
    model_class: Annotated[str | None, typer.Option("--model-class", help="Model class to use (e.g., 'anthropic' or 'minisweagent.models.anthropic.AnthropicModel')", rich_help_panel="Advanced")] = None,
    redo_existing: Annotated[bool, typer.Option("--redo-existing", help="Redo existing instances", rich_help_panel="Data selection")] = False,
    config_spec: Annotated[Path, typer.Option("-c", "--config", help="Path to a config file", rich_help_panel="Basic")] = builtin_config_dir / "extra" / "swebench.yaml",
    environment_class: Annotated[str | None, typer.Option("--environment-class", help="Environment type to use. Recommended are docker or singularity", rich_help_panel="Advanced")] = None,
    instance_ids: Annotated[Path | None, typer.Option("--instance-ids", help="JSON list fixing the task IDs and their order.", exists=True, dir_okay=False)] = None,
) -> None:
    # fmt: on
    output_path = Path(output)
    output_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Results will be saved to {output_path}")
    add_file_handler(output_path / "minisweagent.log")

    dataset_path = DATASET_MAPPING.get(subset, subset)
    if subset in ["verified-40", "verified-45", "verified-50", "verified-45-extra", "verified-50-extra"]:
        logger.info(f"Loading {subset} instances (using split test)...")
        instances = load_verified_instances(subset)
    else:
        logger.info(f"Loading dataset {dataset_path}, split {split}...")
        instances = list(load_hf_dataset(dataset_path, split))

    if instance_ids is not None:
        pinned_ids = json.loads(instance_ids.read_text())
        if not isinstance(pinned_ids, list) or not all(isinstance(i, str) for i in pinned_ids) or len(set(pinned_ids)) != len(pinned_ids):
            raise ValueError("--instance-ids must contain a JSON list of unique instance ID strings.")
        by_id = {instance["instance_id"]: instance for instance in instances}
        if missing := set(pinned_ids) - by_id.keys():
            raise ValueError(f"Pinned tasks are missing from the dataset: {sorted(missing)}")
        instances = [by_id[instance_id] for instance_id in pinned_ids]
    instances = filter_instances(instances, filter_spec=filter_spec, slice_spec=slice_spec, shuffle=shuffle)
    selected_ids = [instance["instance_id"] for instance in instances]
    selected_tasks = sorted(
        [{key: instance.get(key) for key in ("instance_id", "repo", "base_commit", "version", "problem_statement")} for instance in instances],
        key=lambda task: task["instance_id"],
    )
    if not redo_existing and (output_path / "preds.json").exists():
        existing_instances = list(json.loads((output_path / "preds.json").read_text()).keys())
        logger.info(f"Skipping {len(existing_instances)} existing instances")
        instances = [instance for instance in instances if instance["instance_id"] not in existing_instances]
    logger.info(f"Running on {len(instances)} instances...")


    config = yaml.safe_load(get_config_path(config_spec).read_text())
    if environment_class is not None:
        config.setdefault("environment", {})["environment_class"] = environment_class
    if model is not None:
        config.setdefault("model", {})["model_name"] = model
    if model_class is not None:
        config.setdefault("model", {})["model_class"] = model_class

    manifest = write_manifest(output_path, config, selected_ids, workers, selected_tasks)
    progress_manager = RunBatchProgressManager(len(instances), output_path / f"exit_statuses_{time.time()}.yaml")

    def process_futures(futures: dict[concurrent.futures.Future, str]):
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except concurrent.futures.CancelledError:
                pass
            except Exception as e:
                instance_id = futures[future]
                logger.error(f"Error in future for instance {instance_id}: {e}", exc_info=True)
                progress_manager.on_uncaught_exception(instance_id, e)

    with Live(progress_manager.render_group, refresh_per_second=4):
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(process_instance, instance, output_path, config, progress_manager, manifest["run_id"]): instance[
                    "instance_id"
                ]
                for instance in instances
            }
            try:
                process_futures(futures)
            except KeyboardInterrupt:
                logger.info("Cancelling all pending jobs. Press ^C again to exit immediately.")
                for future in futures:
                    if not future.running() and not future.done():
                        future.cancel()
                process_futures(futures)


if __name__ == "__main__":
    app()
