"""Smoke-test one TokenFy experiment config through the project's own model pipeline.

Run inside the cs427-validation container on the desktop; the API key is injected
via MSWEA_MODEL_API_KEY and the model name is chosen with SMOKE_CONFIG.
"""

import os
import time
from pathlib import Path

import yaml

from minisweagent.models import get_model

name = os.environ["SMOKE_CONFIG"]
model_config = yaml.safe_load((Path("experiments/configs") / name).read_text())["model"]
model = get_model(config=model_config)
print(f"== {name} -> {type(model).__name__}({model.config.model_name})")
t0 = time.monotonic()
result = model.query([{"role": "user", "content": "Reply with exactly: OK"}])
print(f"   reply={result.get('message') or result.get('content', '')!r}")
extra = result.get("extra") or result.get("info") or {}
print(f"   usage={ (extra.get('response') or {}).get('usage', extra.get('usage')) }")
print(f"   status={extra.get('response_status', result.get('finish_reason', '?'))}")
print(f"   {time.monotonic() - t0:.1f}s cost=${model.cost:.6f} n_calls={model.n_calls}")