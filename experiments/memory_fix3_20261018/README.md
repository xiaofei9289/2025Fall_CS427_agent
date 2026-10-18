# 修复后记忆的五题对照（fix3）

前两轮失败均为渠道问题，目录按规则原样保留：

- `memory_fix_20261018`：TokenFY 渠道间歇性误报 `content_filter`，两组 0/5、全空补丁
  （轨迹证据 26 次 ok 对 4 次误报、11333 一题 25 次调用正常提交）。
- `memory_fix2_20261018`：密钥被改为仅可访问 `gemini-3.8-flash`（403 实测确认），
  off 组 5 题全部 `APIError` 后终止；随后改用 3.8 触发 `write_manifest`
  的"配置已变"防护，拒绝同目录重跑。

本目录为当前有效运行：模型 `gemini-3.8-flash`（`model_prices.json` 沿用 2.5 单价
作近似，成本数字仅为量级参考，两组同样受影响），消息预算 40 条（离线重放验证：
11333 轨迹 97.3% 已读代码全文可见，最近读取始终完整），任务、提示词、工具与预算
两组逐字段一致，唯一处理变量仍是 `enable_memory`（`memory_search` 两组均禁用）。

## 运行（台式机）

```powershell
python experiments/memory_fix3_20261018/desktop.py all
```

空补丁计入未解决；评分基础设施错误单列。
