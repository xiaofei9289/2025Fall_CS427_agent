# 测试驱动的修复工作流（MVP）

这个模块把“先复现、再修改、再验证、最后提交”从提示词建议变成可执行、可恢复、可审计的提交门。核心不是新增一个阶段枚举，而是三件事：

1. 分类测试结果，区分代码失败、无测试、collection/import 错误、超时和环境错误；
2. 把测试证据绑定到当前工作区的 diff fingerprint；
3. 在提交路径上做确定性检查，模型不能自己宣布“已验证”。

## 启用

批量 SWE-bench 入口新增两个参数：

```bash
python -m minisweagent.run.extra.swebench \
  --subset verified-50 --instance-ids experiments/configs/verified50_tasks.json \
  --slice 0:5 --workers 1 --config experiments/configs/baseline.yaml \
  --workflow --workflow-mode advisory \
  --output runs/pilot-repair
```

- `--workflow` 打开工作流；不打开时 `ProgressTrackingAgent` 的行为与之前一致，也不注册 `run_tests`。
- `advisory`：记录未验证提交，但不阻塞；适合官方测试不可见的 SWE-bench。
- `strict`：在 `max_verify_attempts` 次内阻塞未验证提交；达到上限后仍允许提交并记录 `unverified`，避免因测试环境问题丢失补丁。

配置也可以直接写在 YAML 的 `agent` 段：

```yaml
agent:
  workflow_enabled: true
  workflow_mode: strict
  acceptance_command: ""      # 可选；服务端式验收命令，例如 python -m pytest -q
  test_timeout: 120
  max_test_runs: 6
  max_verify_attempts: 2
  artifact_dir: ""            # SWE-bench runner 会自动设为该题的输出目录
```

## 工具

`run_tests` 是工作流安装的本地工具（不进入全局注册表）。如果配置了 `enabled_tools`，不需要把 `run_tests` 写进去；工作流会自动安装它。即使写了，`RepairAgent` 也会在创建工具集时移除这个名字，再由工作流补上，避免 `DefaultAgent` 把它当成未知工具。

```json
{"name": "run_tests", "args": {"command": "python -m pytest -q tests/test_config.py", "timeout": 120}}
```

它返回 `status`、`counts`、失败 test ID、`diff fingerprint`、耗时和输出尾部。`status` 取值：

| status | 含义 |
| --- | --- |
| `passed` | 至少运行了一个测试且没有失败/错误 |
| `test_failed` | 有断言失败或测试 error |
| `collection_error` | import/collection 阶段失败 |
| `no_tests` | 没有测试运行 |
| `timeout` | 超过测试超时 |
| `infra_error` | 命令/容器/权限/内存/磁盘等环境错误 |
| `interrupted` | 被中断 |
| `unknown` | 非零退出但无法解析 |

执行前会删除仓库内的 `*.pyc` 并设置 `PYTHONDONTWRITEBYTECODE=1`。这是必要的：同大小、同一秒内的源码修改可能让 CPython 继续使用旧字节码，验证会测到旧代码。容器内还会优先用 `timeout -k` 包住命令，避免只杀掉 `docker exec` 客户端而留下容器内进程。`time_limit` 启用时，`run_tests` 的 timeout 会被限制在剩余预算内；剩余不足 3 秒时直接拒绝运行，避免测试吃掉收尾预算。

## 验证语义

`local_verification` 只有在以下条件同时满足时才是 `verified`：

- 第一次测试与任务开始时的工作区指纹一致（baseline fingerprint == pristine）；
- baseline 是 `test_failed`，不是超时、环境错误、collection error 或 no_tests；
- 验证命令与 baseline 相同；
- 验证时的 diff fingerprint 与当前工作区一致，且测试运行期间工作区没有变化；
- 测试文件没有被修改；
- 没有新增失败；
- 验证 run 是 `passed`，且运行的测试数不少于 baseline；
- 验证 run 的跳过数不高于 baseline，通过数至少覆盖 baseline 的 `passed + failed`；
- baseline 至少有一个可识别的失败 test ID。

其他情况分别返回 `inconclusive`、`stale`、`unverified` 或 `regression`。`verified` 只表示**本地验证**，不是 SWE-bench 官方解决；不要把它写成 `issue_resolved`。

## 产物

启用工作流且 `artifact_dir` 可用时，每题输出目录会多出：

| 文件 | 内容 |
| --- | --- |
| `verification.jsonl` | 每次测试的 run 记录、diff 摘要、阶段和本地验证状态 |
| `repair_state.json` | baseline、最近一次测试、phase、验证状态、新增失败 |
| `repair_diff.patch` | 经过 junk/测试脚本过滤后的候选补丁 |
| `repair_diff.json` | 文件列表、是否改测试、是否空补丁、最终决策 |
| `run_summary.json` | 退出状态、最终 gate 状态、本地验证和 state |

产物目录必须在仓库之外（SWE-bench runner 默认放在 `output/<instance_id>/`）。如果放在仓库内，它会被算进 diff，baseline 会被判为“不干净”。

## 提交门

模型尝试提交时：

1. 计算工作区 diff（`git add -N` 包含 untracked 文件）；
2. 空补丁在 `max_verify_attempts` 次内阻塞；
3. 如果配置了 `acceptance_command` 且上次测试不是当前 diff，自动运行验收命令；
4. 调用 `local_verification`；
5. 未通过时，`strict` 在次数上限内抛出 `SubmissionBlocked`，把原因作为下一条 observation 让模型继续修；
6. 允许提交时，用**经过验证的规范化 diff** 替换提交内容，避免 `git diff HEAD` 漏掉 untracked 新文件，也避免提交 repro 脚本。

`run_tests` 本身不决定 phase；它只产生证据。phase 由测试记录和提交决策推导，模型不能自报 `verified`。

## 已知边界

- SWE-bench 的 `FAIL_TO_PASS` 不可见；本地只能做 issue 驱动的复现和定向测试，不能保证覆盖官方测试。不要把 `instance["FAIL_TO_PASS"]` 传给 agent。
- `acceptance_command` 为空时，`local_verification` 依赖模型主动使用 `run_tests`；`strict` 会推动它，但不能强迫模型选择正确的测试。
- 当前接入的是 SWE-bench 批量入口；服务端 `TaskAgent` 仍使用原来的退出码验收，后续可以把 `parse_test_output` 和 `TestRun` 接到 `service/worker.py`，将 collection error/no tests 映射为 `error` 而不是 `failed`。
- 测试日志在返回给模型时按 `max_output` 截断；完整输出目前不额外落盘。需要完整日志时可在容器内重定向到文件或扩展 artifact writer。
- 没有运行模型 API；本 MVP 的验证是离线单测和确定性 agent 测试。正式结论仍需 5 题 pilot 和 50 题多轮对照。

## 实验建议

按 [experiments/PLAN.md](../experiments/PLAN.md) 的冻结流程开新目录。`write_manifest` 会在配置或源码变化时拒绝复用旧目录；不要覆盖 `deepseek_scale50_20261018` 等已归档结果。

- 先 5 题 pilot，确认 gate 能触发、空补丁不丢、超时不误判；
- 再 50 题，至少 2 轮；同配置历史 50 题在 37/40/42 之间波动，单轮 ±2 不能作为结论；
- 指标：官方 resolved、空补丁、调用数、成本、wall time、每题 test run 数、验证覆盖率、`false_verified`（本地 verified 但官方未解决）；
- 把 `local_verification` 当预测、`official_resolution` 当标签，报告 TP/FP/FN/TN。最有价值的坏案例是“本地 verified、官方 failed”。
