"""Workspace diff helpers shared by the repair workflow, the test tool, and submission export."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

_JUNK_NAME = re.compile(r"^(reproduce\w*|run_test|test_fix|apply_patch|mock_query)\.py$")
_TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]+\.py$|(^|/)[^/]+_test\.py$|(^|/)conftest\.py$")
_GENERATED_PATH = re.compile(
    r"(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|htmlcov|\.eggs|[^/]+\.egg-info)(/|$)"
    r"|\.(pyc|pyo)$|(^|/)\.coverage$|(^|/)coverage\.xml$"
)


def _path_from_part(part: str) -> str:
    match = re.match(r"diff --git a/(.+?) b/(.+)$", part.splitlines()[0])
    return match.group(1) if match else ""


def _strip_generated_parts(text: str) -> str:
    """Ignore caches and coverage files so test runs do not make the workspace look dirty."""
    if not text:
        return ""
    kept: list[str] = []
    for part in re.split(r"(?=^diff --git )", text, flags=re.M):
        if not part.startswith("diff --git "):
            continue
        if _GENERATED_PATH.search(_path_from_part(part)):
            continue
        kept.append(part)
    return "".join(kept)


def _is_junk_diff_path(path: str, header: str) -> bool:
    """Drop reproduction scripts, generated files, and new files left at the repo root."""
    if path.startswith("_build/") or "/_build/" in path:
        return True
    if path.endswith((".doctree", ".pyc", ".png", ".so")):
        return True
    name = path.rsplit("/", 1)[-1]
    if _JUNK_NAME.match(name):
        return True
    new_file = any(line.startswith("new file mode ") for line in header.splitlines()[:8])
    return new_file and "/" not in path


def sanitize_patch(text: str) -> str:
    """Keep source diffs and drop scratch files that make a submission fail to apply."""
    text = _strip_generated_parts(text)
    if not text or "diff --git " not in text:
        return ""
    parts = re.split(r"(?=^diff --git )", text, flags=re.M)
    kept: list[str] = []
    for part in parts:
        if not part.startswith("diff --git "):
            continue
        path = _path_from_part(part)
        if _is_junk_diff_path(path, part):
            continue
        kept.append(part if part.endswith("\n") else part + "\n")
    return "".join(kept)


def diff_fingerprint(patch: str) -> str:
    """Stable identity for the workspace state that was tested."""
    return hashlib.sha256(patch.encode("utf-8")).hexdigest() if patch else ""


@dataclass(frozen=True)
class DiffResult:
    ok: bool
    patch: str
    error: str = ""


@dataclass(frozen=True)
class DiffSummary:
    changed_files: tuple[str, ...] = ()
    test_files_changed: bool = False
    is_empty: bool = True
    junk_only: bool = False
    diff_chars: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_files": list(self.changed_files),
            "test_files_changed": self.test_files_changed,
            "is_empty": self.is_empty,
            "junk_only": self.junk_only,
            "diff_chars": self.diff_chars,
        }


def compute_diff(env: Any) -> DiffResult:
    """Return the current worktree diff, including untracked files.

    ``git add -N`` records intent-to-add so new files appear in ``git diff HEAD``
    without staging their contents. The index is touched, but the worktree is not.
    """
    try:
        added = env.execute("git add -N -- .")
    except Exception as error:  # noqa: BLE001
        return DiffResult(False, "", f"{type(error).__name__}: {error}")
    if added.get("returncode") != 0:
        return DiffResult(False, "", added.get("output") or "git add -N failed")
    try:
        diff = env.execute("git diff HEAD")
    except Exception as error:  # noqa: BLE001
        return DiffResult(False, "", f"{type(error).__name__}: {error}")
    if diff.get("returncode") != 0:
        return DiffResult(False, "", diff.get("output") or "git diff HEAD failed")
    return DiffResult(True, _strip_generated_parts(diff.get("output") or ""))


def summarize_diff(patch: str) -> DiffSummary:
    """Classify the diff without trusting the model's own description."""
    patch = _strip_generated_parts(patch)
    changed: list[str] = []
    test_changed = False
    for part in re.split(r"(?=^diff --git )", patch, flags=re.M):
        if not part.startswith("diff --git "):
            continue
        path = _path_from_part(part)
        if not path:
            continue
        changed.append(path)
        if _TEST_PATH.search(path):
            test_changed = True
    sanitized = sanitize_patch(patch)
    return DiffSummary(
        changed_files=tuple(changed),
        test_files_changed=test_changed,
        is_empty=not sanitized.strip(),
        junk_only=bool(patch.strip()) and not sanitized.strip(),
        diff_chars=len(patch),
    )
