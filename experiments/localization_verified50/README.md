# 50 题离线定位

这套用例把 `experiments/configs/verified50_tasks.json` 的 50 个任务转成离线定位评测。
查询只使用 SWE-bench 的官方 `problem_statement`；应修改的 Python 文件从官方 `patch`
的 `diff --git` 行提取，不进入查询。每个代码副本固定在任务的 `base_commit`。

## 生成与获取

`cases.json` 由缓存的 `SWE-bench/SWE-bench_Verified` 数据生成，已放入本目录。
代码副本不入库，复用五题目录的冻结抓取脚本，需要联网获取：

```bash
python experiments/localization_verified5/prepare_checkouts.py \
  --cases experiments/localization_verified50/cases.json \
  --output experiments/localization_verified50/checkouts
```

脚本按 `repo_url + base_commit` 抓取，已存在且 HEAD 匹配的副本会跳过，并写出
`checkouts/checkouts_manifest.json`。只检查现有副本时加 `--verify-only`。

## 评测

```bash
MINISWEAGENT_INDEX_CACHE=0 python -m minisweagent.run.extra.localization_eval \
  --cases experiments/localization_verified50/cases.json \
  --checkouts-root experiments/localization_verified50/checkouts \
  --output experiments/localization_verified50/result.json --k 5
```

关闭索引缓存是为了让一次性评测不把 50 份索引写进 `/tmp`；交互式 Agent 工具默认开启缓存。
评测器只保留当前仓库的一个完整索引，避免 50 个仓库同时驻留内存。指标为 Recall@5、Hit@5、MRR，
方法包括文件级 BM25、符号级 BM25、上下文选择和 `repo_brief`。

## 结果

| 方法 | Recall@5 | Hit@5 | MRR |
| --- | ---: | ---: | ---: |
| 文件级 BM25 | 0.534 | 0.60 | 0.467 |
| 符号级 BM25 | 0.531 | 0.60 | 0.437 |
| 上下文选择（`context_files`） | **0.691** | **0.76** | **0.560** |
| 确定性 `repo_brief` | 0.645 | 0.68 | 0.488 |

50 题覆盖 9 个仓库，其中 Django 24 题；`index_stats` 记录了 50 个独立的 base-commit 副本。
与文件级 BM25 相比，上下文选择在 11 道题上提高了命中，只在 `matplotlib__matplotlib-23299`
上丢了一次命中；召回从 0.534 提高到 0.691。

五题上 `repo_brief` 的 Recall@5 是 0.88，但 50 题只有 0.645，低于上下文选择的 0.691。主要原因
是 brief 会优先相信 issue 中显式出现的路径/符号；这些提示在部分题上指向错误文件，挤掉了 BM25
候选。五题结果因此不能外推到 50 题，`repo_brief` 也不应被描述为普遍优于纯 BM25 的方案。

这些仍是离线文件定位指标，不是 SWE-bench 解决率。它们说明“文件/符号混合检索 + 片段上下文”
比单一文件级 BM25 更适合作为候选生成器，但不能证明在线 Agent 会因此多解决题目。
