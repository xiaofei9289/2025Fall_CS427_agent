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

## 检索归因（2026-10-18 补算）

用 `minisweagent.run.extra.retrieval_audit` 逐条解析五条 retrieval 轨迹，结果在
[retrieval_audit.md](retrieval_audit.md)。它把“检索没找到”“找到了但没读”“读了但没改”
“改了但没通过”分开：

| 指标 | 结果 |
| --- | ---: |
| 官方文件进入首轮检索 top-10 | 5/5 |
| 检索后读取官方文件 | 5/5 |
| 编辑官方文件 | 4/5 |
| 最终解决 | 3/5 |

- 五题的首轮 `code_search` 查询由模型自己改写，均把至少一个官方文件拉进 top-10；
  Matplotlib 的 `lib/matplotlib/axis.py` 排第 3。
- `matplotlib-20826` 的模型读了 `_base.py`/`axis.py` 的相关代码，却没有形成编辑，反而转向
  下载 3.4.3–3.6 做版本考古，50 步耗尽。这不是“检索未命中”，而是检索后的收敛失败。
- `django-11532` 读取并编辑了 `django/core/mail/message.py`，失败来自 18 个原有邮件测试在
  SMTP `EHLO` 上报错。这是定位成功、下游验证失败。
- 因此这组数据的瓶颈已经从“找得到”转向“找到后怎么用”；增加检索召回不是下一步的最高
  优先级。
- 同一脚本跑 baseline 五条轨迹：分类全部是 `no_search`，但读取/编辑官方文件均为 5/5，
  最终 4/5 解决。这说明这组题里多数任务不检索也能做对，进一步限制了对 retrieval 的归因。

另：这组 treatment 同时改变了工具、提示词和“强制首步” gate，不能把差异单独归因于检索
质量。复现旧行为使用 `experiments/configs/retrieval_gate.yaml`；新策略使用 brief，不再强制
首步检索。
