# 三个 TokenFy 单渠道模型的五题流程验证

目的:验证三个互为单渠道的 key(`claude-opus-5`、`gpt-5.6-sol`、`gemini-3.8-flash`)能跑通
SWE-bench 生成与官方评分流程。三组不构成模型能力对照。

方法与 `pilot_20261017` 一致:同一五题(`tasks.json`)、每题 50 步、1 美元、300 秒、
单 worker,仅模型不同。`model_class: litellm`、`api_base: https://TokenFy.net/v1`;成本按网关
公开计价表达式换算的 `tokenfy_model_registry.json` 统计;模型调用超时由 DeepSeek 用的 45 秒
放宽到与仓库基线一致的 120 秒。密钥经 `TOKENFY_KEY_<ARM>` 环境变量注入,不写入配置、仓库或命令行。
全局成本上限 10 美元(起初误用 budget 实验的 5 美元,首轮因此截断,已重跑)。配置副本与
冒烟脚本在 `experiments/configs/tokenfy_*.yaml`、`experiments/configs/smoke_tokenfy.py`。

官方评分对 `preds.empty_on_errors.json` 执行:导出器把 API 异常文本记为 `model_patch` 是有测试
断言的既有行为,评分前将非 `diff --git` 开头的占位文本置空,原始 `preds.json` 原样保留;
与 `budget_20261017` 的 LF 修正同属"仅消除非补丁内容"的规范化。

| 官方结果 | claude_opus_5 | gpt_5_6_sol | gemini_3_8_flash |
| --- | ---: | ---: | ---: |
| 完成评分 | 2/5 | 1/5 | 0/5 |
| 通过 | 1(django-15315) | 1(django-11333) | 0 |
| 未通过 | 1(django-11333) | 0 | 0 |
| 空补丁 | 3 | 4 | 5 |
| harness 错误 | 0 | 0 | 0 |
| 模型花费(约) | $7.9 | $0.6 | $0.01 |

限制:三个 key 余额在运行中途耗尽(claude 剩 $0.18、gpt 剩 $0.004、gemini 剩 $0.003),
全部 `APIError` 均为网关"预扣费额度失败";gemini 组首题即余额不足,五题为零提交。
gpt-5.6-sol 在 django-15315 上两次调用即空提交,行为需复跑核查;claude 两个完成题均撞 $1
单题预算退出(RecoveredPatch),高价模型做整组对照前需另行设计预算。一次运行、部分题目
缺失,不能据此比较模型能力。当前状态:生成与官方评分已完成、零 harness 错误;
待三个 key 充值后删除 APIError 任务重跑修订上表。

台式机 Linux 容器内运行(`experiments/configs` 下同名配置亦可用作五十题扩量入口):

```bash
python experiments/pilot_tokenfy_20261018/run.py generation   # 全部三个 arm
python experiments/pilot_tokenfy_20261018/run.py grading --arms claude_opus_5
```

`--arms` 指定子集;生成/评分日志、执行记录(退出码与耗时)分别写入本目录与各 `arm/evaluation`。