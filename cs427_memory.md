# CS427 Course Project: Extending mini-swe-agent with Memory

This document summarizes the current memory integration in mini-swe-agent and provides guidance for CS427 students who will extend the agent with advanced memory capabilities.

## Current Architecture

### Memory Components
- Location: `src/minisweagent/memory/__init__.py`
- Exports three memory components:
  ```python
  from .history import HistoryManager
  from .session import SessionMemory
  from .replay import TrajectoryReplayer
  ```

### History Manager
- `HistoryManager` (see `src/minisweagent/memory/history.py`):
  - Provides conversation compression capabilities and keeps recent messages while preserving system messages to manage context length
  - Key methods:
    - `compress_messages()`: Reduces message history while keeping important context
    - `get_summary_stats()`: Provides statistics about message history

### Session Memory
- `SessionMemory` (see `src/minisweagent/memory/session.py`):
  - Enables cross-session persistence with JSON file storage and automatically manages session files in repository-local directories
  - Key methods:
    - `save_session()`: Persists conversation data with metadata
    - `load_session()` / `get_messages()`: Retrieves previous conversations
    - `list_sessions()`: Shows available sessions
    - `cleanup_old_sessions()`: Manages storage by removing old sessions

### Trajectory Replayer
- `TrajectoryReplayer` (see `src/minisweagent/memory/replay.py`):
  - Analyzes saved agent runs for debugging and replay
  - Key methods:
    - `load_trajectory()`: Loads saved trajectory data
    - `create_replay_script()`: Generates shell scripts for reproduction

### Usage Examples

- Enable memory with default settings:
  ```bash
  mini --memory --task "start new session"
  ```

- Use specific session and directory:
  ```bash
  mini --memory --memory-dir "./project_memory" --memory-session "feature_dev" --task "implement feature"
  ```

- Load previous session:
  ```bash
  mini --memory --memory-load --memory-session "my_session" --task "continue previous work"
  ```

- Set custom history limit:
  ```bash
  mini --memory --memory-max 100 --memory-session "long_session" --task "complex debugging"
  ```

- Session management from code:
  ```python
  from minisweagent.memory import SessionMemory
  memory = SessionMemory(Path("./memory"), "session_id")
  memory.save_session(messages)
  previous_messages = memory.get_messages()
  ```

- Trajectory analysis:
  ```python
  from minisweagent.memory import TrajectoryReplayer
  replayer = TrajectoryReplayer(Path("trajectory.json"))
  actions = replayer.extract_actions()
  replayer.create_replay_script(Path("replay.sh"))
  ```

## Extending the Memory Component

We have implemented basic memory functionality including conversation history compression, cross-session persistence, and trajectory replay for debugging. These provide a foundation for more advanced memory capabilities.

Your task is to extend the existing memory framework to enhance the agent's problem-solving abilities. If you have better ideas, you are also welcome to redesign the memory framework entirely, though this may require more time and effort.

Please note that this is an **optional** task. Simply implementing additional memory features will not earn extra credit - only improvements that demonstrably enhance agent performance on SWE-Bench will be rewarded. Consider carefully whether to pursue this extension (it may require significant time investment) and think strategically about which memory capabilities would genuinely improve programming task performance.

### Possible Memory Ideas

These are some reference ideas to inspire your implementation. You can also study memory modules from other mainstream agents:

- **memory_search**: search through conversation history using keywords, patterns, or **semantic similarity** to find relevant past information
- **memory_compression**: intelligently compress conversation history while preserving contextually important information for the current task

### Expectations for the Optional Memory Part

- **Focus on Performance**: Implement memory features that measurably improve agent effectiveness on programming tasks, not just add functionality
- **Integration**: Build on the existing memory architecture and ensure compatibility with the agent's workflow
- **SWE-Bench Compatibility**: Memory features should work within the Docker environment constraints when applicable
- **Testing**: Provide unit tests and demonstrate that your memory enhancements actually improve agent performance
- **Simplicity**: Keep memory operations lightweight and ensure they fail gracefully without breaking the agent