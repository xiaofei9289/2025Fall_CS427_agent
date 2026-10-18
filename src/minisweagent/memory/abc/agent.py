"""A minimal memory-aware agent for the A/B/C experiment.

The agent reuses the existing action parser, environment execution, tool
dispatch, and budget checks.  It replaces only the prompt-construction path: the
full transcript stays in ``self.messages``; each model call gets a ``PromptView``
built by one of the three policies; and the view's accounting is written to a
per-task JSONL trace so the report can audit the budget after the run.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from minisweagent.agents.default import (
    AgentConfig,
    DefaultAgent,
    NonTerminatingException,
    TerminatingException,
)

from .budget import BudgetError, estimate_tokens, message_text
from .policy import PolicyLimits, build_policy
from .search import MemorySearchTool, SearchContext


class MemoryBudgetError(TerminatingException):
    """The prompt cannot be constructed without dropping the task or newest turn."""


@dataclass
class MemoryAgentConfig(AgentConfig):
    """Agent settings used by the clean experiment.

    ``context_token_limit`` and the legacy message-count fields are not used;
    the memory fields below are the single source of truth.  Keeping the legacy
    fields at their defaults means the base class does not instantiate its old
    ``HistoryManager``.
    """

    memory_policy: str = "window"
    memory_total_tokens: int = 8000
    memory_summary_tokens: int = 1000
    memory_retrieval_tokens: int = 1500
    memory_trace_path: str = ""


def tool_spec(tool: Any) -> dict[str, Any]:
    """Return the prompt-visible spec for a tool instance."""
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }


class MemoryTrace:
    """Append-only, per-task record of every prompt view."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, view, *, step: int, full_messages: int) -> None:
        if self.path is None:
            return
        payload = {
            "step": step,
            "policy": view.policy,
            "budget": view.total_tokens,
            "pinned_tokens": view.pinned_tokens,
            "summary_tokens": view.summary_tokens,
            "retrieval_tokens": view.retrieval_tokens,
            "max_retrieval_tokens": view.max_retrieval_tokens,
            "sent_messages": len(view.sent_indices),
            "dropped_messages": len(view.dropped_indices),
            "sent_indices": list(view.sent_indices),
            "dropped_indices": list(view.dropped_indices),
            "summary_present": view.summary_present,
            "summary_text": view.summary_text,
            "task_index": view.task_index,
            "task_present": view.task_present,
            "clipped": view.clipped,
            "budget_enforced": view.budget_enforced,
            "full_messages": full_messages,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


class MemoryAgent(DefaultAgent):
    """Agent whose model prompt is built by a pre-registered memory policy."""

    def __init__(
        self,
        model,
        env,
        *,
        config_class=MemoryAgentConfig,
        **kwargs,
    ):
        super().__init__(model, env, config_class=config_class, **kwargs)
        self.memory = build_policy(
            self.config.memory_policy,
            PolicyLimits(
                total_tokens=self.config.memory_total_tokens,
                summary_tokens=self.config.memory_summary_tokens,
                retrieval_tokens=self.config.memory_retrieval_tokens,
            ),
        )
        self.search_context = SearchContext()
        # Copy before mutating: with enabled_tools=None the base class exposes the
        # global registry dict itself, and A/B must not remove entries from it.
        self.tools = dict(self.tools)
        # A/B must not expose the tool even if a global registry happens to
        # contain the legacy one.  C installs the clean tool bound to this run.
        self.tools.pop("memory_search", None)
        if self.config.memory_policy == "summary_search":
            self.tools["memory_search"] = MemorySearchTool(
                self.search_context,
                token_limit=self.config.memory_retrieval_tokens,
            )
        self.retrieval_gate = set()
        self.extra_template_vars["tool_specs"] = [tool_spec(tool) for tool in self.tools.values()]
        self.tracer = MemoryTrace(self.config.memory_trace_path)
        if not self.config.memory_policy:
            raise ValueError("memory_policy must be set")
        if self.memory.name != self.config.memory_policy:
            raise ValueError(f"policy name mismatch: {self.memory.name!r} != {self.config.memory_policy!r}")

    def run(self, task: str, **kwargs) -> tuple[str, str]:
        """Run one task with tagged messages and the clean memory view."""
        self.started_at = time.monotonic()
        self.budget_phase, self.limit_reason = "solving", ""
        self.extra_template_vars |= {"task": task, **kwargs}
        self.messages = []
        self.add_message("system", self.render_template(self.config.system_template), extra={"kind": "system"})
        self.add_message("user", self.render_template(self.config.instance_template), extra={"kind": "task"})
        while True:
            try:
                self.step()
            except NonTerminatingException as error:
                self.add_message("user", str(error), extra={"kind": "feedback"})
            except TerminatingException as error:
                self.add_message("user", str(error), extra={"kind": "terminal"})
                return type(error).__name__, str(error)

    def query(self) -> dict:
        self.check_budget()
        step = self.model.n_calls + 1
        # The tool can see exactly the messages that exist before this call.
        self.search_context.update(self.messages, step)
        try:
            view = self.memory.build(self.messages)
        except BudgetError as error:
            raise MemoryBudgetError(str(error)) from error
        self.tracer.record(view, step=step, full_messages=len(self.messages))
        api_messages = [{"role": message.get("role", "user"), "content": message_text(message)} for message in view.messages]
        response = self.model.query(api_messages)
        extra = response.setdefault("extra", {})
        metadata = view.metadata()
        metadata["step"] = step
        extra["memory"] = metadata
        self.add_message("assistant", **response)
        return response

    def get_observation(self, response: dict) -> dict:
        self.check_model_response(response)
        output = self.execute_action(self.parse_action(response))
        observation = self.render_template(self.config.action_observation_template, output=output)
        extra: dict[str, Any] = {"kind": "observation", "returncode": output.get("returncode")}
        tool_extra = output.get("extra")
        if isinstance(tool_extra, dict):
            extra.update(tool_extra)
        self.add_message("user", observation, extra=extra)
        return output

    def context_stats(self) -> dict[str, int]:
        """Small convenience for tests and logs; the trace is the auditable record."""
        return {
            "messages": len(self.messages),
            "estimated_tokens": estimate_tokens(self.messages),
            "model_calls": self.model.n_calls,
        }
