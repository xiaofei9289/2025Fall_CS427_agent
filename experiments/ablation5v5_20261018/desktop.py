"""Desktop launcher for the four-arm retrieval/tool ablation."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
from pathlib import Path

STUDY_NAME = "ablation5v5_20261018"


def source_digest(root: Path) -> str:
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
    if platform.system() != "Windows":
        raise SystemExit("Run this launcher on the Windows desktop.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    assert study.name == STUDY_NAME
    digest = source_digest(root)
    frozen = root / "desktop_validation" / f"frozen-{STUDY_NAME}-{digest[:12]}"
    if not frozen.exists():
        frozen.mkdir(parents=True)
        shutil.copytree(root / "src", frozen / "src")
        for name in ("pyproject.toml", "README.md", "LICENSE.md", "uv.lock"):
            if (root / name).is_file():
                shutil.copy2(root / name, frozen / name)
        print(f"Frozen source copy: {frozen} (digest {digest[:16]})", flush=True)
    if source_digest(frozen) != digest:
        raise SystemExit(f"Frozen digest differs from the desktop repo {digest[:16]}; use a new study directory.")
    (frozen / "SWE-bench").mkdir(exist_ok=True)
    (frozen / "experiments" / STUDY_NAME).mkdir(parents=True, exist_ok=True)

    key = api_key()
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

    env = docker_env | {
        "DEEPSEEK_API_KEY": key,
        "MSWEA_MODEL_API_KEY": key,
        "MSWEA_GLOBAL_COST_LIMIT": "0",
        "PYTHONPATH": "/workspace/src:/workspace/SWE-bench",
        "MSWEA_SILENT_STARTUP": "1",
        "MSWEA_GLOBAL_CONFIG_DIR": "/tmp/cs427-config",
        "HF_HOME": "/hf-cache",
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
        "cs427-validation:local",
        "python",
        f"experiments/{STUDY_NAME}/run_four.py",
    ]
    print("Running four-arm ablation in the desktop Linux engine", flush=True)
    subprocess.run(command, cwd=root, env=env, check=True)


if __name__ == "__main__":
    main()
