"""Capture configuration and source identity for controlled SWE-bench runs."""

import hashlib
import json
import platform
import subprocess
import uuid
import zipfile
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from minisweagent import __version__, package_dir


def write_manifest(
    output: Path, config: dict, instance_ids: list[str], workers: int, tasks: list[dict] | None = None
) -> dict:
    path = output / "run_manifest.json"
    source_root = package_dir.parent.parent
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=source_root, capture_output=True, text=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=source_root, capture_output=True, text=True)
    files = sorted(p for p in package_dir.rglob("*") if p.suffix in {".py", ".yaml", ".tcss"})
    files += [
        source_root / name
        for name in ("pyproject.toml", "README.md", "LICENSE.md", "uv.lock")
        if (source_root / name).is_file()
    ]
    contents = {str(file.relative_to(source_root)): file.read_bytes() for file in files}
    digest = hashlib.sha256()
    for name, content in contents.items():
        digest.update(name.encode() + b"\0" + content + b"\0")
    source = {
        "git_commit": revision.stdout.strip() or None,
        "git_dirty": bool(status.stdout.strip()),
        "sha256": digest.hexdigest(),
    }
    if path.exists():
        manifest = json.loads(path.read_text())
        if (
            manifest["config"] != config
            or manifest["instance_ids"] != sorted(instance_ids)
            or manifest.get("tasks") != tasks
            or manifest["workers"] != workers
        ):
            raise ValueError("Run configuration or task IDs changed (including workers); use a new output directory.")
        if source["sha256"] != manifest["source"]["sha256"]:
            raise ValueError("Source changed since this run started; use a new output directory.")
        return manifest
    if (output / "preds.json").exists():
        raise ValueError("Existing predictions have no run manifest; use a new output directory.")
    manifest = {
        "run_id": uuid.uuid4().hex,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "instance_ids": sorted(instance_ids),
        "tasks": tasks,
        "workers": workers,
        "source": source,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "mini_version": __version__,
        "dependencies": {name: version(name) for name in ("litellm", "datasets", "pyyaml")},
    }
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output / "source.zip", "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
