"""Tests for trajectory replay functionality."""

import json
from pathlib import Path

import pytest
from minisweagent.memory.replay import TrajectoryReplayer


class TestTrajectoryReplayer:
    """Test cases for TrajectoryReplayer class."""

    @pytest.fixture
    def sample_trajectory_data(self):
        """Sample trajectory data for testing."""
        return {
            "info": {
                "exit_status": "Submitted",
                "submission": "Task completed",
                "model_stats": {
                    "api_calls": 5,
                    "instance_cost": 0.15
                },
                "mini_version": "1.0.0"
            },
            "messages": [
                {"role": "system", "content": "You are helpful"},
                {"role": "user", "content": "Task: list files"},
                {"role": "assistant", "content": "I'll list the files.\n```bash\nls -la\n```"},
                {"role": "user", "content": "Observation: file1.txt file2.py"},
                {"role": "assistant", "content": "Found files.\n```tool\n{\"name\": \"read_file\", \"args\": {\"path\": \"file1.txt\"}}\n```"},
                {"role": "user", "content": "Observation: Content of file1"}
            ],
            "trajectory_format": "mini-swe-agent-1"
        }

    @pytest.fixture
    def trajectory_file(self, tmp_path, sample_trajectory_data):
        """Create a temporary trajectory file for testing."""
        file_path = tmp_path / "test_trajectory.json"
        with open(file_path, 'w') as f:
            json.dump(sample_trajectory_data, f)
        return file_path

    def test_init(self, trajectory_file):
        """Test TrajectoryReplayer initialization."""
        replayer = TrajectoryReplayer(trajectory_file)
        assert replayer.trajectory_file == trajectory_file
        assert replayer._trajectory_data is None

    def test_load_trajectory_success(self, trajectory_file):
        """Test successful trajectory loading."""
        replayer = TrajectoryReplayer(trajectory_file)
        assert replayer.load_trajectory() is True
        assert replayer._trajectory_data is not None

    def test_load_trajectory_nonexistent_file(self, tmp_path):
        """Test loading non-existent trajectory file."""
        nonexistent_file = tmp_path / "nonexistent.json"
        replayer = TrajectoryReplayer(nonexistent_file)
        assert replayer.load_trajectory() is False

    def test_load_trajectory_invalid_json(self, tmp_path):
        """Test loading trajectory with invalid JSON."""
        invalid_file = tmp_path / "invalid.json"
        invalid_file.write_text("invalid json content")

        replayer = TrajectoryReplayer(invalid_file)
        assert replayer.load_trajectory() is False

    def test_get_trajectory_info(self, trajectory_file, sample_trajectory_data):
        """Test getting trajectory information."""
        replayer = TrajectoryReplayer(trajectory_file)
        info = replayer.get_trajectory_info()

        assert info["exit_status"] == "Submitted"
        assert info["submission"] == "Task completed"
        assert info["total_messages"] == 6
        assert info["api_calls"] == 5
        assert info["cost"] == 0.15
        assert info["mini_version"] == "1.0.0"
        assert info["format"] == "mini-swe-agent-1"

    def test_get_trajectory_info_no_file(self, tmp_path):
        """Test getting trajectory info when file doesn't exist."""
        nonexistent_file = tmp_path / "nonexistent.json"
        replayer = TrajectoryReplayer(nonexistent_file)
        info = replayer.get_trajectory_info()
        assert info == {}

    def test_get_messages(self, trajectory_file, sample_trajectory_data):
        """Test getting messages from trajectory."""
        replayer = TrajectoryReplayer(trajectory_file)
        messages = replayer.get_messages()

        assert len(messages) == 6
        assert messages[0]["role"] == "system"
        assert messages[1]["content"] == "Task: list files"

    def test_get_messages_no_file(self, tmp_path):
        """Test getting messages when file doesn't exist."""
        nonexistent_file = tmp_path / "nonexistent.json"
        replayer = TrajectoryReplayer(nonexistent_file)
        messages = replayer.get_messages()
        assert messages == []

    def test_replay_steps(self, trajectory_file):
        """Test replaying trajectory steps."""
        replayer = TrajectoryReplayer(trajectory_file)
        steps = list(replayer.replay_steps())

        assert len(steps) == 6
        assert steps[0]["step"] == 0
        assert steps[0]["is_last"] is False
        assert steps[-1]["step"] == 5
        assert steps[-1]["is_last"] is True

    def test_replay_steps_with_start_and_limit(self, trajectory_file):
        """Test replaying with start step and max steps."""
        replayer = TrajectoryReplayer(trajectory_file)
        steps = list(replayer.replay_steps(start_step=2, max_steps=2))

        assert len(steps) == 2
        assert steps[0]["step"] == 2
        assert steps[1]["step"] == 3

    def test_extract_actions(self, trajectory_file):
        """Test extracting actions from trajectory."""
        replayer = TrajectoryReplayer(trajectory_file)
        actions = replayer.extract_actions()

        assert len(actions) == 2

        # First action should be bash
        bash_action = actions[0]
        assert bash_action["type"] == "bash"
        assert bash_action["action"] == "ls -la"

        # Second action should be tool
        tool_action = actions[1]
        assert tool_action["type"] == "tool"
        assert tool_action["tool_name"] == "read_file"
        assert tool_action["tool_args"]["path"] == "file1.txt"

    def test_extract_actions_no_actions(self, tmp_path):
        """Test extracting actions when no actions exist."""
        data = {
            "messages": [
                {"role": "system", "content": "System message"},
                {"role": "user", "content": "User message"}
            ]
        }
        trajectory_file = tmp_path / "no_actions.json"
        with open(trajectory_file, 'w') as f:
            json.dump(data, f)

        replayer = TrajectoryReplayer(trajectory_file)
        actions = replayer.extract_actions()
        assert actions == []

    def test_create_replay_script(self, trajectory_file, tmp_path):
        """Test creating replay script."""
        replayer = TrajectoryReplayer(trajectory_file)
        script_file = tmp_path / "replay.sh"

        success = replayer.create_replay_script(script_file)
        assert success is True
        assert script_file.exists()

        # Check script content
        script_content = script_file.read_text()
        assert "#!/bin/bash" in script_content
        assert "ls -la" in script_content
        assert "Tool call: read_file" in script_content

        # Check script is executable
        assert script_file.stat().st_mode & 0o111 != 0

    def test_create_replay_script_with_observations(self, trajectory_file, tmp_path):
        """Test creating replay script with observations."""
        replayer = TrajectoryReplayer(trajectory_file)
        script_file = tmp_path / "replay_with_obs.sh"

        success = replayer.create_replay_script(script_file, include_observations=True)
        assert success is True

        script_content = script_file.read_text()
        assert "# Output: file1.txt file2.py" in script_content

    def test_create_replay_script_no_actions(self, tmp_path):
        """Test creating replay script when no actions exist."""
        data = {"messages": [{"role": "system", "content": "No actions"}]}
        trajectory_file = tmp_path / "no_actions.json"
        with open(trajectory_file, 'w') as f:
            json.dump(data, f)

        replayer = TrajectoryReplayer(trajectory_file)
        script_file = tmp_path / "empty_replay.sh"

        success = replayer.create_replay_script(script_file)
        assert success is False
        assert not script_file.exists()

    def test_create_replay_script_io_error(self, trajectory_file):
        """Test creating replay script with IO error."""
        replayer = TrajectoryReplayer(trajectory_file)
        # Try to write to a directory instead of a file
        invalid_path = Path("/dev/null/invalid_path")

        success = replayer.create_replay_script(invalid_path)
        assert success is False