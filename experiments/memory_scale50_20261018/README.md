# 修复后记忆的 50 题受控扩量

本目录是 `memory_fix_20261018` 五题对照的扩量版本，配置由五题版本程序化派生：
`on.yaml` / `off.yaml` 除 `enable_memory` 外逐字段一致（已校验），任务为课程固定的
50 题清单（`experiments/configs/verified50_tasks.json`）。两组均禁用 `memory_search`，
单一处理变量是历史压缩。开启组使用与五题版相同的 40 条消息预算。每题 50 步、
1 美元上限、单 worker，全局成本上限 50 美元。

## 启动门槛（先读）

1. **仅当五题对照的官方评分显示开启组通过数严格高于关闭组时才启动本实验**；持平或更低
   即止损，不投入 50 题预算。课程加分要求的是"可证明提升 agent 表现"，通过数持平、
   只省 token 不构成加分证据。
2. 运行前必须把最新修复源码（2026-10-18 的 `default.py` 去重与记忆优雅降级、
   `session.py` 清理）同步到 `desktop_validation/memory-fix-20261018`；`desktop.py`
   会检查快照中任务文本只出现一次，旧快照会被拒绝。两组共用同一快照。
   同步用 `powershell -ExecutionPolicy Bypass -File experiments\memory_fix_20261018\refresh_snapshot.ps1`
   （在 `git pull` 后执行，自动镜像并校验快照新鲜度）。
3. 50 题对照**只跑一次**：不得根据其结果回头调整配置再跑。调参只在五题集上进行；
   最终声明以单次 50 题结果为准。前 5 题与五题 pilot 重叠（迭代用过），报告时
   `comparison.md` 会同时给出全 50 题与剔除前 5 题后的结果。

## 运行（台式机）

```powershell
python experiments/memory_scale50_20261018/desktop.py all
```

凭据与镜像要求与 `memory_fix_20261018` 相同：`cs427-validation:local` 镜像就绪，
TokenFY 密钥从台式机环境读取，不写入配置或日志。生成与评分各留日志和
`*_execution.json`；两组的预测、轨迹、源码快照和官方结果分别位于 `off/`、`on/`，
`run_manifest.json` 记录运行 ID 与源码身份。

## 产出与解读

评分完成后 `run.py` 自动生成 `comparison.json` 和 `comparison.md`：解决数、空补丁数、
评分基础设施错误数、API 调用数与成本。空补丁计入未解决；评分基础设施错误单列，
不并入解决率。50 题两组预计需要数小时，建议预留整段时间并保持 Docker 引擎可用。
