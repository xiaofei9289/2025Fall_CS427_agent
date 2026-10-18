# 台式机验收记录

执行主机：`PC-20230218RALO`（`192.168.1.11`），Windows 10 上的 Docker Desktop Linux 引擎。工作目录：`D:\cs427-upgrade-20261017`。所有本轮测试、镜像构建和正式评分均在该台式机进行。

| 检查 | 最终结果 | 证据 |
| --- | --- | --- |
| 回归测试 | 239 passed，9 deselected，24.91 秒 | [pytest.log](pytest.log)、[执行记录](pytest.json) |
| 静态检查 | All checks passed | [ruff.log](ruff.log)、[执行记录](ruff.json) |
| HTTP → Docker → pytest → 补丁下载 | succeeded，2 次确定性模型调用，非空补丁 | [demo/result.json](demo/result.json) |
| API 容器重启 | 任务仍为 succeeded，调用数仍为 2 | [demo/restarted_task.json](demo/restarted_task.json) |
| 首轮五题官方评分 | baseline 3/5，retrieval 4/5，零 harness 错误 | [实验说明](../experiments/pilot_20261017/README.md) |
| 强制检索五题评分 | baseline 4/5，retrieval 3/5，含 1 个空补丁，零 harness 错误 | [实验说明](../experiments/gate-20261017/README.md) |
| 收尾五题对照 | 统一修正末尾换行后：关闭组 3/5，开启组 5/5，零 harness 错误 | [原始与修正版结果](../experiments/budget_20261017/README.md) |

回归覆盖工具、记忆、服务、任务取消与恢复、预算、实验清单、审计、对比和 Agent 执行。9 项带 slow 标记的测试未运行。服务演示使用确定性模型，验证工程链路；模型能力以各实验的官方评分记录为准。

预算深化新增收尾提示与剩余额度记录、候选补丁在验收前保存、验收超时后保全，以及恢复后提示去重。Docker 演示的独立 fixture 将 `finalization_step_reserve` 设为 50，以两次确定性调用验证收尾事件；服务实际默认值仍为 5。演示事件顺序为 `budget → model/action → candidate → verification → succeeded`，重启后仍保留结果。详情见 [预算收尾说明](../docs/budget_finalization.md)。

新增“关闭收尾／开启收尾”的同工具、同硬预算五题对照已完成。原始关闭组为 3 题通过、1 题未通过、1 题补丁应用错误；开启组为 5/5。统一补齐末尾换行后另行完整验收，关闭组 3/5、开启组 5/5，参见 [实验目录](../experiments/budget_20261017/README.md)。模型生成估算费用合计 0.04391898 美元；格式修正与评分没有新增模型调用。原始结果完整保留，服务镜像已更新。

官方评分暴露了旧导出器 `.strip()` 丢失补丁末尾字符的问题，已修复，并用导出字节直接执行 Git 应用回归。收尾提示只在一题触发，不能将整组分差归因于提示。

本轮修复了空补丁解决率口径，以及强制首步检索影响服务提交动作的问题。失败回归日志保留为 `before-service-gate-fix-pytest.log`；最终通过记录为 `pytest.log`。跨系统打包生成的 AppleDouble 元数据已清理，后续打包需使用 `COPYFILE_DISABLE=1 tar ...`。

重新运行方式见 [部署说明](../deployment/README.md)。三轮五题结果各自保留，不能混算为总体提升结论。
