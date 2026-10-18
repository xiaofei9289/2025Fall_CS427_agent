"""Prepare frozen base-commit checkouts for the five-task localization set.

The checkouts are intentionally ignored by git.  This script makes the archive
reproducible on a new machine and writes a manifest that records the exact
repository URL, base commit, checked-out HEAD, and Python file count.

    python experiments/localization_verified5/prepare_checkouts.py
    python experiments/localization_verified5/prepare_checkouts.py --verify-only

The default cases and output directories are relative to this file.  Set
``--output`` to another ignored directory when you need a second copy.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import typer

app = typer.Typer(add_completion=False)
HERE = Path(__file__).resolve().parent


class PrepareError(RuntimeError):
    """Raised when a checkout cannot be prepared safely."""


def _git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def _head(path: Path) -> str:
    result = _git(["rev-parse", "HEAD"], cwd=path)
    return result.stdout.strip() if result.returncode == 0 else ""


def _python_file_count(path: Path) -> int:
    result = _git(["ls-files", "--", "*.py"], cwd=path)
    return len([line for line in result.stdout.splitlines() if line.strip()]) if result.returncode == 0 else 0


def _load_cases(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if not isinstance(data, list) or not data:
        raise PrepareError(f"Cases file must be a non-empty JSON list: {path}")
    for case in data:
        if not isinstance(case, dict) or not case.get("instance_id") or not case.get("base_commit"):
            raise PrepareError(f"Case is missing instance_id/base_commit: {case!r}")
        if not case.get("repo_url"):
            raise PrepareError(f"Case {case['instance_id']} is missing repo_url")
    return data


def _safe_destination(output: Path, instance_id: str) -> Path:
    destination = (output / instance_id).resolve()
    root = output.resolve()
    if destination == root or root not in destination.parents:
        raise PrepareError(f"Unsafe checkout destination: {destination}")
    return destination


def _clone(case: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    base_commit = case["base_commit"]
    clone = _git(["clone", "--no-checkout", "--filter=blob:none", case["repo_url"], str(destination)])
    if clone.returncode != 0:
        # Hosts that do not support partial clone still support a normal clone.
        shutil.rmtree(destination, ignore_errors=True)
        clone = _git(["clone", "--no-checkout", case["repo_url"], str(destination)])
    if clone.returncode != 0:
        raise PrepareError(f"git clone failed for {case['instance_id']}: {clone.stderr.strip()}")
    fetch = _git(["fetch", "--depth", "1", "origin", base_commit], cwd=destination)
    if fetch.returncode != 0:
        fetch = _git(["fetch", "origin"], cwd=destination)
    if fetch.returncode != 0:
        raise PrepareError(f"git fetch failed for {case['instance_id']}: {fetch.stderr.strip()}")
    checkout = _git(["checkout", "--detach", base_commit], cwd=destination)
    if checkout.returncode != 0:
        raise PrepareError(f"git checkout failed for {case['instance_id']}: {checkout.stderr.strip()}")
    head = _head(destination)
    if head != base_commit:
        raise PrepareError(f"HEAD mismatch for {case['instance_id']}: expected {base_commit}, got {head}")


def _entry(case: dict, destination: Path) -> dict:
    return {
        "instance_id": case["instance_id"],
        "repo_url": case["repo_url"],
        "base_commit": case["base_commit"],
        "head": _head(destination),
        "path": destination.name,
        "python_files": _python_file_count(destination),
    }


def prepare(
    cases_path: Path,
    output: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    verify_only: bool = False,
) -> dict:
    cases = _load_cases(cases_path)
    output = output.resolve()
    entries = []
    for case in cases:
        destination = _safe_destination(output, case["instance_id"])
        if verify_only:
            if not destination.is_dir():
                raise PrepareError(f"Missing checkout: {destination}")
            head = _head(destination)
            if head != case["base_commit"]:
                raise PrepareError(
                    f"Checkout {case['instance_id']} is at {head or '<none>'}, expected {case['base_commit']}"
                )
            entries.append(_entry(case, destination))
            continue
        if dry_run:
            typer.echo(
                f"would clone {case['repo_url']} -> {destination} @ {case['base_commit']}"
            )
            entries.append(
                {
                    "instance_id": case["instance_id"],
                    "repo_url": case["repo_url"],
                    "base_commit": case["base_commit"],
                    "head": None,
                    "path": destination.name,
                    "python_files": None,
                }
            )
            continue
        if destination.exists():
            if _head(destination) == case["base_commit"]:
                entries.append(_entry(case, destination))
                continue
            if not force:
                raise PrepareError(
                    f"{destination} exists at {_head(destination) or '<none>'}; "
                    "use --force to replace it"
                )
            shutil.rmtree(destination)
        _clone(case, destination)
        entries.append(_entry(case, destination))
    manifest = {
        "cases": str(cases_path.resolve()),
        "cases_sha256": hashlib.sha256(cases_path.read_bytes()).hexdigest(),
        "checkouts": entries,
    }
    if not dry_run:
        output.mkdir(parents=True, exist_ok=True)
        manifest_path = output / "checkouts_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        typer.echo(f"wrote {manifest_path}")
    return manifest


@app.command()
def main(
    cases: Path = typer.Option(HERE / "cases.json", exists=True, dir_okay=False),
    output: Path = typer.Option(HERE / "checkouts", file_okay=False),
    force: bool = typer.Option(False, help="Replace an existing checkout at a different commit."),
    dry_run: bool = typer.Option(False, help="Print clone commands without changing the filesystem."),
    verify_only: bool = typer.Option(False, help="Only verify existing checkouts and write the manifest."),
) -> None:
    try:
        manifest = prepare(cases, output, force=force, dry_run=dry_run, verify_only=verify_only)
    except PrepareError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    app()
