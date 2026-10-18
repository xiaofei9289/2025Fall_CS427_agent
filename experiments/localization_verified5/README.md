# 五题离线定位

查询只使用官方问题原文。应修改的 Python 文件来自官方补丁，不提供给检索。代码副本固定在各题的 base commit。评分命令：

```bash
python -m minisweagent.run.extra.localization_eval \
  --cases experiments/localization_verified5/cases.json \
  --output experiments/localization_verified5/result.json --k 5
```

| 方法 | Recall@5 | Hit@5 | MRR |
| --- | ---: | ---: | ---: |
| 文件级 BM25 | 0.54 | 0.80 | 0.50 |
| 符号级 BM25 | 0.34 | 0.60 | 0.61 |

Hit@5 表示前五名里至少有一个官方文件。`django__django-11532` 的官方补丁有 5 个文件，前五名只包含 `django/core/mail/message.py`，所以召回率是 0.20。

| 题目 | 文件级前五名是否含官方文件 | 强制查找后的在线结果 |
| --- | --- | --- |
| django__django-15315 | 含，排第 2 | 两组都通过 |
| django__django-11333 | 含 `resolvers.py`，不含 `base.py` | 两组都通过 |
| django__django-14855 | 含 | 两组都通过 |
| django__django-11532 | 含主文件，其余四个官方文件不在前五 | 两组都未通过 |
| matplotlib__matplotlib-20826 | 不含；`lib/matplotlib/axis.py` 排第 54 | baseline 通过，retrieval 空补丁 |

Matplotlib 的问题原文写的是 `ax.clear()`、共享坐标轴和动画。前五名主要是教程、`pyplot.py` 和 `animation.py`。去掉教程、示例和测试后，官方文件仍排第 33。因此这题的空补丁对应的是关键词没有指向官方文件，不是“已经找到文件但预算不够”。

四道至少命中一个官方文件的 Django 题里，三道两组都通过。没有命中全部官方文件的邮件题两组都失败。这次结果不支持继续加向量检索，也不支持立刻重跑模型。
