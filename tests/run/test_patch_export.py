import subprocess

import pytest

from minisweagent.run.extra.swebench import sanitize_submission_patch


@pytest.mark.parametrize(("original", "modified"), [
    ("value = 1\n", "value = 1\n\ndef helper():\n    return 2\n"),
    ("value = 1\n\n", "value = 2\n\n"),
])
def test_exported_patch_applies_without_repairing_its_bytes(tmp_path, original, modified):
    package = tmp_path / "pkg"
    package.mkdir()
    source = package / "app.py"
    source.write_text(original)
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Test", "-c", "user.email=test@example.org",
                    "commit", "-m", "fixture"], check=True, capture_output=True)
    source.write_text(modified)
    raw = subprocess.check_output(["git", "-C", str(tmp_path), "diff", "HEAD"], text=True)
    exported = sanitize_submission_patch(raw)
    assert exported == raw and exported.endswith("\n")
    source.write_text(original)
    subprocess.run(["git", "-C", str(tmp_path), "apply", "--check", "-"], input=exported, text=True, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "apply", "-"], input=exported, text=True, check=True)
    assert source.read_text() == modified
