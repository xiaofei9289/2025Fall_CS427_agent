# 修复后记忆的五题对照（重跑）

`memory_fix_20261018` 的首次运行已由官方评分确认**无效**：TokenFY 渠道间歇性返回
`finish_reason=content_filter` 但内容完整可用（无 refusal），适配器把每次误报当作
真过滤并立即终止，两组 0/5、全部空补丁、每组仅 20/32 次调用。轨迹证据：
`django__django-11333` 一题 25 次 `ok` 调用正常提交，全组 26 次 ok 对 4 次误报。
该目录原样保留作为渠道问题记录，不用于任何结论。

适配器已改为：`content_filter` 且内容非空、无 refusal 时按 `truncated` 处理，受
`max_consecutive_model_errors`（默认 3）约束可重试；只有空内容或显式拒绝才立即终止。
两组使用同一处理逻辑，`cs427_memory.md` 已同步更新。本目录是源码变更后的重跑，
配置与 `memory_fix_20261018` 逐字段一致（仅 `litellm_model_registry` 指向本目录），
任务为相同五题，唯一处理变量仍是 `enable_memory`。

## 运行（台式机）

```powershell
python experiments/memory_fix2_20261018/desktop.py all
```

其余前置（源码快照含适配器修复、`cs427-validation:local` 镜像、TokenFY 密钥）与
`memory_fix_20261018` 相同。空补丁计入未解决；评分基础设施错误单列。
