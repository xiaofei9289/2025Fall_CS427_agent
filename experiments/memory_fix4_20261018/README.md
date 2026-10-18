# 修复后记忆的五题对照（fix4）

前三轮失败均为 TokenFY 渠道问题，目录按规则原样保留：

- `memory_fix_20261018`：2.5 渠道间歇性误报 `content_filter`（带完整内容），两组 0/5。
- `memory_fix2_20261018`：密钥被改为仅可访问 3.8（403 `APIError`）；改配置后
  `write_manifest` "配置已变"防护拒绝同目录重跑。
- `memory_fix3_20261018`：3.8 渠道间歇性 `content_filter`+空内容（同 payload 重放实测
  为间歇故障而非真过滤），且**账户余额耗尽**（403 `预扣费额度失败, 用户剩余额度:
  ＄0.004848, 需要预扣费额度: ＄0.005238`），off 组 `[RecoveredPatch, APIError,
  ModelResponseError, ModelResponseError, APIError]` 后 `run.py` 按设计拒绝评分。

适配器两步修复（a6b2c76、00e0d51）：`content_filter` 仅在显式 `refusal` 时按真过滤
立即终止，否则按 `truncated` 受 `max_consecutive_model_errors` 有界重试。本目录为
当前有效运行：模型 `gemini-3.8-flash`（定价沿用 2.5 近似，成本仅为量级参考）、
消息预算 40、任务与配置两组逐字段一致，唯一处理变量是 `enable_memory`
（`memory_search` 两组均禁用）。

## 运行（台式机，充值后）

```powershell
python experiments/memory_fix4_20261018/desktop.py all
```

预算参考：五题两组按 token 量级估计 1–2 美元；50 题扩量约 10 倍。空补丁计入未解决；
评分基础设施错误单列。
