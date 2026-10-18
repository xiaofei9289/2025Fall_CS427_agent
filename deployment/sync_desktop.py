"""Sync committed code from the Mac to the desktop test workspace.

The Mac is the editing and source-of-truth side; the desktop only runs tests. This
script refuses to sync a dirty tree, packages the tracked code/tests/deployment and
the experiment configs (not their results), copies the archive, and asks the desktop
to replace its code directories and verify the same source fingerprint used by
run_manifest.json.

Example:
    python deployment/sync_desktop.py --target D:/cs427-workspace
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLY = ROOT / "deployment" / "desktop_sync_apply.py"
DEFAULT_HOST = "desktop-pc"
DEFAULT_TARGET = "D:/cs427-workspace"
DEFAULT_REMOTE_TAR = "C:/Users/Administrator/AppData/Local/Temp/cs427-sync.tar"
TOP_LEVEL = {
    ".dockerignore",
    ".gitignore",
    "LICENSE.md",
    "README.md",
    "cs427_memory.md",
    "cs427_tools_extension.md",
    "mkdocs.yml",
    "pyproject.toml",
    "uv.lock",
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def source_fingerprint() -> tuple[str, int]:
    package = ROOT / "src" / "minisweagent"
    files = sorted(p for p in package.rglob("*") if p.suffix in {".py", ".yaml", ".tcss"})
    files += [ROOT / name for name in ("pyproject.toml", "README.md", "LICENSE.md", "uv.lock")
              if (ROOT / name).is_file()]
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.relative_to(ROOT).as_posix().encode() + b"\0" + file.read_bytes() + b"\0")
    return digest.hexdigest(), len(files)


def wanted(path: str) -> bool:
    """Code, tests, deployment, docs, and experiment configs; never run artifacts."""
    if path in TOP_LEVEL:
        return True
    parts = path.split("/")
    if parts[0] in {"src", "tests", "deployment", "docs", "SWE-bench"}:
        return True
    if parts[0] != "experiments":
        return False
    if path == "experiments/PLAN.md":
        return True
    if len(parts) != 3:
        return False
    name = parts[2]
    if parts[1] == "configs":
        return True
    return (
        name in {
            "README.md", "desktop.py", "evaluate.py", "model_prices.json",
            "run.py", "run_all.py", "tokenfy_model_registry.json",
        }
        or name.endswith((".yaml", ".yml"))
        or fnmatch.fnmatch(name, "tasks*.json")
        or fnmatch.fnmatch(name, "smoke_*.py")
        or name.startswith("Dockerfile")
    )


def selected_files() -> list[str]:
    tracked = [path for path in git("ls-files", "-z").split("\0") if path]
    files = sorted({path for path in tracked if wanted(path)} | {"uv.lock"})
    if not (ROOT / "uv.lock").is_file():
        raise SystemExit("uv.lock is missing; it is part of the manifest fingerprint.")
    return files


def build_archive(path: Path, files: list[str], fingerprint: str, count: int, commit: str) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name in files:
            archive.add(ROOT / name, arcname=name, recursive=False)
        manifest = {
            "git_commit": commit,
            "source_sha256": fingerprint,
            "source_files": count,
            "tar_files": len(files),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        payload = json.dumps(manifest, indent=2).encode()
        info = tarfile.TarInfo("sync_manifest.json")
        info.size, info.mtime, info.mode = len(payload), int(time.time()), 0o644
        archive.addfile(info, io.BytesIO(payload))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--remote-tar", default=DEFAULT_REMOTE_TAR)
    args = parser.parse_args()

    status = [line for line in git("status", "--porcelain", "-uall").splitlines()
              if line.strip() and line.strip() != "?? uv.lock"]
    if status:
        raise SystemExit("Commit or stash these changes first:\n" + "\n".join(status))

    fingerprint, count = source_fingerprint()
    commit = git("rev-parse", "HEAD").strip()
    files = selected_files()
    handle = tempfile.NamedTemporaryFile(prefix="cs427-sync-", suffix=".tar.gz", delete=False)
    archive_path = Path(handle.name)
    handle.close()
    try:
        build_archive(archive_path, files, fingerprint, count, commit)
        print(f"archive: {len(files)} files, {archive_path.stat().st_size / 1048576:.1f} MB")
        print(f"source.sha256: {fingerprint}")
        subprocess.run(["scp", "-q", str(archive_path), f"{args.host}:{args.remote_tar}"], check=True)
        command = ["ssh", args.host, "python", "-", "--target", args.target, "--tar", args.remote_tar]
        completed = subprocess.run(command, input=APPLY.read_bytes(), capture_output=True)
        if completed.returncode:
            sys.stderr.write(completed.stderr.decode(errors="replace"))
            raise SystemExit(completed.returncode)
        result = json.loads(completed.stdout.decode().strip().splitlines()[-1])
        print(json.dumps(result, indent=2))
        if result["source_sha256"] != fingerprint:
            raise SystemExit(
                f"Fingerprint mismatch: Mac {fingerprint[:16]} vs desktop {result['source_sha256'][:16]}"
            )
        if result.get("git_commit") != commit:
            raise SystemExit("Commit mismatch between the archive and its manifest.")
    finally:
        archive_path.unlink(missing_ok=True)

    print(f"\nSynced {commit[:12]} to {args.host}:{args.target}")
    print("Next on the desktop:")
    print(f"  ssh {args.host} \"cd {args.target}; python deployment/desktop_run.py checks\"")


if __name__ == "__main__":
    main()
