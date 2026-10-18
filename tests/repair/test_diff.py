import subprocess

from minisweagent.environments.local import LocalEnvironment
from minisweagent.repair.diff import (
    compute_diff,
    diff_fingerprint,
    sanitize_patch,
    summarize_diff,
)


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("value = 1\n")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "base"],
        check=True,
        capture_output=True,
    )
    return repo


def test_compute_diff_includes_untracked_and_ignores_generated_files(tmp_path):
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("value = 2\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_new.py").write_text("def test_new():\n    assert True\n")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "app.cpython-311.pyc").write_bytes(b"stale")
    (repo / ".pytest_cache").mkdir()
    (repo / ".pytest_cache" / "cache").write_text("noise")

    result = compute_diff(LocalEnvironment(cwd=str(repo)))
    assert result.ok is True
    assert "app.py" in result.patch
    assert "tests/test_new.py" in result.patch
    assert "__pycache__" not in result.patch
    assert ".pytest_cache" not in result.patch

    summary = summarize_diff(result.patch)
    assert summary.changed_files == ("app.py", "tests/test_new.py")
    assert summary.test_files_changed is True
    assert summary.is_empty is False
    assert summary.junk_only is False


def test_junk_only_diff_is_empty_after_sanitizing(tmp_path):
    repo = _repo(tmp_path)
    (repo / "reproduce_issue.py").write_text("print('repro')\n")
    result = compute_diff(LocalEnvironment(cwd=str(repo)))
    assert result.ok is True
    summary = summarize_diff(result.patch)
    assert summary.is_empty is True
    assert summary.junk_only is True
    assert sanitize_patch(result.patch) == ""


def test_generated_build_and_cache_paths_are_dropped():
    patch = (
        "diff --git a/_build/generated.py b/_build/generated.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/_build/generated.py\n"
        "@@ -0,0 +1 @@\n"
        "+x = 1\n"
        "diff --git a/.pytest_cache/v/cache b/.pytest_cache/v/cache\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/.pytest_cache/v/cache\n"
        "@@ -0,0 +1 @@\n"
        "+noise\n"
    )
    assert sanitize_patch(patch) == ""


def test_fingerprint_changes_with_workspace(tmp_path):
    repo = _repo(tmp_path)
    env = LocalEnvironment(cwd=str(repo))
    assert diff_fingerprint(compute_diff(env).patch) == ""
    (repo / "app.py").write_text("value = 2\n")
    first = diff_fingerprint(compute_diff(env).patch)
    (repo / "app.py").write_text("value = 3\n")
    second = diff_fingerprint(compute_diff(env).patch)
    assert first and first != second
