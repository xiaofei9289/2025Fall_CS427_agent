# 记忆修复验证（2026-10-18）

修复已写入本地项目。验证主机为台式机 `PC-20230218RALO`，代码和测试放在独立目录
`D:\cs427-upgrade-20261017\desktop_validation\memory-fix-20261018`，未覆盖既有实验产物。

## 修复内容

- 历史压缩保留任务和连续的完整动作/观察轮次，摘要占用同一消息预算；未达到阈值时保持原始上下文。
- 摘要只把成功执行的读取工具记为读取，标注来源步骤与读取范围；同一操作成功后清除旧失败，已修改文件的旧读取标为可能过期。
- 空正文、截断、过滤响应与动作格式错误分开处理。过滤响应立即结束，连续空正文/截断默认三次结束；调用和费用仍累计，空 assistant 回复保留在轨迹但不再次发送给模型。
- 因模型响应错误提前结束时，SWE-bench 导出器仍恢复已形成的源码补丁，诊断文字不会成为提交补丁。

## 台式机纯 Python 回归

结果：**70 passed**，退出码 0，pytest 耗时 5.83 秒。模型接口和执行环境使用 mock，不调用付费模型。

覆盖文件：

- `tests/memory/test_history.py`
- `tests/memory/test_integration.py`（mock 环境）
- `tests/memory/test_session.py`
- `tests/memory/test_search.py`
- `tests/models/test_litellm_model.py`
- `tests/agents/test_model_responses.py`
- `tests/tools/test_memory_search.py`
- `tests/agents/test_finalization.py::test_model_response_error_recovers_patch_without_exporting_diagnostic`

台式机原始验证记录保存在独立目录中的 `native-targeted.log` 和 `native-targeted.json`。

## 故障轨迹离线重放

在台式机原地读取 `memory_credit_20261017/on` 的原始轨迹，用该实验的 `source.zip` 中旧压缩器
与本次修复后的压缩器逐调用比较。只输出诊断计数，不导出原始轨迹。

| 任务 | 原始调用数 | 旧版丢弃最近动作的调用数 | 修复后 | 修复后动作/观察拆散次数 | 修复后最大发送消息数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| django__django-11333 | 50 | 37 | 0 | 0 | 12 |
| django__django-11532 | 50 | 35 | 0 | 0 | 12 |

诊断记录位于台式机独立目录中的 `replay.json`。这是对原有轨迹的上下文保留验证，不是模型续跑，不能解释成新增通过题目。

## 尚未完成的验证

Linux 集成测试未启动成功：Docker Desktop 的 WSL 引擎在挂接既有数据盘时失败，报告
`disk not found: no sd* disk ...`。已启动现有后台服务并尝试重启一次 Desktop；未重置、删除或重建数据盘。
Docker 命令及失败记录保存在台式机独立目录的 `targeted.log` 和 `targeted.json`。

未重跑 SWE-bench 生成或官方评分。原五题关闭记忆 4/5、开启记忆 2/5 的结果保持不变；修复后的性能收益需要另开目录做受控对照。
