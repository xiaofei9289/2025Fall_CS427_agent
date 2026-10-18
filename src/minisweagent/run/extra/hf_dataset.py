"""Load a Hugging Face dataset from the local cache, then the Hub."""

import os
from collections.abc import Callable
from typing import Any

from datasets import load_dataset


def _cache_miss(error: BaseException) -> bool:
    text = f"{type(error).__name__}: {error}"
    return isinstance(error.__cause__, FileNotFoundError) or any(
        label in text for label in ("OfflineModeIsEnabled", "LocalEntryNotFoundError")
    )


def _restore(saved: dict[str, str | None]) -> None:
    for key, value in saved.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def load_hf_dataset(path: str, split: str, *, loader: Callable[..., Any] = load_dataset) -> Any:
    """Return a dataset from the local cache, downloading it only when the cache has no copy."""
    keys = ("HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE")
    saved = {key: os.environ.get(key) for key in keys}
    os.environ.update({"HF_HUB_OFFLINE": "1", "HF_DATASETS_OFFLINE": "1"})
    try:
        return loader(path, split=split)
    except Exception as error:
        if not _cache_miss(error):
            raise
    finally:
        _restore(saved)
    for key in keys:
        os.environ.pop(key, None)
    try:
        return loader(path, split=split)
    finally:
        _restore(saved)
