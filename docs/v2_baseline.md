# V2 可复现基线

本分支（`feature/codepair-v2`，从本地 `main@2fe0f6c` 切出）只做工程基线整理：
修复安装/导入/测试入口的可复现性问题，不改写 Agent，不移动或覆盖 `experiments/`
下的历史实验记录。

## 这一步解决的问题

早期公开 `origin/main` 曾停留在缺少 memory/search、retrieval tools、audit 和
localization 实现的状态，因此会出现“`default.py` 引用了不存在的模块”的错觉。
当前本地 `main` 与 `origin/main` 都在 `20af3e2`，已包含这些实现；本节保留为历史
说明，不再描述当前分支差异。

接口核对结果：

| 调用方 | 实现位置 | 状态 |
|---|---|---|
| `default.py: from minisweagent.memory.search import set_search_context` | `src/minisweagent/memory/search.py` | 存在，含 `set_search_context` / `MemorySearch` |
| `default.py: HistoryManager.prompt_messages(...)` | `src/minisweagent/memory/history.py:374` | 存在 |
| `code_search` / `repo_map` / `code_context` | `src/minisweagent/tools/code_search.py` | 存在并注册 |
| `find_references` | `src/minisweagent/tools/find_references.py` | 存在并注册；轻量 AST 关系扫描 |
| `repo_brief` | `src/minisweagent/retrieval/brief.py` / `brief_tool.py` | 存在；容器内注入，不依赖安装包 |
| AST 索引、BM25、上下文与缓存 | `src/minisweagent/retrieval/repository.py` | 存在；容器内注入同一文件执行 |
| `audit.py` | `src/minisweagent/run/extra/audit.py` | 存在 |
| `localization_eval.py` | `src/minisweagent/run/extra/localization_eval.py` | 存在 |
| `retrieval_audit.py` | `src/minisweagent/run/extra/retrieval_audit.py` | 存在；逐轨迹归因 |
| `prepare_checkouts.py` | `experiments/localization_verified5/prepare_checkouts.py` | 存在；重建冻结副本 |

另外修复了三处会破坏“换个终端/换台机器就复现不了”的问题：

1. `uv venv` 默认不安装 pip，原验收命令 `python -m pip install -e ".[dev]"` 会直接
   报 `No module named pip`。下文给出 `--seed` 和 `ensurepip` 两种可复现做法。
2. CLI 集成测试直接执行 `mini` / `mini-extra`，依赖虚拟环境已经激活并进入 `PATH`。
   现在先查 `PATH`，再查当前解释器同目录的 console script，未激活虚拟环境也能跑。
3. 默认 `pytest -q` 会把需要 Docker/Singularity、终端或 Hugging Face 网络的 slow
   用例一起执行，在离线机器上必然失败。现在默认只跑离线回归集；slow 用例用
   `pytest -q -m slow` 显式开启。

## 环境

要求 Python 3.10+；本基线在 Python 3.11.12 / macOS 上验证。

```bash
# 推荐：uv 创建带 pip 的环境
uv venv --python 3.11 --seed .venv
source .venv/bin/activate

# 如果沿用已有的 uv 环境（没有 pip）
python -m ensurepip --upgrade

python -m pip install -e ".[dev]"
```

也可以直接用 uv 安装到现有环境：

```bash
uv pip install -e ".[dev]" --python .venv/bin/python
```

## 验收

```bash
# 1. Agent 导入
python -c "from minisweagent.agents.default import DefaultAgent; print('Agent import OK')"

# 2. 默认离线回归测试
pytest -q

# 3. slow / Docker / 网络集成测试（在台式机或有 Docker 的环境）
pytest -q -m slow

# 4. 一条命令跑完 1-3 中的离线部分
python scripts/verify_v2_baseline.py
```

`scripts/verify_v2_baseline.py` 不调用模型、不需要 Docker，依次检查：

- editable 安装是否指向本仓库的 `src/`；
- `DefaultAgent`、memory/search、audit、localization_eval、swebench 是否可导入；
- 工具注册表、`read_file` / `write_file`、`code_search` / `code_context` / `find_references` 是否能独立执行；
- `experiments/configs/baseline.yaml`、`brief_only.yaml`、`retrieval.yaml`、`retrieval_gate.yaml` 是否能通过 SWE-bench 入口加载；
- 默认离线测试是否通过。

本机验证结果（2026-10-18，Python 3.11.12）：

```text
674 passed, 19 skipped, 51 deselected
```

服务测试中依赖 `os.killpg` 的用例对沙箱敏感；同一天较早一次运行曾在 DSH 文件沙箱下报
`PermissionError: Operation not permitted`，最新全量运行通过。台式机上的服务测试仍需单独复跑。

51 个 deselected 均为 `@pytest.mark.slow`，包括 Docker/Singularity 环境测试、
`test_swebench.py` 的 Docker 端到端流程和需要 HF dummy 数据集网络的用例。它们不是
V2 的默认门禁；在台式机执行：

```bash
pytest -q -m slow
```

## 边界

- 本阶段没有重写 `DefaultAgent`，也没有改动 `experiments/`、`deliverables_*` 和
  `desktop_validation/` 中的历史结果。
- slow 套件依赖 Docker、公开 dummy 数据集和网络，当前 Mac 没有 Docker daemon，
  因此只验证了默认离线套件与不依赖 Docker 的入口。
- 没有调用任何模型 API；SWE-bench 配置验证只加载 YAML 和 CLI，不产生费用。
- 公开仓库的修复以本分支推送后为准；在推送前，GitHub `main` 仍可能落后于本地实现。
