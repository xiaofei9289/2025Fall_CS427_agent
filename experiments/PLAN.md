# Agent 深化：基线与代码定位

第一阶段交付基线审计、受控实验入口、Python AST/BM25 定位与仓库地图。
后续依次推进证据记忆、测试驱动阶段流程和失败恢复。

## 历史基线

原始文件保持为证据；审计结果输出到独立目录。

```bash
python -m minisweagent.run.extra.audit \
  --run-dir deliverables_midterm/generation \
  --evaluation-dir deliverables_midterm \
  --output experiments/baseline_audit/midterm

python -m minisweagent.run.extra.audit \
  --run-dir deliverables_final/generations \
  --evaluation-dir deliverables_final \
  --output experiments/baseline_audit/final
```

每次审计生成 `audit.json` 和逐任务 `report.md`。必须指定一个具体运行目录，
例如期末的 `generations` 与 `rerun-verified-40` 属于不同运行。
评测结果决定是否解决；轨迹中的路径错误、环境错误、测试失败仅作为人工复查线索。
`trace_matches_prediction=false` 的记录不能用于解释提交 patch 的表现。

| 运行 | 预测 | 轨迹 | 已解决 | 完整性问题 |
|---|---:|---:|---:|---|
| 期中 | 50 | 50 | 19/50 | 无 |
| 原期末 | 50 | 49 | 25/50 | 1 份缺失轨迹，1 份 patch 不匹配 |

原期末的 25 个未解决任务包括：17 个需要进一步复查、4 个预算耗尽、4 个空提交。
期中统一为 250 步；期末混用了 50、100、250 步。历史轨迹均未开启 memory。
这些数据支持描述历史成绩，不能证明某一组件带来的因果收益。

## 固定配置与任务

`configs/baseline.yaml` 固定当前模型 `deepseek/deepseek-chat`、400 步、每任务成本阈值 10 美元、
temperature=0、Docker 参数和提示词，关闭 memory。
`configs/retrieval.yaml` 仅在相同配置上增加 `repo_map`、`code_search` 两个工具。
`configs/verified50_tasks.json` 固定课程选取的 50 个任务及其顺序。

先在固定的 5 题上检查整个运行与评测流程，再扩到全部 50 题。
下面是实际会调用模型的 pilot 命令；使用不同输出目录保存两个实验组。

```bash
MSWEA_GLOBAL_COST_LIMIT=10 python -m minisweagent.run.extra.swebench \
  --subset verified-50 --instance-ids experiments/configs/verified50_tasks.json \
  --slice 0:5 --workers 1 --config experiments/configs/baseline.yaml \
  --output runs/pilot-baseline

MSWEA_GLOBAL_COST_LIMIT=10 python -m minisweagent.run.extra.swebench \
  --subset verified-50 --instance-ids experiments/configs/verified50_tasks.json \
  --slice 0:5 --workers 1 --config experiments/configs/retrieval.yaml \
  --output runs/pilot-retrieval
```

batch runner 生成 `run_manifest.json` 和 `source.zip`，记录运行 ID、任务描述与 base commit、
配置、依赖版本及源码内容身份。轨迹关联同一运行 ID；各 worker 使用独立配置副本。
源码快照包含未提交的实现，支持恢复这次实际使用的源码。源码、配置或任务改变后需使用新目录；
已有预测却没有 manifest 的旧目录也需作为历史记录保留，另开新目录。
运行前后均应保留对应 Docker 镜像；当前配置使用镜像 tag，跨机器重现还需固定对应 image digest。

使用仓库附带的 SWE-bench harness 对两个输出分别评分：

```bash
PYTHONPATH=SWE-bench python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --predictions_path runs/pilot-baseline/preds.json --max_workers 1 \
  --run_id pilot-baseline --report_dir runs/pilot-baseline
```

另一个实验组使用其对应 predictions 路径、run_id 和 report_dir。评分后可对该运行目录执行 audit，
检查其 manifest、轨迹、预测和评测记录。对照指标为解决数、空 patch 数、
每题 API 调用数、输入/输出 token、总成本，以及总成本除以解决数。
固定相同模型、任务、提示词和预算；扩大试验时预留独立任务集，避免只围绕这 50 题调参。

## 代码定位

`repo_map` 输出与 issue 相关的 Python 文件、类、函数签名和行范围；
`code_search` 使用 BM25 与符号名匹配排序，并返回 qualified name、docstring 和行范围。
模型再用已有读取工具查看候选代码。

索引遵守 Git ignore，包含 tracked 文件和新建的非 ignored Python 文件。
跳过符号链接、超过 1 MB 的文件和无法解析的文件，并报告跳过原因。
它在环境内部执行自包含的标准库实现，支持 Python 3.6+；旧解释器的结束行号为近似值。
当前每次调用重新构建索引，文件修改立即可见；增量索引与 embedding 留给后续有数据支持时加入。
地图使用字符预算，尚未实现 tokenizer 精确预算。

运行本仓库的人工标注冒烟集，不调用模型：

```bash
python -m minisweagent.run.extra.localization_eval \
  --cases experiments/localization_smoke_cases.json \
  --output experiments/localization_smoke_result.json --k 5
```

评测分别输出文件级 BM25 与符号级 BM25 的 Recall@K、Hit@K 和 MRR。
`gold_files` 只用于评分，检索输入仅包含 issue 文本。
这 4 条案例验证工具链，不能作为 SWE-bench 修复能力提升的证据。
正式定位评测需为每个任务提供处于正确 base commit 的 checkout，再按相同格式标注目标文件。

## 后续里程碑

五题 pilot 已在台式机完成官方评分：baseline 3/5，retrieval 4/5。那次 retrieval 没有调用定位工具。
强制第一步调用查找之后的重跑在 `experiments/gate-20261017`：baseline 4/5，retrieval 3 题通过、1 题未通过、1 题空补丁。五条 retrieval 轨迹都调用了 `code_search`。两组都是一次运行，不能据此宣称查找带来提升。

同工具、同硬预算的收尾对照在 `experiments/budget_20261017` 已完成。原始关闭组有一题导出换行错误；统一补齐末尾 LF 后的独立验收为关闭组 3/5、开启组 5/5。提示只在一题触发，且修复在提示前已形成；没有减少整组调用数、生成耗时或空补丁的证据。下一轮应使用相同的第 45 步对话和工作区进行分叉，再用未参与调参的任务验证。

`memory_fix_20261018` 的首次运行被 TokenFY 渠道间歇性误报 `content_filter` 提前终止（两组 0/5、
全空补丁；轨迹证据为 26 次 ok 对 4 次误报、11333 一题 25 次调用正常提交）。适配器已改为
`content_filter` 且有可用内容时按截断处理（a6b2c76），重跑位于 `experiments/memory_fix2_20261018`。
该密钥随后被改为仅可访问 `gemini-3.8-flash`（403 实测确认），fix2 改用该模型并把
`model_prices.json` 沿用 2.5 单价作近似——成本数字仅为量级参考，两组同样受影响。
fix2 的 off 组首轮 403 全部 `APIError` 终止，改配置后又被 `write_manifest`
"配置已变"防护拒绝同目录重跑，两轮目录均原样保留；fix3 改用 3.8 后 off 组死于
3.8 渠道间歇性 `content_filter`+空内容与**余额耗尽**（403 `预扣费额度失败, 用户剩余额度:
＄0.004848`），同 payload 重放证明为间歇故障而非真过滤。适配器最终形态（00e0d51）：
仅显式 `refusal` 按真过滤立即终止，其余 `content_filter` 按截断有界重试。
fix4 两组完成官方评分（off 3/5、on 2/5），但 `off` 组生成期间宿主快照被整体重新同步，
manifest `source.sha256` 不一致被守卫判无效；归一化行尾后唯一真差异为 `history.py`
（对 off 组惰性），结果只作预览，目录保留。fix5 加固：冻结一次性源码副本并以 readonly
挂载；`off` 组 3/5 时被 SIGKILL（137），保留作过程记录后放弃。随后改用 deepseek 路线：
`experiments/deepseek_scale50_20261018` 为 50 题关闭记忆基线组（用户启动，400 步、
每题 10 美元、4 worker），`experiments/deepseek_scale50_memory_20261018` 为配对开启组，
启动器冻结基线实际源码并断言指纹一致，`compare` 阶段产出跨组官方对照。
消息预算已从 12 条提高到 40 条（12 条在两轮对照中开启组 0/5、1/5，弃用），生成前先用
`minisweagent.run.extra.memory_replay` 对失败轨迹离线重放，确认刚读的重要代码仍在发送内容中
（11333 轨迹重放：25 次调用中 5 次压缩，已读代码 97.3% 全文可见，最近一次读取始终完整）。
50 题扩量配置已预置于 `experiments/memory_scale50_20261018`，仅在五题对照显示开启组通过数
严格高于关闭组后单次运行，报告同时给出全 50 题与剔除前 5 题调参任务的结果。

四个渠道模型的五题流程验证位于 `experiments/pilot_tokenfy_20261018`（TokenFy 的
`claude-opus-5`、`gpt-5.6-sol`、`gemini-3.8-flash` 与官方 `deepseek-chat`）：完整重跑
（`_r2`）与官方评分零 harness 错误，gpt-5.6-sol 4/5、deepseek 3/5（与历史基线任务级
一致）、claude/gemini 各 1/5（$1/题）。Claude $3/题组（`claude_opus_5_3usd`，`_r3`+`_r5`）
为 3/5，11333/15315 在预算放宽后通过；matplotlib-20826 在 DeepSeek（$0.01）与 Claude
（$4.1）上同样是"探索耗尽 300 秒无改动"，时间上限与探索策略是该题瓶颈，恰为 retrieval
工具实验的靶子；`_r4` 因 `--tasks` 实现缺陷误跑全 5 题并强杀止损（$6.22，留档不计对照）。

官方渠道 `deepseek-chat` 的 400 步预算五十题全量运行位于 `experiments/deepseek_scale50_20261018`
（`baseline_r2`）：**42/50 通过、零 harness 错误、1203 次调用、$0.288、约 29 分钟**，显著高于
历史期末混用预算口径的 25/50（版本与预算不同，不可归因比较），作为后续组件对照的基线锚点。
同日两次运行中 20826/11532 一过一败，单次运行方差需以多轮复核为重。首轮 `baseline/` 因批次
收尾瞬间 Docker/WSL2 引擎崩溃丢失 16 个任务写回（容器内校验读到崩溃前页缓存），34 幸存题为
26 通过；产物留档，宿主侧复核与退出码管道保护已列入教训。
15315 的"两次调用空提交"失败链（模拟式爆写 + 格式错误反馈谎报 found 0 actions + 幻觉
完成即提交）已定位，`default.py` 计数反馈已修复并补回归测试。各组渠道与预算约束不同，
不能据此比较模型能力。

2026-10-18 独立审查（台式机隔离副本复现）确认 7 个实现缺陷并全部修复（本仓库源码）：
TUI confirm 模式对工具动作 KeyError、压缩固定首条任务致续接任务丢失、bash 修改后摘要
保留未过期源码、session 保存失败掩盖提交结果、结构错误 session 崩溃、grep 错误码被
`|| test $? = 1` 掩为成功、工具 `/testbed` 路径约束不完整（现为环境工作区组件级校验）。
证据有效性修复最关键：`sed -i`/重定向/git apply/heredoc 等写入现使旧读取按路径或全量
过期；真实回归已入库。fix5/scale50 启动器同时修复评分阶段守卫（单独 grading 复用冻结
副本）；scale50 加固为冻结副本挂载。既有 fix5 冻结结果不受影响；修复后源码需在 fix5
归档后经新目录（fix6）重做五题对照，作为扩量前最后一轮 gate。

1. 五题查找对照和离线定位已完成。文件级 Hit@5 为 4/5；Matplotlib 的官方文件排第 54，见 `experiments/localization_verified5`。
2. 用相同预算扩到固定任务集之前，先解释邮件题在主文件已命中时仍失败的原因。
3. 将历史压缩改为动作/观察配对、token 预算和可追溯证据状态，并加入单独消融组。
4. 增加复现、修改、验证、提交的阶段状态；区分环境失败与代码失败，预留验证预算。
5. 用完整对照结果、代表性失败案例与可运行 demo 展示项目。
