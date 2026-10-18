# DeepSeek 8000-token 记忆对照

## 共同条件

- 同一模型 `deepseek/deepseek-chat`、同一源码快照、同一批 50 题、400 步、每题 10 美元。
- `context_token_limit: 8000`，按每条消息 `字符数 / 4 + 4` 估算；`enable_memory` 两组都关。
- **两组都固定保留系统提示和原任务。** 丢失任务说明属于目标丢失，不属于记忆，因此不能算作处理变量。

## 唯一处理变量

| | 关闭组 `off` | 开启组 `on` |
| --- | --- | --- |
| `history_policy` | `truncate` | `compress` |
| 超限后 | 丢掉最旧的非系统消息（任务已固定），仍放不下时截断最新一条 | 保留任务、一段 `[memory]` 证据摘要和放得下的最近完整动作/观察 |
| `memory_search` | 无 | 有：`mode=full` 返回匹配消息正文，`index=N` 直接打开被丢掉的某一条 |

摘要只记录真正执行过的工具调用：成功读取（最多约 1000 字摘录）、修改导致旧读取过期、尚未被后来成功覆盖的非零退出。模型正文里提到的路径不算证据。bash 读路径和工具路径统一按 `/testbed` 归一化，重定向和 heredoc 视为写而不是读。摘要本身也要挤进 8000；放不下时退回成和关闭组一样的截断。若最新一轮自身就超过预算，保留该轮动作并截断观察，而不是只发摘要。

关闭组没有这份摘要，也就不提供这个工具。`tests/run/test_token_memory_config.py` 会核对：上限相同、策略分别是 truncate 和 compress、搜索工具只在开启组。

## 预注册判据（跑之前定好，不因结果改）

1. **主判据**：生效题上的 `gained` / `lost` 不一致对与 McNemar 精确 p，同时报不一致对数量；单次运行、50 题，10pp 左右的差异本来就不显著，不要只贴 p 值。
2. **内置安慰剂**：两组都没有任何调用触到 8000 的题，历史上送的完全相同，结果必须一致。`comparison.md` 会列出这个子集的题数和差异题；一旦有差异，说明 provider 非确定性存在，整轮解释要打折。
3. **归因证据**：日志要能给出“某次调用被压缩 → 摘要/检索 → 后续成功”的因果链，而不只是分数差。`memory_search` 的调用次数与命中次数如实报告；如果为 0，就说明增益来自摘要而不是检索，不能写成检索的功劳。

不重复跑到显著为止，也不用重跑替换关闭组的失败轨迹。

## 口径

8000 是估算 token，不是 provider 计数。`字符数 / 4` 对代码偏低、对中文偏低得更多。绝对准确性不影响两组对照（两边用同一个估算器），但报告里应写 estimated tokens；`comparison.md` 会用真实 `usage.prompt_tokens` 给出“实际 / 估算”的中位比值和样本数，方便说明 8000 实际相当于多少真实 token。

## 运行

```powershell
python experiments/deepseek_token_memory_20261018/desktop.py all --workers 2
```

密钥从台式机用户环境 `DEEPSEEK_API_KEY` 读取，不写入磁盘。`compare` 阶段写 `comparison.json` 和 `comparison.md`，后者包含分组指标、不一致对、McNemar p、安慰剂子集、`memory_search` 调用统计和估算器校准比值。

## 可选第三条臂

`on_summary_only.yaml` 已经准备好：它和开启组完全一样，只是不带 `memory_search`。跑它就多一张表，把“摘要”和“检索”的贡献拆开：

```powershell
python experiments/deepseek_token_memory_20261018/desktop.py all --arm on_summary_only --workers 2
```

`report()` 会自动发现任何带 `run_manifest.json` 的目录，并分别与 `off` 做配对统计。默认的 `--arm both` 只跑两组主对照，不跑这条臂；跑不跑由预算决定。
