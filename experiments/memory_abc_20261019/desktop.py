"""Windows desktop launcher for the A/B/C study.

It freezes the source once, verifies the digest, and runs the study inside the
existing Linux container image.  The API key is read from the Windows user
environment and passed only as a process environment variable; it is never
written to disk.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
from pathlib import Path

STUDY_NAME = "memory_abc_20261019"


def source_digest(root: Path) -> str:
    """Digest the same source set the run manifest records."""
    package = root / "src" / "minisweagent"
    files = sorted(path for path in package.rglob("*") if path.suffix in {".py", ".yaml", ".tcss"})
    files += [root / name for name in ("pyproject.toml", "README.md", "LICENSE.md", "uv.lock") if (root / name).is_file()]
    digest = hashlib.sha256()
    for file in files:
        digest.update(str(file.relative_to(root)).replace("\\", "/").encode() + b"\0" + file.read_bytes() + b"\0")
    return digest.hexdigest()


def api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as settings:
            return winreg.QueryValueEx(settings, "DEEPSEEK_API_KEY")[0]
    except FileNotFoundError as error:
        raise SystemExit("Configure DEEPSEEK_API_KEY; no model calls started.") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("generation", "grading", "compare", "all"))
    parser.add_argument("--arm", choices=("a", "b", "c", "all"), default="all")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--tag", default=None)
    parser.add_argument("--round", default=None)
    parser.add_argument("--rounds", default=None)
    parser.add_argument("--arms", default="a,b,c")
    parser.add_argument("--a-tag", default=None)
    parser.add_argument("--b-tag", default=None)
    parser.add_argument("--c-tag", default=None)
    parser.add_argument("--tasks", default=None, help="task-list JSON for a focused rerun")
    parser.add_argument("--redo", action="store_true", help="overwrite an existing tag")
    parser.add_argument("--sham-search", action="store_true", help="C control: install memory_search but return no matches")
    args = parser.parse_args()
    if platform.system() != "Windows":
        raise SystemExit("Run this launcher on the Windows desktop.")

    study = Path(__file__).resolve().parent
    root = study.parents[1]
    assert study.name == STUDY_NAME
    digest = source_digest(root)
    # Freeze per source version so a Mac edit + sync produces a new clean copy
    # instead of being blocked by an old frozen snapshot.
    frozen = root / "desktop_validation" / f"frozen-{STUDY_NAME}-{digest[:12]}"
    phases = ("generation", "grading", "compare") if args.phase == "all" else (args.phase,)

    if "generation" in phases and not frozen.exists():
        frozen.mkdir(parents=True)
        shutil.copytree(root / "src", frozen / "src")
        for name in ("pyproject.toml", "README.md", "LICENSE.md", "uv.lock"):
            if (root / name).is_file():
                shutil.copy2(root / name, frozen / name)
        print(f"Frozen source copy: {frozen} (digest {digest[:16]})", flush=True)
    elif not frozen.exists():
        raise SystemExit(f"{frozen} is missing; run generation first.")
    if source_digest(frozen) != digest:
        raise SystemExit(f"Frozen digest differs from the desktop repo {digest[:16]}; use a new study directory.")
    # Mountpoints must exist under the read-only frozen mount before Docker can
    # bind the study and SWE-bench directories on top of them.
    (frozen / "SWE-bench").mkdir(exist_ok=True)
    (frozen / "experiments" / STUDY_NAME).mkdir(parents=True, exist_ok=True)

    docker_env = os.environ | {"DOCKER_HOST": "npipe:////./pipe/dockerDesktopLinuxEngine"}
    docker_config = root / "desktop_validation" / "docker-config"
    if docker_config.is_dir():
        docker_env["DOCKER_CONFIG"] = str(docker_config)
    subprocess.run(["docker", "info", "--format", "{{.OSType}}"], env=docker_env, check=True)
    image = subprocess.run(
        ["docker", "image", "inspect", "cs427-validation:local"],
        env=docker_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if image.returncode:
        raise SystemExit("The cs427-validation:local image must be restored or built before evaluation.")

    key = api_key() if {"generation", "grading"} & set(phases) else ""
    env = docker_env | {
        "DEEPSEEK_API_KEY": key,
        "MSWEA_MODEL_API_KEY": key,
        "MSWEA_GLOBAL_COST_LIMIT": "0",
        "PYTHONPATH": "/workspace/src:/workspace/SWE-bench",
        "MSWEA_SILENT_STARTUP": "1",
        "MSWEA_GLOBAL_CONFIG_DIR": "/tmp/cs427-config",
        "HF_HOME": "/hf-cache",
        "MSWEA_MEMORY_SHAM": "1" if args.sham_search else "0",
    }
    mounts = [
        "--mount",
        f"type=bind,source={frozen},target=/workspace,readonly",
        "--mount",
        f"type=bind,source={study},target=/workspace/experiments/{STUDY_NAME}",
        "--mount",
        f"type=bind,source={root / 'SWE-bench'},target=/workspace/SWE-bench,readonly",
        "--mount",
        "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock",
        "--mount",
        "type=volume,source=cs427-hf-cache,target=/hf-cache",
    ]
    command = [
        "docker",
        "run",
        "--rm",
        "--entrypoint=",
        *mounts,
        "-w",
        "/workspace",
        "-e",
        "PYTHONPATH",
        "-e",
        "MSWEA_SILENT_STARTUP",
        "-e",
        "MSWEA_GLOBAL_CONFIG_DIR",
        "-e",
        "MSWEA_MODEL_API_KEY",
        "-e",
        "MSWEA_GLOBAL_COST_LIMIT",
        "-e",
        "DEEPSEEK_API_KEY",
        "-e",
        "HF_HOME",
        "-e",
        "MSWEA_MEMORY_SHAM",
        "cs427-validation:local",
        "python",
        f"experiments/{STUDY_NAME}/run.py",
        args.phase,
        "--arm",
        args.arm,
        "--workers",
        str(args.workers),
    ]
    if args.pilot:
        command.append("--pilot")
    if args.tag:
        command += ["--tag", args.tag]
    if args.round:
        command += ["--round", args.round]
    if args.rounds:
        command += ["--rounds", args.rounds]
    for flag, value in (("--a-tag", args.a_tag), ("--b-tag", args.b_tag), ("--c-tag", args.c_tag)):
        if value:
            command += [flag, value]
    if args.arms:
        command += ["--arms", args.arms]
    if args.tasks:
        command += ["--tasks", args.tasks]
    if args.redo:
        command.append("--redo")
    print("Running in the desktop Linux engine", flush=True)
    subprocess.run(command, cwd=root, env=env, check=True)


if __name__ == "__main__":
    main()
