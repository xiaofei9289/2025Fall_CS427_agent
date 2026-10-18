"""Basic agent class. See https://mini-swe-agent.com/latest/advanced/control_flow/ for visual explanation."""

import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from jinja2 import StrictUndefined, Template

from minisweagent import Environment, Model
from minisweagent.memory import HistoryManager, SessionMemory
from minisweagent.memory.search import set_search_context
from minisweagent.tools import REGISTRY as TOOL_REGISTRY
from minisweagent.tools import list_tool_specs


@dataclass
class AgentConfig:
    # The default settings are the bare minimum to run the agent. Take a look at the config files for improved settings.
    system_template: str = (
        "You are a helpful assistant that can do anything.\n"
        "If tools are available, you may call exactly one per step.\n"
        "{% if tool_specs %}Available tools:\n"
        "{% for t in tool_specs %}- {{t.name}}: {{t.description}} (parameters: {{t.parameters}})\n{% endfor %}{% endif %}"
    )
    instance_template: str = (
        "Your task: {{task}}. Provide EXACTLY ONE action in triple backticks.\n"
        "Choose one of:\n"
        "1) Bash command:\n"
        "```bash\n<your command>\n```\n"
        "2) Tool call:\n"
        "```tool\n{\"name\": \"<tool_name>\", \"args\": { ... }}\n```\n"
        "Prefer tools for reading/writing files or similar operations.\n"
        "To finish, ensure the first line of the resulting output is 'COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT'."
    )
    timeout_template: str = (
        "The last command <command>{{action['action']}}</command> timed out and has been killed.\n"
        "The output of the command was:\n <output>\n{{output}}\n</output>\n"
        "Please try another command and make sure to avoid those requiring interactive input."
    )
    format_error_template: str = (
        "Please always provide EXACTLY ONE action in triple backticks: either a ```bash``` block or a ```tool``` block."
    )
    action_observation_template: str = "Observation: {{output}}"
    step_limit: int = 0
    cost_limit: float = 3.0
    time_limit: float = 0.0
    finalization_step_reserve: int = 0
    finalization_time_reserve: float = 0.0
    finalization_cost_reserve: float = 0.0
    max_consecutive_model_errors: int = 3
    # Memory settings
    enable_memory: bool = False
    memory_max_messages: int = 50
    memory_dir: str = ""
    memory_session_id: str = ""
    memory_load_session: bool = False
    enabled_tools: list[str] | None = None


class NonTerminatingException(Exception):
    """Raised for conditions that can be handled by the agent."""


class FormatError(NonTerminatingException):
    """Raised when the LM's output is not in the expected format."""


class ExecutionTimeoutError(NonTerminatingException):
    """Raised when the action execution timed out."""


class TerminatingException(Exception):
    """Raised for conditions that terminate the agent."""


class Submitted(TerminatingException):
    """Raised when the LM declares that the agent has finished its task."""


class LimitsExceeded(TerminatingException):
    """Raised when the agent has reached its cost or step limit."""


class ModelResponseError(TerminatingException):
    """Raised when the provider cannot supply an executable response."""


class DefaultAgent:
    def __init__(self, model: Model, env: Environment, *, config_class: Callable = AgentConfig, **kwargs):
        self.config = config_class(**kwargs)
        self.messages: list[dict] = []
        self.model = model
        self.env = env
        self.started_at = time.monotonic()
        self.budget_phase = "solving"
        self.limit_reason = ""
        # Make tools available (if any are registered) without changing defaults
        names = self.config.enabled_tools
        if names is not None and (unknown := set(names) - TOOL_REGISTRY.keys()):
            raise ValueError(f"Unknown enabled tools: {sorted(unknown)}")
        self.tools = TOOL_REGISTRY if names is None else {name: TOOL_REGISTRY[name] for name in names}
        self.retrieval_gate = {"code_search", "repo_map"} & set(names or [])
        self.retrieval_used = False
        self.extra_template_vars = {"tool_specs": [spec for spec in list_tool_specs() if spec["name"] in self.tools]}

        # Initialize memory components if enabled
        self.history_manager = None
        self.session_memory = None
        if self.config.enable_memory:
            self.history_manager = HistoryManager(
                max_messages=self.config.memory_max_messages
            )
            if self.config.memory_dir:
                self.session_memory = SessionMemory(
                    memory_dir=Path(self.config.memory_dir),
                    session_id=self.config.memory_session_id or None
                )

    def render_template(self, template: str, **kwargs) -> str:
        template_vars = asdict(self.config) | self.env.get_template_vars() | self.model.get_template_vars()
        return Template(template, undefined=StrictUndefined).render(
            **kwargs, **template_vars, **self.extra_template_vars
        )

    def add_message(self, role: str, content: str, **kwargs):
        self.messages.append({"role": role, "content": content, **kwargs})

    def run(self, task: str, **kwargs) -> tuple[str, str]:
        """Run step() until agent is finished. Return exit status & message"""
        self.started_at = time.monotonic()
        self.budget_phase, self.limit_reason = "solving", ""
        self.extra_template_vars |= {"task": task, **kwargs}

        # Load session if requested and available
        if self.config.enable_memory and self.config.memory_load_session and self.session_memory:
            loaded_messages = self.session_memory.get_messages()
            if loaded_messages:
                self.messages = loaded_messages.copy()  # Start with loaded history
                # Add new task message to continue the conversation
                self.add_message("user", self.render_template(self.config.instance_template))
            else:
                # No session found, start fresh
                self.messages = []
                self.add_message("system", self.render_template(self.config.system_template))
                self.add_message("user", self.render_template(self.config.instance_template))
        else:
            # Normal operation without memory loading
            self.messages = []
            self.add_message("system", self.render_template(self.config.system_template))
            self.add_message("user", self.render_template(self.config.instance_template))

        while True:
            try:
                self.step()
            except NonTerminatingException as e:
                self.add_message("user", str(e))
            except TerminatingException as e:
                self.add_message("user", str(e))
                # Save session before exiting if memory is enabled
                if self.config.enable_memory and self.session_memory:
                    self.session_memory.save_session(self.messages, {"exit_status": type(e).__name__})
                return type(e).__name__, str(e)

    def step(self) -> dict:
        """Query the LM, execute the action, return the observation."""
        return self.get_observation(self.query())

    def budget_state(self) -> dict:
        return {
            "phase": self.budget_phase, "limit_reason": self.limit_reason,
            "remaining_steps": max(0, self.config.step_limit - self.model.n_calls) if self.config.step_limit > 0 else None,
            "remaining_cost": max(0.0, self.config.cost_limit - self.model.cost) if self.config.cost_limit > 0 else None,
            "remaining_seconds": max(0.0, self.config.time_limit - (time.monotonic() - self.started_at))
            if self.config.time_limit > 0 else None,
        }

    def check_budget(self) -> None:
        remaining = self.budget_state()
        for name in ("steps", "cost", "seconds"):
            if remaining[f"remaining_{name}"] == 0:
                self.limit_reason = name
                raise LimitsExceeded(f"Budget exhausted: {name}")
        reserves = {"steps": self.config.finalization_step_reserve, "cost": self.config.finalization_cost_reserve,
                    "seconds": self.config.finalization_time_reserve}
        if self.budget_phase != "finalizing" and any(
            reserve > 0 and remaining[f"remaining_{name}"] is not None and remaining[f"remaining_{name}"] <= reserve
            for name, reserve in reserves.items()
        ):
            self.budget_phase = "finalizing"
            self.add_message("user", (
                "FINALIZATION: The remaining budget is reserved for finishing the task. "
                f"Remaining model calls: {remaining['remaining_steps']}; "
                f"cost budget: {remaining['remaining_cost']}; seconds: {remaining['remaining_seconds']}. "
                "Stop broad searches and comparisons with other versions. Inspect the current git diff; "
                "if no fix exists, use the evidence already collected to implement the smallest justified fix. "
                "Run focused tests if time permits, then submit the patch using the task's submission command. "
                "Do not claim tests passed unless their output confirms it. Hard limits still apply."
            ))

    def query(self) -> dict:
        """Query the model and return the response."""
        self.check_budget()

        # Keep the full transcript searchable, and send a salient subset when memory is on.
        set_search_context(self.messages, self.session_memory)
        messages_to_send = self.messages
        if self.config.enable_memory and self.history_manager:
            # Memory must fail gracefully: an impossible compression limit falls back
            # to the full transcript instead of breaking the agent.
            try:
                messages_to_send = self.history_manager.prompt_messages(self.messages)
            except ValueError:
                messages_to_send = self.messages

        # Keep failed responses in the audit transcript, but do not feed empty
        # assistant turns back to the provider on the next attempt.
        messages_to_send = [
            message for message in messages_to_send
            if not (message.get("role") == "assistant" and not (message.get("content") or "").strip())
        ]
        response = self.model.query(messages_to_send)
        if self.config.enable_memory and self.history_manager:
            extra = response.setdefault("extra", {})
            extra["memory"] = {
                "full_messages": len(self.messages),
                "sent_messages": len(messages_to_send),
                "evidence": any(
                    isinstance(message.get("content"), str) and message["content"].startswith("[memory]")
                    for message in messages_to_send
                ),
            }
        self.add_message("assistant", **response)
        return response

    def get_observation(self, response: dict) -> dict:
        """Execute the action and return the observation."""
        self.check_model_response(response)
        output = self.execute_action(self.parse_action(response))
        observation = self.render_template(self.config.action_observation_template, output=output)
        self.add_message("user", observation, extra={"returncode": output.get("returncode")})
        return output

    @staticmethod
    def response_status(response: dict) -> str:
        return response.get("extra", {}).get("response_status") or (
            "ok" if (response.get("content") or "").strip() else "empty"
        )

    def check_model_response(self, response: dict) -> None:
        """Keep provider failures out of action parsing and bound empty-response loops."""
        status = self.response_status(response)
        if status == "filtered":
            raise ModelResponseError("Provider returned content_filter; no action was executed.")
        if status not in {"empty", "truncated"}:
            return
        consecutive = 0
        # Deriving this from the full transcript also preserves the limit on resume.
        for message in reversed(self.messages):
            if message.get("role") != "assistant":
                continue
            if self.response_status(message) not in {"empty", "truncated"}:
                break
            consecutive += 1
        consecutive = max(1, consecutive)
        if consecutive >= max(1, self.config.max_consecutive_model_errors):
            raise ModelResponseError(f"Provider returned {consecutive} consecutive empty or truncated responses.")
        raise NonTerminatingException(
            f"Model response was {status}; no action was executed. "
            "Return a complete response containing exactly one bash or tool action block."
        )

    def parse_action(self, response: dict) -> dict:
        """Parse a single action: either a bash block or a tool block.

        Tool syntax:
            ```tool
            {"name": "read_file", "args": {"path": "..."}}
            ```
        Bash syntax (existing):
            ```bash
            echo hello
            ```
        """
        content = response["content"]
        tool_blocks = re.findall(r"```tool\n(.*?)\n```", content, re.DOTALL)
        bash_blocks = re.findall(r"```bash\n(.*?)\n```", content, re.DOTALL)

        if len(tool_blocks) + len(bash_blocks) != 1:
            raise FormatError(self.render_template(self.config.format_error_template, actions=[]))

        if tool_blocks:
            try:
                payload = json.loads(tool_blocks[0].strip())
                name = payload["name"]
                args = payload.get("args", {})
                return {"kind": "tool", "tool_name": name, "tool_args": args, **response}
            except Exception as e:  # noqa: BLE001
                raise FormatError(f"Invalid tool payload: {e}")

        # Fallback: bash (original behavior)
        return {"kind": "bash", "action": bash_blocks[0].strip(), **response}

    def execute_action(self, action: dict) -> dict:
        if self.retrieval_gate and not self.retrieval_used:
            if action.get("kind") != "tool" or action.get("tool_name") not in self.retrieval_gate:
                names = " or ".join(sorted(self.retrieval_gate))
                example = sorted(self.retrieval_gate)[0]
                raise FormatError(
                    f"Call {names} before any other action. Use exactly one tool block:\n"
                    f'```tool\n{{"name": "{example}", "args": {{"query": "keywords from the issue"}}}}\n```'
                )
            self.retrieval_used = True
        # Dispatch tool calls if present; otherwise, execute bash as before
        if action.get("kind") == "tool":
            tool_name = action.get("tool_name", "")
            tool = self.tools.get(tool_name)
            if not tool:
                output = {"output": f"Unknown tool: {tool_name}", "returncode": 127}
                self.has_finished(output)
                return output
            try:
                # Prefer passing env if tool supports it; fall back otherwise
                try:
                    output = tool(action.get("tool_args", {}), self.env)  # type: ignore[misc]
                except TypeError:
                    output = tool(action.get("tool_args", {}))  # type: ignore[call-arg]
            except Exception as e:  # noqa: BLE001
                output = {"output": f"Tool '{tool_name}' error: {e}", "returncode": 1}
            self.has_finished(output)
            return output

        try:
            output = self.env.execute(action["action"])
        except subprocess.TimeoutExpired as e:
            output = e.output.decode("utf-8", errors="replace") if e.output else ""
            raise ExecutionTimeoutError(
                self.render_template(self.config.timeout_template, action=action, output=output)
            )
        except TimeoutError:
            raise ExecutionTimeoutError(self.render_template(self.config.timeout_template, action=action, output=""))
        self.has_finished(output)
        return output

    def has_finished(self, output: dict[str, str]):
        """Raises Submitted exception with final output if the agent has finished its task."""
        lines = output.get("output", "").lstrip().splitlines(keepends=True)
        if lines and lines[0].strip() in ["MINI_SWE_AGENT_FINAL_OUTPUT", "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"]:
            raise Submitted("".join(lines[1:]))
