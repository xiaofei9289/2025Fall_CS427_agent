# DeepSeek 官方 50 题扩量

目的:官方渠道 `deepseek-chat` 在仓库标准 400 步 / 10 美元 / 无时间墙基线预算下,对固定
五十题全量运行生成与官方评分,作为后续组件对照的基线锚点。

方法:`configs/baseline.yaml` 的原样副本(`baseline.yaml`,400 步、$10/题、无 300 秒墙、
temperature=0);`DEEPSEEK_API_KEY` 经环境变量注入,不写入配置、仓库或命令行;4 workers;
官方评分对 `preds.empty_on_errors.json` 执行(异常文本置空,原始 `preds.json` 保留)。

## 最终结果(`baseline_r2`,2026-10-18 下午)

| 项 | 值 |
| --- | ---: |
| 完成评分 | 50/50 |
| **通过** | **42** |
| 未通过 | 8 |
| 空补丁 | 0 |
| harness 错误 | 0 |
| 模型调用 | 1203 |
| 生成时长 | 约 29 分钟(4 workers) |
| 记录成本 | **$0.288** |

未通过 8 题:`django__django-11532`、`matplotlib__matplotlib-20826`、`psf__requests-2317`、
`pydata__xarray-6992`、`pylint-dev__pylint-4604`、`pylint-dev__pylint-4661`、`sympy__sympy-13852`、
`sympy__sympy-15017`。其余 42 题全部通过,完整清单见 `baseline_r2/evaluation/grading_summary.json`。

参考:历史期末在此任务集以 50/100/250 步混用预算为 25/50。本运行为统一 400 步预算与当前版本
官方模型,42/50 显著更高;二者不可直接归因(供应商版本与预算不同),仅作基线锚点。同日两轮
400 步运行中 `matplotlib-20826` 与 `django-11532` 一轮通过一轮未过(见下节),提示单次运行
存在方差,重要比较宜做多轮复核。

## 重复运行方差(2026-10-18 补充)

`ablation5v5_20261018` 用同一 `baseline.yaml`、同一 `tasks.json`、同一 `07d8...` 源码另跑两轮
50 题 baseline:r1 37/50、r2 40/50;两轮之间有 7 个任务翻转。与本目录 `baseline_r2` 的
42/50 合并,三次同配置基线为 37/40/42。单轮相差 2 题不足以支持组件结论;后续对照以
多轮重复和配对任务为准。r3 因 HuggingFace 数据集网络不可达未启动,retrieval 臂尚未开始,
详见 [ablation5v5_20261018](../ablation5v5_20261018/README.md)。

## 事故记录(首轮 `baseline/` 目录,原样留档)

首轮生成于批次收尾瞬间恰逢 Docker/WSL2 引擎崩溃(14:47:00 `error waiting for container:
unexpected EOF`):容器内校验通过 50/50 时看到的是崩溃前的页缓存,宿主盘上只有 34 个任务产物,
最后 16 个任务的写回丢失;尾部 `grep` 管道掩盖了 docker 退出码使中断显示为成功。34 题的局部
官方评分为 26 通过(其时 20826、11532 曾通过,与 `_r2` 相反,是运行间方差的又一证据)。
教训:关键产物应以宿主侧复核为准;长管道命令勿在尾部接 `grep`,以免吞掉上游退出码;
同一工作流把 `--tag` 留痕用于灾后重跑。

## 台式机运行方式(Linux 容器)

```bash
python experiments/deepseek_scale50_20261018/run.py generation --tag _r2 --workers 4
python experiments/deepseek_scale50_20261018/run.py grading --tag _r2 --workers 4
```

`--tag` 追加到输出目录与 run_id,旧轮次原样保留;生成/评分日志与执行记录在本目录,
官方结果在 `baseline<--tag>/evaluation`。