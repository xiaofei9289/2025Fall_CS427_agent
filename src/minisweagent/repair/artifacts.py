"""Atomic, best-effort artifact writes for a repair run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from minisweagent.utils.log import logger


class ArtifactWriter:
    def __init__(self, directory: str | Path | None):
        self.directory = Path(directory) if directory else None

    @property
    def enabled(self) -> bool:
        return self.directory is not None

    def _ensure(self) -> bool:
        if self.directory is None:
            return False
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            logger.warning(f"Failed to create repair artifact directory {self.directory}: {error}")
            return False
        return True

    def write_json(self, name: str, value: Any) -> None:
        if not self._ensure():
            return
        path = self.directory / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + "\n")
            temporary.replace(path)
        except OSError as error:
            logger.warning(f"Failed to write repair artifact {path}: {error}")

    def append_jsonl(self, name: str, value: Any) -> None:
        if not self._ensure():
            return
        path = self.directory / name
        try:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, default=str) + "\n")
        except OSError as error:
            logger.warning(f"Failed to append repair artifact {path}: {error}")

    def write_text(self, name: str, text: str) -> None:
        if not self._ensure():
            return
        path = self.directory / name
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_text(text)
            temporary.replace(path)
        except OSError as error:
            logger.warning(f"Failed to write repair artifact {path}: {error}")
