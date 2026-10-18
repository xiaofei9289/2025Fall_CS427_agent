# DeepSeek 50 题记忆对照（开启组）

`deepseek_scale50_20261018/baseline_r2` 是完整评分后的关闭记忆组（`deepseek/deepseek-chat`、
400 步、每题 10 美元、4 worker；官方结果 42/50、0 空补丁）。本目录是配对的**开启组**：`on.yaml` 与基线 yaml
仅 `enable_memory: true` + `memory_max_messages: 40` 不同（gemini 渠道今晨反复故障后
改用 deepseek 路线；fix5 gemini 五题对照保留作过程记录）。

`desktop.py` 启动前把台式机仓库根的 `src/` 冻结成一次性副本并断言其指纹与基线
`run_manifest.json` 的 `source.sha256` 一致（基线实际运行的源码与 Mac 仓库在 14 个
文件上有差异，开启组必须逐字节复用基线源码），以 readonly 挂载；`compare` 阶段
跨组校验 manifest（除记忆两字段外全等）并用官方评分产出 `comparison.json/md`。

## 运行（台式机，基线组生成完成后）

```powershell
python experiments/deepseek_scale50_memory_20261018/desktop.py all
```

凭据从 `DEEPSEEK_API_KEY`（进程环境或用户环境变量）读取，不写入磁盘。空补丁计入
未解决；评分基础设施错误单列。费用参考：deepseek-chat 50 题一组约 $0.2–0.5。

## 结果（台式机，2026-10-18）

| Arm | 通过 | 空补丁 | 评分错误 | 模型调用 | 成本（USD） |
| --- | ---: | ---: | ---: | ---: | ---: |
| baseline (`deepseek_scale50_20261018/baseline_r2`) | 42/50 | 0 | 0 | 1203 | 0.287565 |
| on (`on/`) | 40/50 | 0 | 0 | 1734 | 2.024742 |

- 两组源码均为 `07d8fdba4516...`，`desktop.py` 启动前已校验冻结副本指纹；`comparison.json`
  的 `matched_controls` 为 true，`treatment` 为 "history compression only; memory_search
  disabled in both arms"。
- 任务级翻转：baseline 通过而 on 未通过 3 题（`django__django-14725`、
  `matplotlib__matplotlib-23299`、`matplotlib__matplotlib-24870`）；baseline 未通过而 on
  通过 1 题（`matplotlib__matplotlib-20826`）。on 有 1 题 `budget_exhausted`。
- baseline 4 workers、on 2 workers；模型、工具、任务和预算相同，并发度未完全匹配。
- 42 vs 40 只差 2 题，落在同配置 baseline 三次运行 37/40/42 的范围内；调用数 +44%、
  成本约 7 倍。该单次配对不支持"记忆提升 50 题解决率"，也不能据此判定记忆有害；
  需要多轮重复或更多配对臂才能给出因果结论。
