"""Integration tests for memory functionality."""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from minisweagent.agents.default import DefaultAgent, AgentConfig
from minisweagent.memory import HistoryManager, SessionMemory


class TestMemoryIntegration:
    """Integration tests for memory components."""

    @pytest.fixture
    def mock_model(self):
        """Mock model for testing."""
        model = Mock()
        model.cost = 0.0
        model.n_calls = 0
        model.config = Mock()
        model.get_template_vars.return_value = {}
        model.query.return_value = {"content": "Test response"}
        return model

    @pytest.fixture
    def mock_env(self):
        """Mock environment for testing."""
        env = Mock()
        env.config = Mock()
        env.get_template_vars.return_value = {}
        env.execute.return_value = {"output": "Test output", "returncode": 0}
        return env

    def test_agent_with_memory_disabled(self, mock_model, mock_env):
        """Test agent behavior with memory disabled."""
        config = AgentConfig(enable_memory=False)
        agent = DefaultAgent(mock_model, mock_env, config_class=lambda **kwargs: config)

        assert agent.history_manager is None
        assert agent.session_memory is None
        assert agent.config.enable_memory is False

    def test_agent_with_memory_enabled_no_dir(self, mock_model, mock_env):
        """Test agent with memory enabled but no directory specified."""
        config = AgentConfig(
            enable_memory=True,
            memory_max_messages=30,
            memory_dir=""
        )
        agent = DefaultAgent(mock_model, mock_env, config_class=lambda **kwargs: config)

        assert agent.history_manager is not None
        assert agent.history_manager.max_messages == 30
        assert agent.session_memory is None

    def test_agent_with_memory_enabled_with_dir(self, mock_model, mock_env, tmp_path):
        """Test agent with memory enabled and directory specified."""
        config = AgentConfig(
            enable_memory=True,
            memory_max_messages=25,
            memory_dir=str(tmp_path),
            memory_session_id="test_session"
        )
        agent = DefaultAgent(mock_model, mock_env, config_class=lambda **kwargs: config)

        assert agent.history_manager is not None
        assert agent.history_manager.max_messages == 25
        assert agent.session_memory is not None
        assert agent.session_memory.session_id == "test_session"

    def test_history_compression_during_query(self, mock_model, mock_env, tmp_path):
        """Test that history compression works during model queries."""
        config = AgentConfig(
            enable_memory=True,
            memory_max_messages=3,  # Very small limit to force compression
            memory_dir=str(tmp_path)
        )
        agent = DefaultAgent(mock_model, mock_env, config_class=lambda **kwargs: config)

        # Add many messages to exceed limit
        agent.messages = [
            {"role": "system", "content": "System message"},
            {"role": "user", "content": "User 1"},
            {"role": "assistant", "content": "Assistant 1"},
            {"role": "user", "content": "User 2"},
            {"role": "assistant", "content": "Assistant 2"},
            {"role": "user", "content": "User 3"}
        ]

        # Call query to trigger compression
        agent.query()

        # Check that model.query was called with compressed messages
        mock_model.query.assert_called_once()
        compressed_messages = mock_model.query.call_args[0][0]

        # Should have system message + 2 most recent messages = 3 total
        assert len(compressed_messages) == 3
        assert compressed_messages[0]["role"] == "system"
        assert compressed_messages[-1]["content"] == "User 3"

    def test_session_save_on_completion(self, mock_model, mock_env, tmp_path):
        """Test that session is saved when agent completes."""
        config = AgentConfig(
            enable_memory=True,
            memory_dir=str(tmp_path),
            memory_session_id="completion_test"
        )
        agent = DefaultAgent(mock_model, mock_env, config_class=lambda **kwargs: config)

        # Mock the model to return completion signal
        mock_model.query.return_value = {
            "content": "```bash\necho COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\n```"
        }
        mock_env.execute.return_value = {
            "output": "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT\nTask completed",
            "returncode": 0
        }

        # Run the agent
        try:
            agent.run("Test task")
        except Exception:
            pass  # Expected due to mocking

        # Check that session file was created
        session_file = tmp_path / "completion_test.json"
        assert session_file.exists()

    def test_session_load_on_startup(self, mock_model, mock_env, tmp_path):
        """Test loading previous session on agent startup."""
        # First, create a session
        session_memory = SessionMemory(tmp_path, "load_test")
        existing_messages = [
            {"role": "system", "content": "Previous system"},
            {"role": "user", "content": "Previous user message"},
            {"role": "assistant", "content": "Previous assistant message"}
        ]
        session_memory.save_session(existing_messages)

        # Now create agent that should load the session
        config = AgentConfig(
            enable_memory=True,
            memory_dir=str(tmp_path),
            memory_session_id="load_test",
            memory_load_session=True
        )
        agent = DefaultAgent(mock_model, mock_env, config_class=lambda **kwargs: config)

        # Start a run to trigger session loading
        mock_model.query.return_value = {"content": "New response"}
        try:
            agent.run("New task")
        except Exception:
            pass  # Expected due to mocking

        # Check that previous messages were loaded
        assert len(agent.messages) >= 3
        assert any(msg["content"] == "Previous user message" for msg in agent.messages)

    def test_memory_stats_collection(self, mock_model, mock_env, tmp_path):
        """Test that memory components can collect statistics."""
        config = AgentConfig(
            enable_memory=True,
            memory_max_messages=10,
            memory_dir=str(tmp_path),
            memory_session_id="stats_test"
        )
        agent = DefaultAgent(mock_model, mock_env, config_class=lambda **kwargs: config)

        # Add some messages
        agent.messages = [
            {"role": "system", "content": "System message"},
            {"role": "user", "content": "User message"},
            {"role": "assistant", "content": "Assistant message"}
        ]

        # Test history manager stats
        stats = agent.history_manager.get_summary_stats(agent.messages)
        assert stats["total_messages"] == 3
        assert stats["role_counts"]["system"] == 1
        assert stats["role_counts"]["user"] == 1
        assert stats["role_counts"]["assistant"] == 1

        # Save session and test session listing
        agent.session_memory.save_session(agent.messages)
        sessions = agent.session_memory.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "stats_test"
        assert sessions[0]["message_count"] == 3

    def test_end_to_end_memory_workflow(self, mock_model, mock_env, tmp_path):
        """Test complete memory workflow from start to finish."""
        session_id = "e2e_test"

        # Step 1: Run agent with memory and save session
        config1 = AgentConfig(
            enable_memory=True,
            memory_max_messages=50,
            memory_dir=str(tmp_path),
            memory_session_id=session_id
        )
        agent1 = DefaultAgent(mock_model, mock_env, config_class=lambda **kwargs: config1)

        # Simulate conversation
        agent1.messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]

        # Save session manually
        agent1.session_memory.save_session(agent1.messages, {"step": 1})

        # Step 2: Create new agent that loads the previous session
        config2 = AgentConfig(
            enable_memory=True,
            memory_max_messages=50,
            memory_dir=str(tmp_path),
            memory_session_id=session_id,
            memory_load_session=True
        )
        agent2 = DefaultAgent(mock_model, mock_env, config_class=lambda **kwargs: config2)

        # Load the session
        loaded_messages = agent2.session_memory.get_messages()
        assert len(loaded_messages) == 3
        assert loaded_messages[1]["content"] == "Hello"

        # Step 3: Continue conversation and test history compression
        agent2.messages = loaded_messages
        for i in range(50):  # Add many messages to trigger compression
            agent2.messages.extend([
                {"role": "user", "content": f"Message {i}"},
                {"role": "assistant", "content": f"Response {i}"}
            ])

        # Test compression
        compressed = agent2.history_manager.compress_messages(agent2.messages)
        assert len(compressed) == 50  # Should be compressed to max_messages

        # Step 4: Cleanup old sessions
        # Create additional sessions first
        for i in range(15):
            extra_session = SessionMemory(tmp_path, f"extra_session_{i}")
            extra_session.save_session([{"role": "user", "content": f"Extra {i}"}])

        # Cleanup keeping only 10 sessions
        deleted_count = agent2.session_memory.cleanup_old_sessions(keep_count=10)
        assert deleted_count > 0

        remaining_sessions = agent2.session_memory.list_sessions()
        assert len(remaining_sessions) <= 10