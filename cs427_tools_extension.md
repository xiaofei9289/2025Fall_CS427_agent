# CS427 Course Project: Extending mini-swe-agent with Tools

This document summarizes the current tool integration in mini-swe-agent and
provides guidance for CS427 students who will extend the agent with additional
capabilities. The overarching goal is to keep the agent small and transparent
while letting the language model invoke safe, well-defined tools in addition to
raw bash commands.

## Current Architecture

### Tool Registry
- Location: `src/minisweagent/tools/__init__.py`
- Exposes a minimal `Tool` protocol:
  ```python
  class Tool(Protocol):
      name: str
      description: str
      parameters: dict  # JSON-schema-like metadata
      def __call__(self, args: dict, env: Any | None = None) -> dict: ...
  ```
- Global registry `REGISTRY` holds tool instances. Use `register(tool)` to add
  new tools and `list_tool_specs()` to expose lightweight metadata to prompts.

### Example Built-in Tool
- `read_file` (see `src/minisweagent/tools/basic.py`):
  - Auto-registered.
  - When the agent has an environment (e.g., Docker in SWEBench), it executes
    `cat` via `env.execute(...)`. When no environment is provided (local use),
    it reads from the host filesystem.
  - Returns `{"output": str, "returncode": int}` to match the shape of bash
    command results.

### Agent Integration
- The default agent (`src/minisweagent/agents/default.py`):
  - Accepts exactly one action per step, either:
    ```bash
    ```bash
    <command>
    ```
    ```
    or
    ```python
    ```tool
    {"name": "tool_name", "args": {...}}
    ```
    ```
  - Parses tool blocks and dispatches through the registry, passing `env` when
    possible so tools can interact with sandboxes.
  - Observations are appended in the same format as bash executions, keeping
    the trajectory linear and easy to inspect.

### SWEBench Runner
- `src/minisweagent/run/extra/swebench.py` imports the tool module so tools are
  available during batch runs.
- The SWEBench configuration (`src/minisweagent/config/extra/swebench.yaml`)
  shows available tools in the prompt to encourage the model to use them.

## Extending the Toolset

### Steps to Add a New Tool
1. Create a new module under `src/minisweagent/tools/` (or extend
   `basic.py` if the tool is general-purpose).
2. Implement a dataclass that satisfies the `Tool` protocol:
   ```python
   @dataclass
   class MyTool:
       name: str = "my_tool"
       description: str = "Describe what it does."
       parameters: dict = field(default_factory=lambda: {
           "type": "object",
           "properties": {
               "path": {"type": "string"},
               "pattern": {"type": "string"},
           },
           "required": ["path"],
           "additionalProperties": False,
       })

       def __call__(self, args: dict, env: Any | None = None) -> dict:
           ...
           return {"output": result_text, "returncode": 0}
   ```
3. Register the tool at import time with `register(MyTool())` so a single import
   makes it available.
4. If the tool should appear in SWEBench runs, import the module in
   `swebench.py` (or use a configuration hook).
5. Add unit tests under `tests/tools/` to cover success/failure cases and any
   security checks.

### Important Tips
- **Use the Environment When Possible:** Tools that operate on the SWEBench
  dataset must issue commands inside the sandboxed environment. When the agent
  passes `env`, call `env.execute("...")` to run commands inside the container
  (working directory `/testbed`). For example, a write tool might execute:
  ```python
  env.execute("printf %s ... | base64 -d > /testbed/path")
  ```

  Note that if a tool doesn't need to operation within the SWEBench docker (e.g. maintaining a TODO list),
  it is ok to handle everything in your local environment.

- **Validate Paths:** For container-aware tools, restrict operations to paths
  under the environment’s working directory (`/testbed`).
- **Timeouts & Safety:** Prefer simple, deterministic commands. Avoid long
  running operations or blind `shell=True` on user strings. Document any
  non-trivial behavior in comments.
- **Return Shape:** Always return `{"output": str, "returncode": int}`. Keep
  outputs concise (truncate or summarize) to avoid bloating the prompt.
- **Prompt Exposure:** Make sure the tool’s `description` and `parameters` are
  understandable—these strings are fed into the system prompt, so clarity
  matters for the language model.

## Expectations for the Course Project
- **Understand the Baseline:** Review the existing `read_file` tool and how the
  agent integrates tools.
- **Add New Tools:** Propose and implement additional tools that improve the
  agent’s effectiveness (e.g., search, format, patch apply, test helpers).
- **SWEBench Compatibility:** Tools intended for SWEBench must work through the
  Docker environment—i.e., implement their logic as a sequence of bash commands
  executed via `env.execute(...)`. Host-side operations have no effect on the
  benchmark.
- **Safety & Documentation:** Document assumptions, error handling, and any
  constraints (path restrictions, output limits). Ensure tools fail gracefully.

By following these guidelines, you will extend mini-swe-agent without losing
its core simplicity, and you’ll create a clear foundation for automated
evaluations on SWEBench and beyond.

