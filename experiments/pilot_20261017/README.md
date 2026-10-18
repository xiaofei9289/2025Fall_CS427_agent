# 五题 baseline / retrieval 对照试验

两组使用相同的 5 题、DeepSeek 配置、提示模板、50 步、1 美元和 300 秒上限，记忆关闭。retrieval 组只多了 `code_search` / `repo_map`。源码快照在各组 `source.zip`，配置在 `run_manifest.json`。台式机官方评分日志在各组 `evaluation/`，对照表在 [comparison.md](comparison.md)。

| 官方结果 | Baseline | Retrieval |
| --- | ---: | ---: |
| 完成评分 | 5/5 | 5/5 |
| 通过 | 3 | 4 |
| 未通过 | 2 | 1 |
| 空补丁 | 0 | 0 |
| harness 错误 | 0 | 0 |
| 模型调用数 | 106 | 102 |
| 估算成本（USD） | 0.032356 | 0.019901 |
| token | 1630024 | 1206039 |

| 题目 | Baseline | Retrieval |
| --- | --- | --- |
| django__django-11333 | 通过 | 通过 |
| django__django-11532 | 未通过 | 未通过 |
| django__django-14855 | 通过 | 通过 |
| django__django-15315 | 通过 | 通过 |
| matplotlib__matplotlib-20826 | 未通过 | 通过 |

完整性问题为空。两组控制项除启用工具外一致。源码指纹 `bf51636987b788fc9d1408fe1cf21de77fc6974995f81cd0e8e434ca12640b23`，对应提交 `3306f13281cd74938f96315106a17165b9ce5dac`，生成时工作区是脏的。成本来自运行记录，未与供应商账单核对。两组顺序运行，供应商缓存也可能影响成本。

retrieval 轨迹里的工具调用只有 `refined_read_file` 3 次和 `replace` 6 次，没有 `code_search` 或 `repo_map`。因此 4/5 与 3/5 的差别不能归因于定位工具。这是一次小样本流程验证，不能外推到 50 题或宣称总体提升。

先前 Mac 上的验收错误仍留在各组 `local_evaluation_attempt`，不计入上表。

## 失败案例：django__django-11532

两组都提交了 `django/core/mail/message.py` 里一行改动，把 `Message-ID` 的域名改成 IDNA 后再交给 `make_msgid`。补丁都能应用。官方目标测试 `test_non_ascii_dns_non_unicode_email` 通过，同时 18 个原有邮件测试报错。报错发生在 SMTP `EHLO`：主机名含非 ASCII 字符，`smtplib` 用 ASCII 编码失败。两组补丁和失败集合相同，所以这题没有组间差异。

## 唯一分差：matplotlib__matplotlib-20826

Baseline 把坐标轴刻度初始化挪到后面，并给 `SubplotBase` 增加 `cla`。目标测试通过，但 `test_markevery_polar` 的 png/pdf 和 `test_tickdirs` 失败。Retrieval 只改了 `lib/matplotlib/axis.py` 里主次网格的 `gridOn` 标志，官方测试全部通过。这条轨迹同样没有调用 `code_search` 或 `repo_map`。
