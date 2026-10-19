# A/B/C 记忆实验：设计与预注册

状态：干净实现已完成，尚未运行正式实验。本文是跑之前冻结的实验设计；结果必须按这里的判据解释。

## 0. 一句话

在同一源码、模型、任务、普通工具和 8000 估算 token 预算下，比较**完整轮窗口（A）**、**同一窗口加证据摘要（B）**、**同一摘要策略加当前 run 历史检索（C）**。主对比是 **C−B**：检索是否比“同样的摘要”多带来收益。

## 1. 研究问题与假设

- **H1（主）**：在生效题上（至少一方丢弃/截断，或 C 调用过检索），C 的成功率高于 B。
- **H2**：在生效题上（B 或 A 丢弃/截断），B 高于 A。
- **H3**：C 高于 A（整套 memory 方案）。
- 零假设：对应差值不大于 0。C−B 为负或置信区间跨 0 时，不宣称检索有收益；不能把“C 用了几次检索”当成收益。

## 2. 三组与唯一变量

| | A | B | C |
| --- | --- | --- | --- |
| `memory_policy` | `window` | `summary` | `summary_search` |
| 保留任务 | 是 | 是 | 是 |
| 历史单位 | 完整 turn | 完整 turn | 完整 turn |
| 超限后 | 丢最旧完整 turn | 丢最旧完整 turn，保留证据摘要 | 同 B |
| `memory_search` | 无 | 无 | 有，仅当前 run；C-only 调用说明；首次写/提交前至少一次 gate |
| 其他工具 | 相同 | 相同 | 相同 |

配置文件在 `configs/base.yaml` + `configs/{a,b,c}.yaml`。每个 arm 文件**只能**设置 `agent.memory_policy`，`study_config.py` 会拒绝任何其他覆盖。`memory_search` 不在 `enabled_tools` 里，由 C 的 policy 安装；C 的 policy 还会在 system prompt 末尾追加一段“何时调用 memory_search”的说明，并在第一次写文件或提交前要求至少一次检索。这两项都是 C treatment 的一部分，A/B 不包含；用 `MSWEA_MEMORY_SEARCH_GATE=0` 可关闭 gate，做自然 C 的敏感性检查。

### 2.1 Sham-search 控制

为了把“检索到有用内容”与“只是多了一个工具/提示/gate”分开，C 支持一个控制臂：
`MSWEA_MEMORY_SHAM=1` 时仍安装同名、同 schema、同描述的 `memory_search`，gate 也照常计数，但工具始终返回
`No matching messages in this run's transcript.`，`retrieval_tokens=0`。C-real 与 C-sham 使用同一
源码、任务、预算、提示和 gate，只有返回内容不同；两者的解决率差异才接近“有用检索”的效应。
运行标签必须分开，例如 `sham_real` 与 `sham_ctl`，不能混在同一 tag 中。该控制不改变 A/B/C
的 p2final 结论；它需要单独一轮实验。

## 3. 固定条件

- 模型：`deepseek/deepseek-chat`，temperature 0。
- 任务：`tasks.json` 的 50 个 SWE-bench Verified 实例；`pilot.json` 是前 10 个。
- 预算：每题 400 步、10 美元；提示词 8000 估算 token。
- 工具：`read_file`、`write_file`、`refined_read_file`、`search_file_content`、`replace`、`find_definition`、`read_many_files` 三组相同。
- 源码：桌面启动器首次运行冻结 `src`，readonly 挂载；manifest 记录源码哈希。源码或配置变化必须换新 study 目录。
- 评分：官方 SWE-bench harness；空补丁算未解决。

## 4. 预算：唯一口径

### 4.1 估算器

每条消息 `ceil(字符数 / 4) + 4`，其中 4 是 role/格式开销。总预算 8000；摘要 1000；单次检索结果 1500。三组共用同一个估算器。报告同时读取 provider 的 `usage.prompt_tokens` 做校准，但**门限按估算 token 执行**。

### 4.2 组合顺序

1. system prompt + 当前 task：固定，永不丢；放不下就硬失败，不静默丢任务。
2. 最新一个完整 turn：固定；只有它单独超预算时才截断它的 observation，保留 action。若 action 单独就超预算（例如模型输出损坏或失控），截断 action 并记录 clipped；不因此终止任务，下一次模型调用仍保留 task 和这一截断后的 action。
3. 摘要（B/C）：最多 1000；放不下就丢摘要，绝不为了摘要挤掉最新 turn。
4. 更旧的完整 turn：按从新到旧加入；新的放不下就停止，绝不跳着保留更旧的。

A 没有第 3 步；B/C 的第 3 步相同。C 不获得额外额度：`memory_search` 的工具描述和 C-only 调用说明从第 1 步就占 system prompt，这是检索策略的真实成本，不补偿。

### 4.3 硬约束与失败

每次构造 view 时断言：

- 总估算 ≤ 8000；
- 摘要消息 ≤ 1000；
- 每个检索结果 ≤ 1500（单条，不是总和；总和仍受 8000 约束）；
- task 必须在发送内容里；
- history 只能是完整 turn（最新 observation 或 action 的截断除外）。

只有固定前缀（system + task）本身放不下时才抛 `BudgetError`，agent 以 `MemoryBudgetError` 结束；最新 action/observation 超预算会截断并记录 `clipped`，不再作为终止错误。分析把真正的 `MemoryBudgetError` 标为无效 run，而不是当作普通失败。

### 4.4 实测前缀

用 1,500 字符的 task 实测：A/B 的 system+task 约 **1,894** 估算 token；C 因为多一个 937 字符的工具 spec 和一段调用说明，约 **2,200**。即 C 的历史预算比 B 少约 300 token（总预算的 3.7%）。这是 C−B 的保守偏差：C 若仍然更好，结论更强；C 若更差，不能区分“检索没用”和“少了 300 token”。

## 5. 对话表示：turn 是原子

`MemoryAgent` 给自己的消息打 `extra.kind`：`task`、`observation`、`feedback`、`terminal`、`summary`。`conversation.py` 把 task 之后的内容切成：

- `turn`：一个 assistant action + 紧跟的所有 user 消息（正常是一条 observation；格式错误会多一条 feedback）；
- `loose`：没有前置 assistant 的 user 消息（例如预算终止提示）。

保留和丢弃都以 turn 为单位。A 不会出现“observation 还在、对应 action 被删”的孤儿；测试对 A/B/C 都检查这一点。

## 6. 摘要：确定性证据摘要

### 6.1 内容

`summary.py` 只从**被移出的 turns**里抽取：

- 成功读取：step、路径、短摘录（来源可追溯）；
- 修改：step、路径，并让该路径的旧读取失效；
- 非零退出：step、命令/工具、退出码、短摘录；同一操作后来成功则移除；
- 其他成功动作：step、命令/工具、exit 0。

它不读取 task 的 gold patch、官方评分、其他 run 或未来消息。摘要本身不超过 1000 估算 token。

### 6.2 更新方式

摘要是纯函数：`summary = f(所有当前被移出的 turns)`。每次构造 view 时重算，因此：

- 不需要“旧摘要”状态，不会有旧摘要漂移或重复累积；
- B 和 C 对同一组被移出 turns 生成逐字相同的摘要；
- 同一个 transcript 重放会得到同一个摘要。

这等价于一个确定性的增量证据台账，但不是 LLM 摘要。**本版刻意不调用第二次模型**：如果摘要由同一模型生成，B/C 的摘要调用会有各自的随机性和失败路径，C−B 就不再是纯检索效应；同时摘要成本、重试和空响应会污染预算。若研究问题改成“LLM 摘要 vs 规则摘要”，那是另一个预注册实验，不混进本次主对比。

### 6.3 摘要不是

- 不是自然语言“尚未解决的问题”列表；未解决的非零退出是它的代理。
- 不是完整动作日志；只保留有证据价值的读取/修改/失败和少量其他动作。
- 不是跨 run 记忆；没有 session 读取。

## 7. 检索：当前 run 的只读快照

`search.py` 的工具只接收一个 per-agent `SearchContext`：

- 每次模型调用前，agent 把**当前已有的消息**快照进 context；
- 工具只能读这个快照；看不到未来消息、其他 run、saved sessions、官方反馈；
- 支持关键词（所有词都命中）和 regex；`mode=full` 返回消息正文，`index=N` 直接打开当前 transcript 的第 N 条；
- 单次结果在工具边界按 1500 估算 token 截断；`limit` 最大 10；
- 工具 schema 没有 `scope`、没有 `max_chars`、没有 sessions 入口；
- 选择检索就是一次普通模型调用/一步；检索本身不再额外计一步。

## 8. 记账与审计

每次模型调用前，agent 把 view 写入每题的 `memory_trace.jsonl`：

- policy、step、估算总 token、pinned/summary/retrieval token；
- 发送的真实消息下标、被丢消息下标、task 是否存在；
- 摘要是否存在及全文；
- 是否截断最新 observation；max 单条检索 token。

轨迹的每条 assistant 消息还带紧凑的 `extra.memory`；provider 的 `usage.prompt_tokens` 保存在 `extra.response.usage`。分析报告给出：

- 每题 resolved、成本、API 调用数、exit status；
- 丢弃调用数、摘要调用数、检索调用数、检索工具调用数；
- 每题最大估算 token、摘要 token、单条检索 token、预算违规；
- 实际/估算校准（报告从轨迹读取 provider 用量）。

## 9. 统计与预注册

### 9.1 主分析

- 单位：task；结果：官方 resolved / not。
- 主对比：**C−B**。次对比：B−A、C−A。
- 效应量：成功率差；区间：按 task 重采样的 bootstrap 95% percentile CI（10,000 次）；检验：exact McNemar。
- **生效子集**：至少一个 arm 在该题发生过丢弃/截断，或 C 调用过检索；这是 H1/H2 的主要人群。
- **安慰剂子集**：两个 arm 都没有丢弃/截断，且 C 没有调用检索。对 A/B，提示词完全相同，结果必须一致；对涉及 C 的对比，这是**软检查**——C 的 system prompt 仍然带着 memory_search 的工具描述，因此即使不调用检索，输入也不是逐字相同。出现翻转说明 provider 非确定性，单轮结论要打折。
- 同时报告全 50 题和剔除 pilot 10 题的结果；pilot 只用于调试，不作为正式证据。

### 9.2 判据

- 只有 C−B 的 95% CI 不跨 0 且方向为正，才支持“检索有额外收益”；否则写“未观察到”。
- 单轮 CI 不含 run-to-run 方差；同一 baseline 两轮 50 题曾出现 7 个题翻转，因此**正式结论至少需要 2 轮、最好 3 轮**，并且要同时报告每轮和合并结果。合并结果是按 task 对轮次取均值后的描述性 bootstrap，不是把 task-run 当独立样本；每轮的 exact McNemar 仍是主检验。单轮只作方向性证据，不写因果结论。
- 不重复跑到显著；不用重跑替换失败轨迹；不挑检索成功案例。

### 9.3 无效条件

任一条成立则整轮标为 invalid，不进入主表：

- 任一 view 超 8000、摘要超 1000、单条检索超 1500；
- 任一 view 缺 task；
- 出现 `MemoryBudgetError`、`ModelResponseError` 或非预期 exit status；
- 缺 trace、缺轨迹、缺官方评分；
- 三组 manifest 的 controls/source/tasks 不一致。

## 10. 运行协议

1. **pilot 10 题**（A/B/C）：检查是否真的发生丢弃、C 是否调用检索、检索是否返回相关记录、三组是否守住预算。pilot 结果只作调试。
2. 若 8000 导致大量 `MemoryBudgetError` 或异常长循环，先停下来做 8000/12000 的敏感性检查；不要把病态循环解释成 memory 效应。
3. 冻结源码和配置；**正式 50 题 × 3 组 × 至少 2 轮**。每轮用独立 tag（`a_r1` 等），换目录或换 tag，manifest 会拒绝混合。
4. 用官方 harness 逐轮评分；`analysis.py` 生成 `comparison_<round>.json` / `.md`；`--rounds r1,r2` 另写 `comparison_all_rounds.*`。所有题都列出。
5. 报告主表 C−B，附 B−A/C−A、成本、步数、丢弃次数、摘要次数、检索次数、预算审计和 provider 校准。

如果只能跑两组：只跑 B 和 C，主对比仍是 C−B；A 的“整套 memory 方案”对比缺失。命令：

```powershell
python experiments/memory_abc_20261019/desktop.py all --arm b --pilot
python experiments/memory_abc_20261019/desktop.py all --arm c --pilot
python experiments/memory_abc_20261019/desktop.py compare --pilot --arms b,c
```

三组命令：

```bash
# 桌面 Windows
python experiments/memory_abc_20261019/desktop.py all --arm all --pilot --workers 2
# 正式：每轮
python experiments/memory_abc_20261019/desktop.py all --arm all --round r1 --workers 2
# 对比某一轮
python experiments/memory_abc_20261019/desktop.py compare --round r1
# 两轮合并（每轮仍单独写一份 comparison_<round>.md）
python experiments/memory_abc_20261019/desktop.py compare --rounds r1,r2
```

容器内直接运行：

```bash
python experiments/memory_abc_20261019/run.py generation --arm a --pilot
python experiments/memory_abc_20261019/run.py grading --arm a --pilot
python experiments/memory_abc_20261019/run.py compare --pilot
```

## 11. 有效性边界

- 8000 是压力预算，不是模型上下文的上限；结论只适用于“8000 估算 token 下的 SWE-bench 子集”，不能外推成“memory 普遍提升 SWE-bench”。
- 50 题、单模型、单任务集；pilot 10 题从正式统计剔除。
- 摘要是规则化证据摘要，不是 LLM 摘要；检索是关键词/regex，不是 embedding。
- 不做公共前缀 fork：独立运行，A/B 同规则同提示；C 从第 1 步就因为工具描述不同，不能承诺“超限前逐字一致”。这是明确的限制，不用“相同前缀”话术掩盖。
- provider 非确定性存在；安慰剂子集和重复轮次是对策。
- 成本以 DeepSeek 官方单价和 provider 返回为准；不把摘要成本写成非零（本版没有摘要模型调用）。

## 12. 代码地图

```
src/minisweagent/memory/abc/
  budget.py        估算器、PromptView、硬错误、截断工具
  conversation.py  task/turn/loose 解析
  summary.py       确定性证据摘要
  policy.py        window / summary / summary_search
  search.py        当前 run 的检索工具与上下文
  agent.py         MemoryAgent、trace
  stats.py         McNemar、paired bootstrap CI
experiments/memory_abc_20261019/
  configs/         base + a/b/c 单一变量
  run.py           生成、官方评分、对比
  analysis.py      预注册分析与预算审计
  desktop.py       Windows/Linux 容器启动器、源码冻结
  study_config.py  配置加载与唯一变量校验
  tasks.json       50 题；pilot.json 前 10 题
tests/memory/abc/ + tests/run/test_memory_abc_*.py  58 项单元/集成测试
tests/run/        配置与分析的回归测试
```

## 13. 与早期实现的边界

本版不复用旧的 `HistoryManager`：旧实现同时存在消息数和 token 两套策略，`truncate` 按单条消息删，容易产生孤儿 observation，且摘要与检索的预算不是同一个口径。新实现只保留一个 turn 表示、一个估算器、一个硬预算和三个 policy；旧代码保留是为了其他历史实验，不参与本实验。

旧实验的 off 组、旧冻结副本和旧 study 目录都不作为本实验的数据；本实验从新的 manifest 和新的 trace 开始。
