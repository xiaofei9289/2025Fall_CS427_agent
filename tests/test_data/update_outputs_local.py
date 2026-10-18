#!/usr/bin/env python3

import json
from pathlib import Path
from unittest.mock import patch

from minisweagent.models.test_models import DeterministicModel
from minisweagent.run.mini import DEFAULT_CONFIG, main


def update_trajectory():
    traj_path = Path(__file__).parent / "local.traj.json"
    trajectory = json.loads(traj_path.read_text())

    task = "Blah blah blah"

    model_responses = [msg["content"] for msg in trajectory[2:] if msg["role"] == "assistant"]
    print(f"Got {len(model_responses)} model responses")

    with patch("minisweagent.run.mini.get_model") as mock_get_model:
        mock_get_model.return_value = DeterministicModel(outputs=model_responses)
        agent = main(model_name="tardis", config_spec=DEFAULT_CONFIG, task=task, yolo=True,
                     model_class=None, exit_immediately=True)

    # The test fixture is the plain message list, not save_traj's full envelope.
    traj_path.write_text(json.dumps(agent.messages, indent=2))

if __name__ == "__main__":
    update_trajectory()