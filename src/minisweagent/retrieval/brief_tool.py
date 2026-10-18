"""Build the deterministic repository brief on the host or inside an environment."""

from __future__ import annotations

import json
import shlex
from pathlib import Path

from minisweagent.retrieval import brief as brief_module
from minisweagent.retrieval import repository
from minisweagent.utils.log import logger


def _brief_script(issue: str, max_chars: int, max_files: int) -> str:
    """Embed the index and brief sources for execution inside the sandbox."""
    return (
        Path(repository.__file__).read_text(encoding="utf-8")
        + "\n"
        + Path(brief_module.__file__).read_text(encoding="utf-8")
        + "\n"
        + "import json\n"
        + "from pathlib import Path\n"
        + f"issue = {issue!r}\n"
        + f"max_chars = {int(max_chars)}\n"
        + f"max_files = {int(max_files)}\n"
        + "try:\n"
        + "    index = RepositoryIndex(Path.cwd())\n"
        + "    result = {'output': build_brief(index, issue, max_chars, max_files), 'returncode': 0}\n"
        + "except Exception as error:\n"
        + "    result = {'output': 'Error building repository brief: ' + str(error), 'returncode': 1}\n"
        + "print(json.dumps(result))\n"
    )


def build_repo_brief(env, issue: str, max_chars: int = 3000, max_files: int = 6) -> str:
    """Return a brief, or an empty string when the repository cannot be indexed.

    The helper fails open: an indexing error must not prevent the agent from
    starting. The caller can decide whether to log the empty result.
    """
    if not isinstance(issue, str) or not issue.strip():
        return ""
    if not isinstance(max_chars, int) or not 400 <= max_chars <= 20000:
        max_chars = 3000
    if not isinstance(max_files, int) or not 1 <= max_files <= 20:
        max_files = 6
    if env is None:
        try:
            index = repository.RepositoryIndex(Path.cwd())
            return brief_module.build_brief(index, issue, max_chars, max_files)
        except (OSError, ValueError) as error:
            logger.warning(f"Repository brief unavailable: {error}")
            return ""
    script = _brief_script(issue, max_chars, max_files)
    try:
        output = env.execute(f"python -c {shlex.quote(script)}")
    except Exception as error:  # noqa: BLE001
        logger.warning(f"Repository brief execution failed: {error}")
        return ""
    if output.get("returncode") != 0:
        logger.warning(f"Repository brief failed: {str(output.get('output', ''))[:300]}")
        return ""
    try:
        payload = json.loads(output.get("output", ""))
    except (TypeError, ValueError):
        logger.warning("Repository brief returned non-JSON output")
        return ""
    if not isinstance(payload, dict) or payload.get("returncode") != 0:
        return ""
    text = payload.get("output", "")
    return text if isinstance(text, str) else ""


__all__ = ["build_repo_brief"]
