# 只切换历史压缩的五题对照

两组都使用 TokenFY 上的 `gemini-2.5-flash`、相同工具、50 步和 1 美元上限，并且都没有 `memory_search`。开启组在超过 12 条消息后压缩旧历史，摘要保留被省略的读取输出和失败结果。

| 结果 | 关闭记忆 | 开启记忆 |
| --- | ---: | ---: |
| 通过 | 4 | 0 |
| 空补丁 | 0 | 3 |
| 评分错误 | 1 | 2 |

关闭记忆通过 `django__django-11333`、`django__django-11532`、`django__django-14855`、`matplotlib__matplotlib-20826`。`django__django-15315` 评分错误。开启记忆没有通过任何题。`django__django-11333`、`django__django-14855` 和 Matplotlib 是空补丁，邮件题和 `django__django-15315` 是评分错误。

开启组每题都在第 7 次调用前开始发送记忆摘要。没有题目是只有开启记忆才通过的。
