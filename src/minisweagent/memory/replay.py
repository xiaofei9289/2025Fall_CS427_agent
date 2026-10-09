"""Trajectory replay functionality."""

import json
from pathlib import Path
from typing import Any, Optional, Iterator


class TrajectoryReplayer:
    """Replays saved trajectories step by step."""

    def __init__(self, trajectory_file: Path):
        """Initialize trajectory replayer.

        Args:
            trajectory_file: Path to trajectory JSON file
        """
        self.trajectory_file = Path(trajectory_file)
        self._trajectory_data: Optional[dict] = None

    def load_trajectory(self) -> bool:
        """Load trajectory data from file.

        Returns:
            True if successfully loaded, False otherwise
        """
        if not self.trajectory_file.exists():
            return False

        try:
            with open(self.trajectory_file, 'r') as f:
                self._trajectory_data = json.load(f)
            return True
        except (json.JSONDecodeError, IOError):
            return False

    def get_trajectory_info(self) -> dict[str, Any]:
        """Get basic information about the trajectory.

        Returns:
            Dictionary with trajectory metadata
        """
        if not self._trajectory_data:
            if not self.load_trajectory():
                return {}

        info = self._trajectory_data.get("info", {})
        messages = self._trajectory_data.get("messages", [])

        return {
            "exit_status": info.get("exit_status"),
            "submission": info.get("submission"),
            "total_messages": len(messages),
            "api_calls": info.get("model_stats", {}).get("api_calls", 0),
            "cost": info.get("model_stats", {}).get("instance_cost", 0.0),
            "mini_version": info.get("mini_version"),
            "format": self._trajectory_data.get("trajectory_format")
        }

    def get_messages(self) -> list[dict[str, Any]]:
        """Get all messages from the trajectory.

        Returns:
            List of message dictionaries
        """
        if not self._trajectory_data:
            if not self.load_trajectory():
                return []

        return self._trajectory_data.get("messages", [])

    def replay_steps(self, start_step: int = 0, max_steps: Optional[int] = None) -> Iterator[dict[str, Any]]:
        """Replay trajectory steps one by one.

        Args:
            start_step: Step index to start from
            max_steps: Maximum number of steps to replay

        Yields:
            Message dictionaries in sequence
        """
        messages = self.get_messages()
        if not messages:
            return

        end_step = len(messages)
        if max_steps is not None:
            end_step = min(start_step + max_steps, len(messages))

        for i in range(start_step, end_step):
            yield {
                "step": i,
                "message": messages[i],
                "is_last": i == len(messages) - 1
            }

    def extract_actions(self) -> list[dict[str, Any]]:
        """Extract all actions from the trajectory.

        Returns:
            List of action dictionaries
        """
        messages = self.get_messages()
        actions = []

        for i, msg in enumerate(messages):
            if msg.get("role") == "assistant":
                content = msg.get("content", "")

                # Extract bash commands
                import re
                bash_blocks = re.findall(r"```bash\n(.*?)\n```", content, re.DOTALL)
                tool_blocks = re.findall(r"```tool\n(.*?)\n```", content, re.DOTALL)

                if bash_blocks:
                    actions.append({
                        "step": i,
                        "type": "bash",
                        "action": bash_blocks[0].strip()
                    })
                elif tool_blocks:
                    try:
                        tool_data = json.loads(tool_blocks[0].strip())
                        actions.append({
                            "step": i,
                            "type": "tool",
                            "tool_name": tool_data.get("name"),
                            "tool_args": tool_data.get("args", {})
                        })
                    except json.JSONDecodeError:
                        pass

        return actions

    def create_replay_script(self, output_file: Path, include_observations: bool = False) -> bool:
        """Create a shell script to replay the trajectory.

        Args:
            output_file: Path to save the replay script
            include_observations: Whether to include observation comments

        Returns:
            True if script was created successfully
        """
        actions = self.extract_actions()
        if not actions:
            return False

        script_lines = [
            "#!/bin/bash",
            "# Trajectory replay script",
            f"# Generated from: {self.trajectory_file}",
            ""
        ]

        messages = self.get_messages()
        for action in actions:
            step = action["step"]
            script_lines.append(f"# Step {step}")

            if action["type"] == "bash":
                script_lines.append(action["action"])
            elif action["type"] == "tool":
                # Convert tool calls to comments since they can't be executed directly
                script_lines.append(f"# Tool call: {action['tool_name']} with args {action['tool_args']}")

            # Add observation as comment if requested
            if include_observations and step + 1 < len(messages):
                next_msg = messages[step + 1]
                if next_msg.get("role") == "user":
                    obs_content = next_msg.get("content", "").strip()
                    if obs_content.startswith("Observation:"):
                        obs_text = obs_content[12:].strip()  # Remove "Observation:" prefix
                        script_lines.append(f"# Output: {obs_text}")

            script_lines.append("")

        try:
            with open(output_file, 'w') as f:
                f.write("\n".join(script_lines))
            # Make script executable
            output_file.chmod(0o755)
            return True
        except IOError:
            return False