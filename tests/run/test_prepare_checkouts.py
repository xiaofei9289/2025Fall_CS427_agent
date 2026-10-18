import json
import subprocess
from pathlib import Path

import pytest

from experiments.localization_verified5.prepare_checkouts import PrepareError, prepare


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "origin"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    (repo / "a.py").write_text("def a():\n    return 1\n")
    git(repo, "add", "a.py")
    git(repo, "commit", "-q", "-m", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "b.py").write_text("def b():\n    return 2\n")
    git(repo, "add", "b.py")
    git(repo, "commit", "-q", "-m", "later")
    return repo, base


def write_cases(tmp_path: Path, repo: Path, base: str, *, include_url: bool = True) -> Path:
    case = {
        "instance_id": "case1",
        "repo": "checkouts/case1",
        "base_commit": base,
        "gold_files": ["a.py"],
    }
    if include_url:
        case["repo_url"] = str(repo)
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([case]))
    return path


def test_prepare_checkouts_is_frozen_and_idempotent(tmp_path: Path) -> None:
    repo, base = make_repo(tmp_path)
    cases = write_cases(tmp_path, repo, base)
    output = tmp_path / "checkouts"
    manifest = prepare(cases, output)
    checkout = output / "case1"
    assert (checkout / "a.py").is_file()
    assert not (checkout / "b.py").exists()
    assert manifest["checkouts"][0]["head"] == base
    assert manifest["checkouts"][0]["python_files"] == 1
    manifest_path = output / "checkouts_manifest.json"
    assert manifest_path.is_file()
    assert json.loads(manifest_path.read_text())["cases_sha256"] == manifest["cases_sha256"]

    # A second run reuses the checkout instead of cloning again.
    again = prepare(cases, output)
    assert again["checkouts"][0]["head"] == base
    verified = prepare(cases, output, verify_only=True)
    assert verified["checkouts"][0]["head"] == base


def test_prepare_checkouts_dry_run_does_not_write(tmp_path: Path) -> None:
    repo, base = make_repo(tmp_path)
    cases = write_cases(tmp_path, repo, base)
    output = tmp_path / "checkouts"
    manifest = prepare(cases, output, dry_run=True)
    assert manifest["checkouts"][0]["head"] is None
    assert not output.exists()


def test_prepare_checkouts_requires_repo_url(tmp_path: Path) -> None:
    repo, base = make_repo(tmp_path)
    cases = write_cases(tmp_path, repo, base, include_url=False)
    with pytest.raises(PrepareError, match="repo_url"):
        prepare(cases, tmp_path / "checkouts")


def test_verify_only_rejects_missing_checkout(tmp_path: Path) -> None:
    repo, base = make_repo(tmp_path)
    cases = write_cases(tmp_path, repo, base)
    with pytest.raises(PrepareError, match="Missing checkout"):
        prepare(cases, tmp_path / "checkouts", verify_only=True)
