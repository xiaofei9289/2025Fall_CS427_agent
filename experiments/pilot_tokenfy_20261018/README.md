# 四模型五题流程验证(TokenFy 三渠道 + DeepSeek 官方)

目的:验证三个 TokenFy 单渠道模型(`claude-opus-5`、`gpt-5.6-sol`、`gemini-3.8-flash`)与
DeepSeek 官方 `deepseek-chat` 跑通 SWE-bench 生成与官方评分流程。各组渠道资源与预算约束
不同,不构成受控模型对照。

四个 arm 均用 `pilot_20261017` 的固定五题(`tasks.json`)与预算:每题 50 步、1 美元、
300 秒、单 worker,仅模型不同。TokenFy 组:`model_class: litellm`、`api_base: https://TokenFy.net/v1`,
成本按网关公开计价换算的 `tokenfy_model_registry.json` 统计,调用超时放宽到 120 秒;
`deepseek_chat.yaml` 与 DeepSeek 历史预算基线逐字节一致(超时 45 秒),官方渠道、litellm
内置价格表、上下文缓存生效。密钥一律经 `TOKENFY_KEY_<ARM>` 环境变量注入,不写入配置、
仓库或命令行。全局成本上限默认 10 美元,可由外部 `MSWEA_GLOBAL_COST_LIMIT` 覆盖。
首轮(无后缀目录)因三个 TokenFy key 余额中途耗尽部分失败,原样保留;`_r2` 为完整运行。
`deepseek_chat` 组比其余三组晚约半小时加入。

| 官方结果(\_r2 完整运行) | claude_opus_5($1/题) | gpt_5_6_sol | gemini_3_8_flash | deepseek_chat |
| --- | ---: | ---: | ---: | ---: |
| 完成评分 | 5/5 | 5/5 | 5/5 | 5/5 |
| 通过 | 1(14855) | **4**(11333、14855、15315、20826) | 1(11333) | **3**(11333、14855、15315) |
| 未通过 | 2(11333、11532) | 1(11532) | 0 | 1(11532) |
| 空补丁 | 2(15315、20826) | 0 | 4 | 1(20826) |
| harness 错误 | 0 | 0 | 0 | 0 |
| 模型调用数 | 62 | 80 | 176 | 98 |
| 生成耗时 | 374 秒 | 709 秒 | 1197 秒 | 约 240 秒 |
| 估算花费 | $5.28 | $2.03 | $3.26 | $0.02 |

DeepSeek 组的 3/5 与 `pilot_20261017` 基线在任务级完全一致(同败 11532、20826),锚点可靠。

## Claude 单题预算 $1 → $3(`claude_opus_5_3usd`)

`claude_opus_5_3usd.yaml` 仅把 `cost_limit` 提到 3 美元。`_r3` 全 5 题中 3 题完整、2 题被
当时硬编码的 $10 全局限额截断;`_r2`/`_r5` 组合为该预算下的五题完整结果(11532/14855 补跑于
`_r5`,全局限额已改由环境变量覆盖、并新增 `--tasks` 子集重跑):

| 任务 | $1/题 | $3/题 | 结论 |
| --- | --- | --- | --- |
| django-11333 | 未通过($1.00) | **通过**($3.03) | 预算曾是第一约束 |
| django-15315 | 空补丁($1.08) | **通过**($3.15) | 同上 |
| django-14855 | 通过($1.08) | 通过($3.02) | 两预算均过 |
| django-11532 | 未通过 | 未通过($3.18) | 难题,当日所有模型同败 |
| matplotlib-20826 | 空补丁($1.04) | 空补丁($3.07) | 时间瓶颈,与成本无关 |

合计 $3 组:3/5 通过、$16.51(claude 渠道当日另有 `_r4` 事故消耗 $6.22,系 `--tasks` 实现
缺陷导致全 5 题误跑、人工强杀止损,产物留档、不计入对照)。

matplotlib-20826 在 DeepSeek($0.01)与 Claude($4.1)上同样以"探索耗尽、未及修改"收场;
Claude $3 轨迹显示它在 300 秒上限前已定位到正确修复方向(`_label_outer_xaxis` 系列)但
没有时间写出——该题的瓶颈是 300 秒时间上限与探索策略,正是 retrieval 工具预算实验
(`repo_map`/`code_search`)要解决的问题。

## 观察

- `gpt-5.6-sol` 五题全部正常提交(单题 $0.23–0.60),4/5,行为最稳;仅败难题 11532。
- `claude-opus-5` $1 组五题全部撞预算收尾;$3 组马斯洛上移到 3/5。高价模型整组对照前
  需重设单题预算,并同步放宽 300 秒时间上限,否则 matplotlib 类大库探索会先耗尽时间。
- `gemini-3.8-flash` 仅 11333 产出并解析;其余四题思考 token 消耗大量步数、时间与预算
  (20–50 次调用)而未留下改动;django-15315 两次调用即空提交,同款行为在 gpt 首轮 15315
  复现。排查确认失败链:第一响应一次性写出 10–35 个动作的模拟轨迹(含修复动作,均未
  执行),触发格式错误后模型误称"修复已完成"并立即提交;当时仓库的格式错误反馈硬编码
  `actions=[]`,实际检出 12/35 个动作却始终提示 "found 0 actions",已在 `default.py`
  修正为传入真实动作列表并补回归测试。GPT r2 同题第一响应同样爆写 12 个动作但正确恢复
  并通过,属间歇性行为。
- 一次运行、四组非同期对照、部分题目渠道预算不同,以上仅确认流程与失败模式,不能据此
  比较模型能力。

官方评分对 `preds.empty_on_errors.json` 执行:导出器把 API 异常文本记为 `model_patch` 是有测试
断言的既有行为,评分前将非 `diff --git` 开头的占位文本置空,原始 `preds.json` 原样保留;
与 `budget_20261017` 的 LF 修正同属"仅消除非补丁内容"的规范化。

台式机 Linux 容器内运行:

```bash
python experiments/pilot_tokenfy_20261018/run.py generation            # 无后缀首轮目录
python experiments/pilot_tokenfy_20261018/run.py generation --tag _r2  # 完整运行目录
python experiments/pilot_tokenfy_20261018/run.py grading --tag _r2 --arms deepseek_chat
python experiments/pilot_tokenfy_20261018/run.py generation --arms claude_opus_5_3usd \
  --tag _r5 --tasks experiments/pilot_tokenfy_20261018/tasks_r3_redo.json
```

`--tag` 追加到 arm 目录、日志与 run_id;`--arms` 选择子集;`--tasks` 指定实例子集文件
(生成与评分都要带同一 `--tasks`);全局限额经 `MSWEA_GLOBAL_COST_LIMIT` 外部覆盖。
生成/评分日志、执行记录(退出码与耗时)在本目录,官方结果在各 `arm/evaluation`。