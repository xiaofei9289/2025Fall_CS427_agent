# 5v5 retrieval ablation（DeepSeek，50 题）

目的：用 5 轮 baseline 与 5 轮 retrieval 的 50 题运行，估计单轮方差，再判断
`code_search` / `repo_map` 是否带来可重复的解决率变化。两组使用 `deepseek/deepseek-chat`、
400 步、每题 10 美元、无 300 秒墙、4 workers；`baseline.yaml` 与 `retrieval.yaml` 只差
retrieval 工具和对应提示词。

## 2026-10-18 设计修订（未运行）

旧 `retrieval.yaml` 同时改变了三件事：工具、提示词，以及由 `enabled_tools` 自动开启的
`retrieval_gate`（第一个动作必须是检索）。因此旧配置不是干净的“工具可用性”对照，不能把
差异单独归因于 `code_search`/`repo_map`。启动 retrieval 臂前先决定 estimand，使用拆分后的配置：

| Arm | 配置 | 变化 |
| --- | --- | --- |
| A | `baseline.yaml` | 无 brief、无 BM25 工具、无 gate |
| B | `brief_only.yaml` | 只加确定性 `repo_brief`，不开放 `code_search`/`repo_map` |
| C | `retrieval.yaml` | brief + `code_context`/`code_search`/`repo_map`/`find_references` + 检索后行动提示 |
| D | `retrieval_gate.yaml` | 旧行为：工具 + 提示词 + 强制首步检索 |

B 用来隔离“预检索上下文”，C−B 才是“检索工具/行动策略”的增量，C−D 用来估计 gate 的影响。
正式比较仍需要至少 2 轮、最好 3 轮，报告配对 CI；单轮 1–2 题差异落在 37–42 的 baseline 方差内，
不能作为收益证据。旧的 `pilot_20261017`/`gate-20261017` 结果继续作为历史证据，不与新配置混算。

## 当前状态（台式机，2026-10-18）

| 轮次 | 源码 | 通过 | 空补丁 | 评分错误 | 调用 | 成本（USD） |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| baseline_r1 | `07d8...` | 37/50 | 0 | 0 | 1288 | 0.2652 |
| baseline_r2 | `07d8...` | 40/50 | 1 | 0 | 1940 | 0.8551 |
| baseline_r3 | `07d8...` | — | — | — | — | — |
| retrieval_r1–r5 | — | 未开始 | | | | |

- r1/r2 与 `deepseek_scale50_20261018/baseline_r2` 使用同一 `baseline.yaml`、同一
  `tasks.json`、同一 `07d8...` 源码；第三次同配置 baseline 为 42/50。三次运行范围为
  **37–42**，r1 与 r2 之间有 **7 个任务翻转**。
- r2 的 1 个空补丁是 `django__django-15280`；退出状态为 48 Submitted、1 LimitsExceeded、
  1 RecoveredPatch。audit 将 2 题归为 `budget_exhausted`，但评分错误为 0。
- r3 在加载 HuggingFace 数据集时遇到 `Network is unreachable`，重试 5 次后停止，未产生
  任何任务或预测。原因是该快照仍使用旧的 `load_dataset`，没有 Mac HEAD 的
  `hf_dataset.load_hf_dataset` 离线回退。修法：同步 Mac HEAD，或预热/挂载 HF cache 后
  用新目录重跑 r3。
- retrieval 臂尚未开始。在 baseline 方差未估计、源码版本未确定前，不应启动 retrieval 臂。
- 以上结果全部来自 `07d8...`（不含 2026-10-18 审查的 7 个修复），只能描述该源码快照。

## 运行（台式机 Linux 容器）

```bash
python experiments/ablation5v5_20261018/run.py generation --config baseline.yaml --tag baseline_r3 --workers 4
python experiments/ablation5v5_20261018/run.py grading --config baseline.yaml --tag baseline_r3 --workers 4
```

`run_all.py` 会按 baseline r1–r5、retrieval r1–r5 顺序执行，并跳过已有
`evaluation/grading_summary.json` 的轮次。`run.py` 拒绝在非 Linux 主机运行。

## 解释边界

单轮 50 题结果不足以支持 retrieval 的因果结论；本目录的用途是把 37–42 的运行方差先量化，
再用多轮配对比较。42/50 的 scale baseline 不应被当作固定真值，memory 等其他组件的
单轮 ±2 题差异也不能直接归因。

## 2026-10-19 四臂工具 ablation（一轮）

使用 `tasks10.json`、四份 `configs/{baseline,brief_only,retrieval,retrieval_gate}.yaml`
和 `desktop.py` 完成一轮 generation + official grading：

| Arm | Resolved | Cost | Calls | Retrieval tool calls |
| --- | ---: | ---: | ---: | ---: |
| baseline | 8/10 | $0.1023 | 217 | 0 |
| brief | 8/10 | $0.0806 | 201 | 0 |
| retrieval | 9/10 | $0.0499 | 139 | **0** |
| gate | 9/10 | $0.1014 | 268 | 10 |

关键的负面发现：**retrieval 臂没有调用任何检索工具**，所以 9/10 不能归因于
`code_search` / `repo_map` / `code_context` / `find_references`；gate 臂强制调用了
`repo_map` 和 `code_search`，与 retrieval 同为 9/10，但成本约为 2 倍、调用 268 vs 139。
按预注册规则停止同一 config 的第二轮，先修工具曝光或把 gate 明确当作 package treatment。
详见 [FOUR_ARM_20261019.md](FOUR_ARM_20261019.md)。
