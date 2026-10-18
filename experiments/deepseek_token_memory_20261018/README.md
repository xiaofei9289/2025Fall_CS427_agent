# DeepSeek 8000-token 记忆对照

两组使用同一模型、400 步、每题 10 美元、同一源码和同一批 50 题。唯一处理是提示词预算到了之后怎么处理历史。

两边的 `context_token_limit` 都是 8000（约每 4 个字符 1 token）。关闭组丢最旧消息，不能搜索。开启组保留任务和证据摘要，并启用 `memory_search` 取回被丢掉的原文。

关闭组已有轨迹里，30/50 题的真实输入峰值超过 8000 token，所以这个上限会在多数题上生效。短于上限的调用两组发送同一份历史。

```powershell
python experiments/deepseek_token_memory_20261018/desktop.py all --workers 2
```

密钥从台式机用户环境 `DEEPSEEK_API_KEY` 读取，不写入磁盘。
