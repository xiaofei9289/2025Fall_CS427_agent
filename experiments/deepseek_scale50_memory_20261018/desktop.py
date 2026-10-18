"""Launch the memory-on arm of the DeepSeek 50-task comparison with a frozen source copy."""

import argparse
import hashlib
import json
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
    parser.add_argument("--credential-file", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    if platform.system() != "Windows":
        raise SystemExit("Run this launcher on the Windows desktop.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    baseline_study = root / "experiments" / "deepseek_scale50_20261018"
    if not (baseline_study / "baseline_r2" / "run_manifest.json").exists():
        raise SystemExit("The baseline arm has no run manifest; run the baseline first.")
    baseline_sha = json.loads((baseline_study / "baseline_r2" / "run_manifest.json").read_text())["source"]["sha256"]
    frozen = root / "desktop_validation" / f"frozen-{study.name}"
    phases = ("generation", "grading", "compare") if args.phase == "all" else (args.phase,)
    # The on arm must run byte-identical source to the baseline arm.
    if "generation" in phases:
        digest = source_digest(root)
        if digest != baseline_sha:
            raise SystemExit(f"Source digest {digest[:16]} differs from the baseline manifest {baseline_sha[:16]}; "
                             "the desktop repo changed since the baseline; use a new pair of arms.")
        if frozen.exists():
            raise SystemExit(f"{frozen} already exists; delete it before starting a new run.")
        frozen.mkdir(parents=True)
        shutil.copytree(root / "src", frozen / "src")
        for name in ("pyproject.toml", "README.md", "LICENSE.md", "uv.lock"):
            if (root / name).is_file():
                shutil.copy2(root / name, frozen / name)
        # Docker cannot create nested mountpoints inside the readonly /workspace bind.
        (frozen / "SWE-bench").mkdir()
        (frozen / "experiments" / study.name).mkdir(parents=True)
        (frozen / "experiments" / baseline_study.name).mkdir(parents=True)
        print(f"Frozen source copy: {frozen} (digest {digest[:16]})", flush=True)
    else:
        digest = source_digest(frozen)
        if digest != baseline_sha:
            raise SystemExit(f"Frozen digest {digest[:16]} differs from the baseline manifest {baseline_sha[:16]}.")
        print(f"Reusing frozen source copy: {frozen} (digest {digest[:16]})", flush=True)
    env = os.environ | {"DOCKER_HOST": "npipe:////./pipe/dockerDesktopLinuxEngine",
                        "DOCKER_CONFIG": str(root / "desktop_validation" / "docker-config")}
    subprocess.run(["docker", "info", "--format", "{{.OSType}}"], env=env, check=True)
    image = subprocess.run(["docker", "image", "inspect", "cs427-validation:local"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        if args.credential_file:
            from dotenv import dotenv_values

            values = dotenv_values(args.credential_file)
            key = values.get("DEEPSEEK_API_KEY") or values.get("MSWEA_MODEL_API_KEY")
        if not key:
            raise SystemExit("Configure DEEPSEEK_API_KEY or pass --credential-file; no model calls started.")
        env["DEEPSEEK_API_KEY"] = key

    mounts = [
        "--mount", f"type=bind,source={frozen},target=/workspace,readonly",
        "--mount", f"type=bind,source={study},target=/workspace/experiments/{study.name}",
        "--mount", f"type=bind,source={baseline_study},target=/workspace/experiments/{baseline_study.name},readonly",
        "--mount", f"type=bind,source={root / 'SWE-bench'},target=/workspace/SWE-bench,readonly",
        "--mount", "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock",
        "--mount", "type=volume,source=cs427-hf-cache,target=/hf-cache",
    ]
    for phase in phases:
        command = ["docker", "run", "--rm", "--entrypoint=", *mounts, "-w", "/workspace",
                   "-e", "PYTHONPATH=/workspace/src:/workspace/SWE-bench", "-e", "MSWEA_SILENT_STARTUP=1",
                   "-e", "MSWEA_GLOBAL_CONFIG_DIR=/tmp/cs427-config", "-e", "HF_HOME=/hf-cache"]
        if phase in {"generation", "grading"}:
            command += ["-e", "DEEPSEEK_API_KEY"]
        if phase == "grading":
            command += ["-e", "HF_HUB_OFFLINE=1", "-e", "HF_DATASETS_OFFLINE=1"]
        command += ["cs427-validation:local", "python", f"experiments/{study.name}/run.py", phase,
                    "--workers", str(args.workers)]
        print(f"Running {phase} in the desktop Linux engine", flush=True)
        subprocess.run(command, cwd=root, env=env, check=True)


if __name__ == "__main__":
    main()
