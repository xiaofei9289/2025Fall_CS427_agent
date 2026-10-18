"""Apply a workspace tar to the desktop test copy and verify the source fingerprint.

Runs on the desktop (Windows) with `python - --target ... --tar ...`; the Mac-side
launcher `deployment/sync_desktop.py` supplies the tar and parses the JSON result.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
from pathlib import Path

CODE_DIRS = ("src", "tests", "deployment", "SWE-bench", "docs")


def source_fingerprint(root: Path) -> tuple[str, int]:
    """The same fingerprint used by run_manifest.json (POSIX paths)."""
    package = root / "src" / "minisweagent"
    files = sorted(p for p in package.rglob("*") if p.suffix in {".py", ".yaml", ".tcss"})
    names = ("pyproject.toml", "README.md", "LICENSE.md", "uv.lock")
    files += [root / name for name in names if (root / name).is_file()]
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.relative_to(root).as_posix().encode() + b"\0" + file.read_bytes() + b"\0")
    return digest.hexdigest(), len(files)


def apply_tar(tar_path: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            destination = (target / member.name).resolve()
            if not destination.is_relative_to(target.resolve()):
                raise SystemExit(f"Unsafe tar member: {member.name}")
            if member.issym() or member.islnk():
                raise SystemExit(f"Refusing link member: {member.name}")
        for name in CODE_DIRS:
            path = target / name
            if path.exists():
                shutil.rmtree(path)
        archive.extractall(target)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--tar", required=True, type=Path)
    args = parser.parse_args()
    apply_tar(args.tar, args.target)
    manifest = json.loads((args.target / "sync_manifest.json").read_text(encoding="utf-8"))
    actual, count = source_fingerprint(args.target)
    result = {
        "target": str(args.target),
        "git_commit": manifest.get("git_commit"),
        "source_sha256": actual,
        "source_files": count,
        "source_matches": actual == manifest.get("source_sha256"),
        "synced_at": manifest.get("created_at"),
    }
    print(json.dumps(result))
    args.tar.unlink(missing_ok=True)
    if not result["source_matches"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
