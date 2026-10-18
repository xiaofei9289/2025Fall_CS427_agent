# 修复后记忆的五题对照（fix5）

`fix4` 的两组都完成了官方评分（off 3/5、on 2/5），但 `run.py` 的对照守卫正确判其无效：
`off` 组生成期间（12:45–13:15）宿主快照被整体重新同步（CRLF→LF + `history.py` 内容更新），
两组 manifest 的 `source.sha256` 不一致。归一化行尾后唯一真差异是
`src/minisweagent/memory/history.py`——对 `enable_memory=false` 的 off 组是惰性文件，
行为上两组等价，但按指纹纪律不可引用，目录原样保留。

fix5 加固启动器：运行前把 `src/` 与包文件**冻结成一次性副本**
（`desktop_validation/frozen-memory_fix5_20261018`，存在即拒绝复跑）并以 **readonly**
挂载——bind mount 是实时视图，只读挂载挡不住宿主侧改动，冻结副本才能保证两组
manifest 指纹一致。其余与 fix4 相同：模型 `gemini-3.8-flash`（定价沿用 2.5 近似，
成本仅为量级参考）、消息预算 40、任务与配置两组逐字段一致，唯一处理变量是
`enable_memory`（`memory_search` 两组均禁用）。

## 运行（台式机）

```powershell
python experiments/memory_fix5_20261018/desktop.py all
```

分阶段执行：`generation` 前创建一次性冻结副本（已存在即拒绝，防止重跑覆盖证据）；
单独执行 `grading` 会**校验并复用**该冻结副本，评分中断后可按阶段命令恢复，
不会被"目录已存在"守卫拒绝，也不需要删除作为证据的冻结源码。

预算参考：五题两组约 $1.5–3（近似单价）。空补丁计入未解决；评分基础设施错误单列。
