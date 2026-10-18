# 五题离线定位

查询只使用官方问题原文。应修改的 Python 文件来自官方补丁，不提供给检索。代码副本固定在各题的 base commit。副本被 gitignore 忽略，换机器时先重建：

```bash
python experiments/localization_verified5/prepare_checkouts.py
# 只校验已有副本并重写 manifest
python experiments/localization_verified5/prepare_checkouts.py --verify-only
```

评分命令：

```bash
python -m minisweagent.run.extra.localization_eval \
  --cases experiments/localization_verified5/cases.json \
  --output experiments/localization_verified5/result.json --k 5
```

如果本机只有 50 题目录下的同 commit 副本，可用 `--checkouts-root` 复用它们：

```bash
python -m minisweagent.run.extra.localization_eval \
  --cases experiments/localization_verified5/cases.json \
  --checkouts-root experiments/localization_verified50/checkouts \
  --output experiments/localization_verified5/brief_result.json --k 5
```

`prepare_checkouts.py` 读取 `cases.json` 的 `repo_url`/`base_commit`，逐题 clone、checkout，并写
`checkouts/checkouts_manifest.json`（含 cases 哈希、HEAD、Python 文件数）。它不会把源码提交进仓库。

| 方法 | Recall@5 | Hit@5 | MRR |
| --- | ---: | ---: | ---: |
| 文件级 BM25 | 0.54 | 0.80 | 0.50 |
| 符号级 BM25 | 0.34 | 0.60 | 0.63 |
| 上下文选择（`context_files`） | 0.54 | 0.80 | 0.64 |
| 确定性 `repo_brief` | **0.88** | **1.00** | **0.90** |

`brief` 行由同一 base commit 的副本测得（本机用
`experiments/localization_verified50/checkouts` 作为 `--checkouts-root`），结果在
[`brief_result.json`](brief_result.json)。它只使用 issue 中的路径/堆栈/符号线索和 AST 索引，
不读取 gold patch；`repo_brief` 把路径和 traceback 里的绝对路径按最长后缀匹配到当前 checkout，
因此 11532 能定位到 `django/core/mail/message.py` 和 `django/core/mail/utils.py`，Matplotlib 的
`axis.py` 也进入前五。五题样本仍然很小，这只说明离线候选排序有提升，不能直接外推到在线解决率。
50 题复核里 `repo_brief` 的 Recall@5 回落到 0.645，低于上下文选择的 0.691，说明五题上的
0.88 有过拟合成分；见 [`../localization_verified50/README.md`](../localization_verified50/README.md)。

符号级和上下文方法使用同一份 AST 索引；符号检索已排除 `<module>` 伪符号，修掉了此前文件级文档混入符号排名的问题，因此符号 MRR 从 0.61 变为 0.63。上下文选择在文件级和符号级候选之间做 reciprocal-rank fusion，并优先产品代码、最多保留一个测试/文档文件；它的召回与文件级持平，MRR 更高，但仍受 5 题样本限制。

Hit@5 表示前五名里至少有一个官方文件。`django__django-11532` 的官方补丁有 5 个文件，前五名只包含 `django/core/mail/message.py`，所以召回率是 0.20。

| 题目 | 文件级前五名是否含官方文件 | 强制查找后的在线结果 |
| --- | --- | --- |
| django__django-15315 | 含，排第 2 | 两组都通过 |
| django__django-11333 | 含 `resolvers.py`，不含 `base.py` | 两组都通过 |
| django__django-14855 | 含 | 两组都通过 |
| django__django-11532 | 含主文件，其余四个官方文件不在前五 | 两组都未通过 |
| matplotlib__matplotlib-20826 | 不含；`lib/matplotlib/axis.py` 排第 54 | baseline 通过，retrieval 空补丁 |

Matplotlib 的问题原文写的是 `ax.clear()`、共享坐标轴和动画。用原文做 BM25 时前五名主要是教程、`pyplot.py` 和 `animation.py`；去掉教程、示例和测试后，官方文件仍排第 33。

但**不能把离线第 54 直接解释成在线空补丁的原因**。`gate-20261017` 的 retrieval 轨迹里，模型把查询改写成 `clear axes ticks tick labels shared axis visibility` 后，`lib/matplotlib/axis.py` 在首轮 `code_search` 中排第 3；轨迹也读取了 `_base.py`/`axis.py`，只是没有形成编辑。归因审计见
[`experiments/gate-20261017/retrieval_audit.md`](../gate-20261017/retrieval_audit.md)：5/5 题的官方文件进入首轮 top-10，5/5 读取，4/5 编辑，但只有 3/5 解决。因此这题更像是检索后的收敛失败，而不是“关键词没有指向官方文件”。

四道至少命中一个官方文件的 Django 题里，三道两组都通过。没有命中全部官方文件的邮件题两组都失败。这次结果不支持继续加向量检索；上下文选择把 MRR 从 0.50 提到 0.64，但 Recall@5 没有提高，且五题样本不足以说明在线解决率提升。
