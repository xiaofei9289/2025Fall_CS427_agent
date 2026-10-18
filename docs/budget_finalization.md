# 预算收尾与候选补丁保全

本轮针对 `gate-20261017` 的 `matplotlib__matplotlib-20826`：轨迹在后半程反复查看不同版本的实现，50 次调用后仍没有源码修改。旧流程虽然会在退出时执行 `git diff HEAD`，但工作区没有修改就无法恢复补丁。

## 执行策略

在模型调用前检查硬预算，再检查收尾阈值。任一启用的剩余预算达到阈值时，进入 `finalizing`，只插入一次收尾提示，要求停止扩散搜索、检查当前 diff、依据已有证据完成最小修改、做针对性验证并提交。提示使用现有调用额度，不增加调用次数或费用上限。

服务默认配置：

```yaml
agent:
  step_limit: 50
  cost_limit: 1.0
  time_limit: 300
  finalization_step_reserve: 5
  finalization_time_reserve: 45
  finalization_cost_reserve: 0.10
```

例如已使用 45 次调用时，剩余 5 次调用进入收尾阶段。配置为 0 的收尾阈值关闭对应触发条件；基础 Agent 默认关闭这些提示，服务默认启用。硬限额仍由原来的调用前检查执行。收尾是引导策略，不强制模型修改代码，也不能保证产生正确补丁。

时间阈值在模型调用前检查，模型请求或动作仍可能跨过阈值；服务端独立验收使用自己的 `test_timeout`，不包含在 Agent 的 300 秒内。恢复延续累计调用数和成本，运行时间仍按每次恢复计时。

## 产物与恢复

服务任务在 Agent 退出后进入 `exporting`，先原子保存 `patch.diff`，再进入 `verifying`。即使验收超时，候选补丁仍可下载。取消或错误退出时，最后也会保存当前工作区修改。

任务结果新增：

| 字段 | 含义 |
| --- | --- |
| `budget.phase` | `solving` 或 `finalizing` |
| `budget.limit_reason` | `steps`、`cost`、`seconds`，没有耗尽则为空 |
| `budget.remaining_*` | 剩余额度，未启用对应硬预算时为 null |
| `submission_kind` | `agent` 表示主动提交；`recovered` 表示正常停止后保存的候选修改 |
| `verification_status` | `not_run`、`running`、`passed`、`failed`、`error` 或 `interrupted` |

`succeeded` 继续要求非空补丁与服务配置的测试通过。达到预算上限后保存的候选补丁也会独立测试；通过时保留 `exit_status=LimitsExceeded` 和 `submission_kind=recovered`，避免混同为模型主动提交。测试通过不代表 SWE-bench 官方通过。

checkpoint 保存收尾阶段与预算耗尽原因。恢复已进入收尾的任务时，不重复插入收尾提示。events 中的 `budget`、`candidate` 与 `verification` 可用于查看阶段顺序。

SWE-bench 轨迹保留原始 `agent_exit_status` 和预算信息，即使补丁恢复后最终状态变成 `RecoveredPatch`。预算诊断文字不会作为 `model_patch` 提交；没有源码变化时仍是空补丁。

## 验证范围

台式机回归覆盖收尾触发与硬限额共存、费用和时间阈值、预算耗尽后的真实 Git 补丁恢复及可应用性、空补丁口径、候选补丁在验收前可下载、验收超时后保全，以及恢复后提示去重。Docker 演示另外验证事件、补丁下载与 API 重启。

既有五题实验与源码快照保持原样。新增同工具、同硬预算的五题模型对照已经完成；统一修正补丁末尾换行后的官方验收为关闭组 3/5、开启组 5/5。提示仅在一题触发，且修复在提示前已形成，不能据此推导总体修复率提升。过程与原始导出缺陷见 [实验报告](../experiments/budget_20261017/README.md)。

## 补丁导出缺陷与验收口径

新增模型对照的官方评分发现：旧清洗函数对保留的 diff 执行 `.strip()`，去掉了末尾换行，导致文件末尾新增函数的补丁无法应用。这也可能删除以空格开头的空白上下文行，破坏 unified diff 的行数结构。现已保留 diff 块的原始尾部字符。

回归用例直接将导出字节交给 `git apply --check` 与 `git apply`，验证最终文件内容；覆盖末尾新增代码与末尾空白上下文。原先有一条用例手动补了换行，已移除这一步，避免测试替实现修复产物。

这轮实验保留原始预测和评分；另外在两组全部非空补丁的副本上统一补一个缺失的末尾 LF，单独执行官方验收。副本位于 `experiments/budget_20261017/transport_normalized`，变换记录在 `normalization.json`。该过程不重跑模型、不改补丁正文，不能用来掩盖原始交付错误。后续新生成的补丁由已修复的导出器直接保留结构。
