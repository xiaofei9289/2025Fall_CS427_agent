"""Launch the memory comparison on the project's Windows desktop and Linux engine."""

import argparse
import os
import platform
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("generation", "grading", "all"))
    parser.add_argument("--credential-file", type=Path)
    args = parser.parse_args()
    if platform.system() != "Windows":
        raise SystemExit("Run this launcher on the Windows desktop.")
    study = Path(__file__).resolve().parent
    root = study.parents[1]
    code = root / "desktop_validation" / "memory-fix-20261018"
    if not (code / "src" / "minisweagent" / "memory" / "history.py").exists():
        raise SystemExit("The repaired source snapshot is missing.")
    env = os.environ | {"DOCKER_HOST": "npipe:////./pipe/dockerDesktopLinuxEngine",
                        "DOCKER_CONFIG": str(root / "desktop_validation" / "docker-config")}
    subprocess.run(["docker", "info", "--format", "{{.OSType}}"], env=env, check=True)
    image = subprocess.run(["docker", "image", "inspect", "cs427-validation:local"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if image.returncode:
        raise SystemExit("The existing cs427-validation:local image must be restored or built before evaluation.")
    phases = ("generation", "grading") if args.phase == "all" else (args.phase,)
    if "generation" in phases:
        import winreg

        key = os.environ.get("TOKENFY_API_KEY")
        if not key:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as settings:
                    key = winreg.QueryValueEx(settings, "TOKENFY_API_KEY")[0]
            except FileNotFoundError:
                pass
        if args.credential_file:
            from dotenv import dotenv_values

            values = dotenv_values(args.credential_file)
            key = values.get("TOKENFY_API_KEY") or values.get("OPENAI_API_KEY") or values.get("MSWEA_MODEL_API_KEY")
        if not key:
            raise SystemExit("Configure TOKENFY_API_KEY or pass the existing TokenFY --credential-file; no model calls started.")
        # The provider reads this environment variable without persisting it in model_kwargs.
        env["OPENAI_API_KEY"] = key

    (code / "experiments" / study.name).mkdir(parents=True, exist_ok=True)
    mounts = [
        "--mount", f"type=bind,source={code},target=/workspace",
        "--mount", f"type=bind,source={study},target=/workspace/experiments/{study.name}",
        "--mount", f"type=bind,source={root / 'SWE-bench'},target=/workspace/SWE-bench,readonly",
        "--mount", "type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock",
        "--mount", "type=volume,source=cs427-hf-cache,target=/hf-cache",
    ]
    for phase in phases:
        command = ["docker", "run", "--rm", "--entrypoint=", *mounts, "-w", "/workspace",
                   "-e", "PYTHONPATH=/workspace/src:/workspace/SWE-bench", "-e", "MSWEA_SILENT_STARTUP=1",
                   "-e", "MSWEA_GLOBAL_CONFIG_DIR=/tmp/cs427-config", "-e", "HF_HOME=/hf-cache",
                   "-e", "HF_HUB_OFFLINE=1"]
        if phase == "generation":
            command += ["-e", "OPENAI_API_KEY"]
        command += ["cs427-validation:local", "python", f"experiments/{study.name}/run.py", phase]
        print(f"Running {phase} in the desktop Linux engine", flush=True)
        subprocess.run(command, cwd=root, env=env, check=True)


if __name__ == "__main__":
    main()
