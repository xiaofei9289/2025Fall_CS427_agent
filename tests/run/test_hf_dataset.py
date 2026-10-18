import os

import pytest

from minisweagent.run.extra.hf_dataset import load_hf_dataset


def test_cached_dataset_is_used_without_connecting():
    calls = []
    before = os.environ.get("HF_HUB_OFFLINE")

    def loader(path, split):
        calls.append((path, split, os.environ.get("HF_HUB_OFFLINE")))
        return {"path": path, "split": split}

    assert load_hf_dataset("princeton-nlp/SWE-bench_Verified", "test", loader=loader)["split"] == "test"
    assert calls == [("princeton-nlp/SWE-bench_Verified", "test", "1")]
    assert os.environ.get("HF_HUB_OFFLINE") == before


def test_missing_cache_falls_back_to_the_hub():
    calls = []

    def loader(path, split):
        calls.append(os.environ.get("HF_HUB_OFFLINE"))
        if len(calls) == 1:
            raise ConnectionError("Couldn't reach the Hub (OfflineModeIsEnabled)")
        return "downloaded"

    before = os.environ.get("HF_DATASETS_OFFLINE")
    assert load_hf_dataset("missing/dataset", "test", loader=loader) == "downloaded"
    assert calls == ["1", None]
    assert os.environ.get("HF_DATASETS_OFFLINE") == before


def test_other_load_errors_are_not_retried_online():
    def loader(path, split):
        raise ValueError("bad dataset")

    with pytest.raises(ValueError, match="bad dataset"):
        load_hf_dataset("missing/dataset", "test", loader=loader)
