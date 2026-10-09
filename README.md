# CS427-agent

Personal project for CS427, Fall 2025, by [xiaofei9289](https://github.com/xiaofei9289).

This repository extends [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) with tool calling and memory, and keeps the midterm and final course deliverables. Copyright for the upstream code remains with the original authors. See `LICENSE.md`.

## Contents

- `src/minisweagent/`: the agent, environments, models, and the course extensions for tools and memory
- Tools: `read_file`, `write_file`, `refined_read_file`, `read_many_files`, `search_file_content`, `replace`, `find_definition`, `todo`
- Memory: `HistoryManager`, `SessionMemory`, `TrajectoryReplayer`
- `deliverables_midterm/`, `deliverables_final/`: SWE-bench run results and reports
- `tests/`: tests for tools, memory, and the run flow

## Installation

Python 3.10 or newer is required.

```bash
git clone https://github.com/xiaofei9289/2025Fall_CS427_agent.git
cd 2025Fall_CS427_agent
pip install -e .
```

Development dependencies:

```bash
pip install -e ".[dev]"
```

## Run

```bash
mini
```

With the visual interface:

```bash
mini -v
```

From Python:

```python
from minisweagent.agents.default import DefaultAgent
from minisweagent.environments.local import LocalEnvironment
from minisweagent.models.litellm_model import LitellmModel

agent = DefaultAgent(
    LitellmModel(model_name="..."),
    LocalEnvironment(),
)
agent.run("Write a sudoku game")
```

## Tests

```bash
pytest
```

## Documentation

- Tool extension: `cs427_tools_extension.md`
- Memory extension: `cs427_memory.md`
- Upstream docs: <https://mini-swe-agent.com/latest/>

## Acknowledgments

This project is based on [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) and [SWE-agent](https://github.com/SWE-agent/SWE-agent) from the Princeton and Stanford teams. If you find this work helpful, please cite the [SWE-agent paper](https://arxiv.org/abs/2405.15793).
