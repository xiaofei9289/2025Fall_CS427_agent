# 三个 TokenFy 单渠道模型的五题流程验证

目的:验证三个互为单渠道的 key(`claude-opus-5`、`gpt-5.6-sol`、`gemini-3.8-flash`)能跑通
SWE-bench 生成与官方评分流程。三组渠道资源与预算约束不同,不构成受控模型对照。

方法与 `pilot_20261017` 一致:同一五题(`tasks.json`)、每题 50 步、1 美元、300 秒、
单 worker,仅模型不同:`model_class: litellm`、`api_base: https://TokenFy.net/v1`;成本按网关
公开计价表达式换算的 `tokenfy_model_registry.json` 统计;模型调用超时由 DeepSeek 用的 45 秒
放宽到与仓库基线一致的 120 秒;全局成本上限 10 美元。密钥经 `TOKENFY_KEY_<ARM>` 环境变量注入,
不写入配置、仓库或命令行。配置副本与冒烟脚本在 `experiments/configs/tokenfy_*.yaml`、
`experiments/configs/smoke_tokenfy.py`。

首轮(2026-10-18 上午,无后缀目录)因三个 key 余额中途耗尽而部分失败:claude 2/5、gpt 1/5、
gemini 0/5,全部 `APIError` 为网关预扣费失败。产物按原样保留作为证据。充值后以 `--tag _r2`
完整重跑,以下为最终结果。

| 官方结果(\_r2 完整运行) | claude_opus_5 | gpt_5_6_sol | gemini_3_8_flash |
| --- | ---: | ---: | ---: |
| 完成评分 | 5/5 | 5/5 | 5/5 |
| 通过 | 1(django-14855) | 4(11333、14855、15315、matplotlib-20826) | 1(django-11333) |
| 未通过 | 2(11333、11532) | 1(11532) | 0 |
| 空补丁 | 2(15315、20826) | 0 | 4 |
| harness 错误 | 0 | 0 | 0 |
| 模型调用数 | 62 | 80 | 176 |
| 生成耗时 | 374 秒 | 709 秒 | 1197 秒 |
| 估算花费 | $5.28 | $2.03 | $3.26 |

参考:同题集上 DeepSeek 基线 3/5、retrieval 4/5(`pilot_20261017`)。

观察:

- `claude-opus-5` 五题全部撞满预算收尾(单题 $1.00–1.08、11–15 次调用),其中两题在预算
  耗尽时工作区无已跟踪改动,导出为空补丁;$1/题的硬预算对高价模型过紧,整组对照前需重设。
- `gpt-5.6-sol` 五题全部正常提交(单题 $0.23–0.60),官方通过 4/5;仅 django-11532(邮件
  IDNA)未通过,该题 DeepSeek 两轮亦未通过。
- `gemini-3.8-flash` 仅 django-11333 产出补丁并通过;其余四题思考 token 消耗大量步数、
  时间与预算(20–50 次调用)而未留下改动;django-15315 两次调用即空提交,同款行为在
  gpt 首轮 15315 复现。排查确认失败链:第一响应一次性写出 10~35 个动作的模拟轨迹
  (含修复动作,均未执行),触发格式错误后模型误称"修复已完成"并立即提交;当时
  仓库的格式错误反馈硬编码 `actions=[]`,实际检出 12/35 个动作却始终提示
  "found 0 actions",已在 `default.py` 修正为传入真实动作列表并补回归测试。
  GPT r2 同题第一响应同样爆写 12 个动作但正确恢复并通过,属间歇性行为。
- 一次运行、三组非同期对照,以上仅确认流程,不能据此比较模型能力。

官方评分对 `preds.empty_on_errors.json` 执行:导出器把 API 异常文本记为 `model_patch` 是有测试
断言的既有行为,评分前将非 `diff --git` 开头的占位文本置空,原始 `preds.json` 原样保留;
与 `budget_20261017` 的 LF 修正同属"仅消除非补丁内容"的规范化。

台式机 Linux 容器内运行:

```bash
python experiments/pilot_tokenfy_20261018/run.py generation            # 无后缀首轮目录
python experiments/pilot_tokenfy_20261018/run.py generation --tag _r2  # 完整重跑目录
python experiments/pilot_tokenfy_20261018/run.py grading --tag _r2 --arms claude_opus_5
```

`--tag` 追加到 arm 目录、日志与 run_id;`--arms` 选择子集。生成/评分日志、执行记录
(退出码与耗时)在本目录,官方结果在各 `arm/evaluation`。