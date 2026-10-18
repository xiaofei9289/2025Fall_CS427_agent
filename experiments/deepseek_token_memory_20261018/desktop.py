"""Launch both token-budget arms from one frozen source copy."""

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
from pathlib import Path


def source_digest(root: Path) -> str:
    """The manifest's source fingerprint, computed over the shared snapshot set."""
    pkg = root / "src" / "minisweagent"
    files = sorted(p for p in pkg.rglob("*") if p.suffix in {".py", ".yaml", ".tcss"})
    files += [root / n for n in ("pyproject.toml", "README.md", "LICENSE.md", "uv.lock") if (root / n).is_file()]
    digest = hashlib.sha256()
    for f in files:
        digest.update(str(f.relative_to(root)).replace("\\", "/").encode() + b"\0" + f.read_bytes() + b"\0")
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("generation", "grading", "compare", "all"))
    parser.add_argument("--arm", choices=("off", "on", "both"), default="both")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if platform.system() != "Windows":
        raise SystemExit("Run this launcher on the Windows desktop.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    frozen = root / "desktop_validation" / f"frozen-{study.name}"
    phases = ("generation", "grading", "compare") if args.phase == "all" else (args.phase,)
    digest = source_digest(root)
    if "generation" in phases and not frozen.exists():
        frozen.mkdir(parents=True)
        shutil.copytree(root / "src", frozen / "src")
        for name in ("pyproject.toml", "README.md", "LICENSE.md", "uv.lock"):
            if (root / name).is_file():
                shutil.copy2(root / name, frozen / name)
        (frozen / "SWE-bench").mkdir()
        (frozen / "experiments" / study.name).mkdir(parents=True)
        print(f"Frozen source copy: {frozen} (digest {digest[:16]})", flush=True)
    elif not frozen.exists():
        raise SystemExit(f"{frozen} is missing; run generation first.")
    if source_digest(frozen) != digest:
        raise SystemExit(f"Frozen digest differs from the desktop repo {digest[:16]}; use a new study directory.")
    if frozen.exists() and "generation" in phases:
        print(f"Using frozen source copy: {frozen} (digest {digest[:16]})", flush=True)
    env = os.environ | {
        "DOCKER_HOST": "npipe:////./pipe/dockerDesktopLinuxEngine",
        "DOCKER_CONFIG": str(root / "desktop_validation" / "docker-config"),
    }
    subprocess.run(["docker", "info", "--format", "{{.OSType}}"], env=env, check=True)
    image = subprocess.run(
        ["docker", "image", "inspect", "cs427-validation:local"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if image.returncode:
        raise SystemExit("The existing cs427-validation:local image must be restored or built before evaluation.")
    if "generation" in phases or "grading" in phases:
        key = os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            import winreg

            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as settings:
                    key = winreg.QueryValueEx(settings, "DEEPSEEK_API_KEY")[0]
            except FileNotFoundError:
                pass
        if not key:
            raise SystemExit("Configure DEEPSEEK_API_KEY; no model calls started.")
        env["DEEPSEEK_API_KEY"] = key
    mounts = [
        "--mount",
        f"type=bind,source={frozen},target=/workspace,readonly",
        "--mount",
        f"type=bind,source={study},target=/workspace/experiments/{study.name}",
        "--mount",
        f"type=bind,source={root / 'SWE-bench'},target=/workspace/SWE-bench,readonly",
        "--mount",
        "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock",
        "--mount",
        "type=volume,source=cs427-hf-cache,target=/hf-cache",
    ]
    for phase in phases:
        command = [
            "docker",
            "run",
            "--rm",
            "--entrypoint=",
            *mounts,
            "-w",
            "/workspace",
            "-e",
            "PYTHONPATH=/workspace/src:/workspace/SWE-bench",
            "-e",
            "MSWEA_SILENT_STARTUP=1",
            "-e",
            "MSWEA_GLOBAL_CONFIG_DIR=/tmp/cs427-config",
            "-e",
            "HF_HOME=/hf-cache",
        ]
        if phase in {"generation", "grading"}:
            command += ["-e", "DEEPSEEK_API_KEY"]
        command += [
            "cs427-validation:local",
            "python",
            f"experiments/{study.name}/run.py",
            phase,
            "--arm",
            args.arm,
            "--workers",
            str(args.workers),
        ]
        print(f"Running {phase} in the desktop Linux engine", flush=True)
        subprocess.run(command, cwd=root, env=env, check=True)


if __name__ == "__main__":
    main()
