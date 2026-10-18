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
  - `compress_messages()` keeps the system prompt and the most recent turns
  - `compress_salient()` keeps the system prompt, original task, and a continuous suffix of complete action/observation turns. A bounded `[memory]` summary of omitted execution evidence shares the message budget. Limits too small for the task and latest complete turn are rejected
  - Short histories are sent unchanged. Summaries identify source steps, record only successful read tools as reads, and replace earlier failures when the same operation succeeds. Successful edits mark earlier reads as potentially stale. Paths mentioned only in model prose are not evidence
  - The agent uses `prompt_messages()` on each model call when `--memory` is enabled. The full transcript stays in `agent.messages` and remains searchable
  - `get_summary_stats()` reports message counts and whether the history is over the limit

### Memory Search
- `MemorySearch` (see `src/minisweagent/memory/search.py`) searches a transcript by keyword or regular expression
- Keyword queries are case-insensitive and require every term to match. Results include the message index, role, score, and a short snippet
- `SessionMemory.search()` runs the same search across saved session files
- The `memory_search` tool exposes this to the agent. `scope=current` reads the live transcript. `scope=sessions` reads saved sessions. The agent refreshes that context before every model call

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

- Search the live transcript or saved sessions from a tool call:
  ```tool
  {"name": "memory_search", "args": {"query": "traceback src/app.py", "scope": "current"}}
  ```

## Extending the Memory Component

The memory layer keeps a full transcript, sends the model a shorter view of complete recent turns and older execution evidence, and can search the full transcript. `compress_salient()` and `memory_search` cover the two extensions below: finding earlier evidence and compressing history while preserving the connection between actions and their observations.

The shared LiteLLM adapter labels empty, truncated, and filtered responses. A `content_filter` finish reason counts as filtered only when the provider explicitly refuses (non-null `refusal`); channels intermittently report `content_filter` on requests that succeed unchanged on retry — including empty bodies — so those are labeled truncated and bounded by the consecutive-error limit. The agent executes none of these, stops immediately on a genuinely filtered (refused) response, and stops after `max_consecutive_model_errors` (default 3) consecutive empty/truncated responses. Calls and costs still count, and the SWE-bench exporter attempts to recover existing source edits on this early exit. Both experiment arms must use the same response handling. These repairs require new controlled evaluation; they do not change the recorded five-task memory result of 4/5 without memory versus 2/5 with memory.

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
