# CS427-agent

2025 Fall CS427 个人项目，作者 [xiaofei9289](https://github.com/xiaofei9289)。

本仓库在 [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) 上扩展了工具调用和记忆能力，并保留了课程实验的中期、期末交付物。上游代码的版权归原作者所有，见 `LICENSE.md`。

## 项目内容

- `src/minisweagent/`：agent、环境、模型，以及课程扩展的工具和记忆模块
- 工具：`read_file`、`write_file`、`refined_read_file`、`read_many_files`、`search_file_content`、`replace`、`find_definition`、`todo`
- 记忆：`HistoryManager`、`SessionMemory`、`TrajectoryReplayer`
- `deliverables_midterm/`、`deliverables_final/`：SWE-bench 运行结果与报告
- `tests/`：工具、记忆和运行流程测试

## 安装

需要 Python 3.10 及以上。

```bash
git clone https://github.com/xiaofei9289/2025Fall_CS427_agent.git
cd 2025Fall_CS427_agent
pip install -e .
```

开发依赖：

```bash
pip install -e ".[dev]"
```

## 运行

```bash
mini
```

带界面：

```bash
mini -v
```

在 Python 里调用：

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

## 测试

```bash
pytest
```

## 说明文档

- 工具扩展：`cs427_tools_extension.md`
- 记忆扩展：`cs427_memory.md`
- 上游文档：<https://mini-swe-agent.com/latest/>

## 致谢

本项目基于 Princeton 与 Stanford 团队的 [mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) 与 [SWE-agent](https://github.com/SWE-agent/SWE-agent)。如果这项工作对你有帮助，请引用 [SWE-agent 论文](https://arxiv.org/abs/2405.15793)。
