# 强制调用查找后的五题重跑

这组使用和 `pilot_20261017` 相同的五题、模型、步数、成本和时间上限。代码比上一次多了一条限制：retrieval 组的第一个动作必须是 `code_search` 或 `repo_map`。生成和官方评分都在台式机完成。对照表是 [comparison.md](comparison.md)。

先用 `django__django-15315` 做了一题检查。模型第一次使用 bash 被拒绝，随后 `code_search` 把 `Field.__hash__` 排在第一位。

| 官方结果 | Baseline | Retrieval |
| --- | ---: | ---: |
| 完成评分 | 5/5 | 4/5，另有 1 个空补丁 |
| 通过 | 4 | 3 |
| 未通过 | 1 | 1 |
| 空补丁 | 0 | 1 |
| harness 错误 | 0 | 0 |
| 固定五题解决率 | 80% | 60% |
| `code_search` 调用 | 0 | 5 |

| 题目 | Baseline | Retrieval |
| --- | --- | --- |
| django__django-11333 | 通过 | 通过 |
| django__django-11532 | 未通过 | 未通过 |
| django__django-14855 | 通过 | 通过 |
| django__django-15315 | 通过 | 通过 |
| matplotlib__matplotlib-20826 | 通过 | 空补丁 |

`matplotlib__matplotlib-20826` 的 retrieval 轨迹调用了 `code_search`，然后在 50 步上限停止，没有提交补丁。评分已经结束，harness 错误为 0。空补丁计入未解决任务，因此 retrieval 的固定五题解决率为 3/5（60%）；实际执行官方测试的补丁为 4 个。对比脚本已修正原先把空补丁标为“待完成”的口径，基础设施错误或缺失评分仍不生成完整解决率。

五条 retrieval 轨迹都调用了查找。baseline 4 题通过，retrieval 3 题通过。这仍是一次五题运行，不能说明查找提高或降低了修复能力。上一次“工具开了但没人用”的 3/5 对 4/5 保留在 `experiments/pilot_20261017`，不和这次混算。
