# DeepSeek 50 题记忆对照（开启组）

`deepseek_scale50_20261018` 是 50 题关闭记忆的基线组（`deepseek/deepseek-chat`、400 步、
每题 10 美元、4 worker，由用户启动）。本目录是配对的**开启组**：`on.yaml` 与基线 yaml
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
