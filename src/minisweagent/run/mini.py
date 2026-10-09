#!/usr/bin/env python3

"""Run mini-SWE-agent in your local environment. This is the default executable `mini`."""
# Read this first: https://mini-swe-agent.com/latest/usage/mini/  (usage)

import os
import traceback
from pathlib import Path
from typing import Any

import typer
import yaml
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.shortcuts import PromptSession
from rich.console import Console

from minisweagent import global_config_dir
from minisweagent.agents.interactive import InteractiveAgent
from minisweagent.agents.interactive_textual import TextualAgent
from minisweagent.config import builtin_config_dir, get_config_path
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models import get_model
from minisweagent.run.extra.config import configure_if_first_time
from minisweagent.run.utils.save import save_traj
from minisweagent.utils.log import logger

# Register basic tools (read_file, write_file) so they are available in real tasks
try:  # pragma: no cover - convenience import
    import minisweagent.tools.basic  # noqa: F401
except Exception:  # noqa: BLE001
    logger.error("Failed to import basic tools", exc_info=True)

# Register refined read tool
try:  # pragma: no cover - convenience import
    import minisweagent.tools.read  # noqa: F401
except Exception:  # noqa: BLE001
    logger.error("Failed to import read tool", exc_info=True)

# Register todo tool
try:  # pragma: no cover - convenience import
    import minisweagent.tools.todo  # noqa: F401
except Exception:  # noqa: BLE001
    logger.error("Failed to import todo tool", exc_info=True)
DEFAULT_CONFIG = Path(os.getenv("MSWEA_MINI_CONFIG_PATH", builtin_config_dir / "mini.yaml"))
# Default trajectory output to repo directory for easier access
DEFAULT_OUTPUT = Path.cwd() / ".mini-swe-agent" / "last_mini_run.traj.json"
console = Console(highlight=False)
app = typer.Typer(rich_markup_mode="rich")
prompt_session = PromptSession(history=FileHistory(global_config_dir / "mini_task_history.txt"))
_HELP_TEXT = """Run mini-SWE-agent in your local environment.

[not dim]
There are two different user interfaces:

[bold green]mini[/bold green] Simple REPL-style interface
[bold green]mini -v[/bold green] Pager-style interface (Textual)

More information about the usage: [bold green]https://mini-swe-agent.com/latest/usage/mini/[/bold green]
[/not dim]
"""


# fmt: off
@app.command(help=_HELP_TEXT)
def main(
    visual: bool = typer.Option(False, "-v", "--visual", help="Toggle (pager-style) UI (Textual) depending on the MSWEA_VISUAL_MODE_DEFAULT environment setting",),
    model_name: str | None = typer.Option( None, "-m", "--model", help="Model to use",),
    model_class: str | None = typer.Option(None, "--model-class", help="Model class to use (e.g., 'anthropic' or 'minisweagent.models.anthropic.AnthropicModel')", rich_help_panel="Advanced"),
    task: str | None = typer.Option(None, "-t", "--task", help="Task/problem statement", show_default=False),
    yolo: bool = typer.Option(False, "-y", "--yolo", help="Run without confirmation"),
    cost_limit: float | None = typer.Option(None, "-l", "--cost-limit", help="Cost limit. Set to 0 to disable."),
    config_spec: Path = typer.Option(DEFAULT_CONFIG, "-c", "--config", help="Path to config file"),
    output: Path | None = typer.Option(DEFAULT_OUTPUT, "-o", "--output", help="Output trajectory file"),
    exit_immediately: bool = typer.Option( False, "--exit-immediately", help="Exit immediately when the agent wants to finish instead of prompting."),
    # Memory options
    enable_memory: bool = typer.Option(False, "--memory", help="Enable memory functionality"),
    memory_dir: str = typer.Option("", "--memory-dir", help="Directory to store memory files"),
    memory_session_id: str = typer.Option("", "--memory-session", help="Session ID for memory"),
    memory_load_session: bool = typer.Option(False, "--memory-load", help="Load previous session"),
    memory_max_messages: int = typer.Option(50, "--memory-max", help="Maximum messages to keep in history"),
) -> Any:
    # fmt: on
    configure_if_first_time()
    config = yaml.safe_load(get_config_path(config_spec).read_text())

    if not task:
        console.print("[bold yellow]What do you want to do?")
        task = prompt_session.prompt(
            "",
            multiline=True,
            bottom_toolbar=HTML(
                "Submit task: <b fg='yellow' bg='black'>Esc+Enter</b> | "
                "Navigate history: <b fg='yellow' bg='black'>Arrow Up/Down</b> | "
                "Search history: <b fg='yellow' bg='black'>Ctrl+R</b>"
            ),
        )
        console.print("[bold green]Got that, thanks![/bold green]")

    if yolo:
        config.setdefault("agent", {})["mode"] = "yolo"
    if cost_limit:
        config.setdefault("agent", {})["cost_limit"] = cost_limit
    if exit_immediately:
        config["agent"]["confirm_exit"] = False

    # Configure memory settings
    if enable_memory:
        config.setdefault("agent", {})["enable_memory"] = True
        config["agent"]["memory_max_messages"] = memory_max_messages
        if memory_dir:
            config["agent"]["memory_dir"] = memory_dir
        else:
            # Default to repo directory instead of global config dir
            repo_memory_dir = Path.cwd() / ".mini-swe-agent" / "memory"
            config["agent"]["memory_dir"] = str(repo_memory_dir)
        if memory_session_id:
            config["agent"]["memory_session_id"] = memory_session_id
        config["agent"]["memory_load_session"] = memory_load_session

    model = get_model(model_name, config.get("model", {}))
    env = LocalEnvironment(**config.get("env", {}))

    # Both visual flag and the MSWEA_VISUAL_MODE_DEFAULT flip the mode, so it's essentially a XOR
    agent_class = InteractiveAgent
    if visual == (os.getenv("MSWEA_VISUAL_MODE_DEFAULT", "false") == "false"):
        agent_class = TextualAgent

    agent = agent_class(model, env, **config.get("agent", {}))
    exit_status, result, extra_info = None, None, None
    try:
        exit_status, result = agent.run(task)  # type: ignore[arg-type]
    except Exception as e:
        logger.error(f"Error running agent: {e}", exc_info=True)
        exit_status, result = type(e).__name__, str(e)
        extra_info = {"traceback": traceback.format_exc()}
    finally:
        if output:
            save_traj(agent, output, exit_status=exit_status, result=result, extra_info=extra_info)  # type: ignore[arg-type]
    return agent


if __name__ == "__main__":
    app()
