# 修复后的五题记忆对照

本轮重新生成关闭/开启记忆两组补丁，再分别使用仓库内官方 SWE-bench harness 评分。
原 `memory_credit_20261017` 的预测、轨迹和评分不覆盖。

固定原来的五题、TokenFY `gemini-2.5-flash`、每题 50 次调用和 1 美元停止阈值、单 worker。
两组使用同一份修复代码及无效回复处理，工具列表一致，均关闭 `memory_search`；仅
`enable_memory` 不同，开启组使用 40 条消息预算，测试历史压缩与证据摘要。

12 条消息预算已在两轮对照（`memory_compare_20261018` 0/5、`memory_retest_20261018` 1/5，
各 3 个空补丁）中显示开启组显著劣于关闭组，本轮弃用。40 条预算下压缩从第 21 次调用才开始：
短任务（Django 各题 14~23 次调用）基本不压缩，压缩只在长对话中生效，符合"刚读到的代码
不应立即被挤出"的要求。

## 离线重放验证

生成前先用失败轨迹离线重放，确认开启组发给模型的内容里刚读的重要代码仍在：

```bash
python -m minisweagent.run.extra.memory_replay \
  --trajectory <失败任务的 .traj.json> --memory-max 12 --memory-max 40 \
  --output experiments/memory_fix_20261018/replay_<instance>.json
```

工具逐次重放模型调用，把每次调用前的历史读取分为完整可见 / 摘要摘录 / 丢失三档。对
仓库内 50 步 Matplotlib 轨迹的基线验证：12 条预算下 44/50 次调用被压缩、仅 16.4% 的读取
完整可见；40 条预算下压缩推迟到第 21 次调用之后、64.2% 完整可见且最近一次读取从未丢失
（`replay_matplotlib.json`）。台式机上 12 条预算两轮的失败轨迹（`django__django-11333`、
`django__django-14855` 等）恢复后应做同样检查。


台式机上运行前先同步本轮改动（40 条消息预算、`memory_replay` 工具、严格高于门槛）：

```powershell
git pull
powershell -ExecutionPolicy Bypass -File experiments\memory_fix_20261018\refresh_snapshot.ps1
```

刷新脚本把仓库 `src/`、`tests/` 镜像进 `desktop_validation\memory-fix-20261018` 快照，并校验
`default.py` 任务文本唯一、`memory_replay.py` 存在、`on.yaml` 已是 40 条预算；旧快照会被拒绝。

然后启动：

```powershell
python experiments/memory_fix_20261018/desktop.py all
```

凭据从台式机进程/用户环境的 `TOKENFY_API_KEY` 读取，也可通过 `--credential-file` 指定已有
TokenFY 配置文件。密钥只作为容器环境变量传入，不写入实验配置或命令行。
生成和评分分别保存日志，预测、轨迹、源码快照和官方结果位于独立的 `off/`、`on/`。

当前状态：**生成和官方评分均未启动**。已同步修复源码和运行脚本，并验证两组配置仅
`enable_memory` 不同。用户完成 Docker 重装/迁移后，已确认台式机 Linux 引擎恢复，
但镜像和缓存为空。正在用 `Dockerfile.validation` 重建评测镜像；Docker Hub 基础镜像
下载失败后，改用项目已采用的 Docker 官方 ECR Public 分发，构建继续进行。

目前网络阻塞：台式机访问 Docker Hub 和 Hugging Face 的 HTTPS 失败，任务镜像及数据集
尚未重新下载，已请求恢复该网络。ECR Public 和 TokenFY 服务可访问。模型凭据已由用户
提供，仅在后续生成进程中临时使用，不写入配置、仓库或实验日志。

前置条件恢复后，完成运行会生成 `comparison.json` 和 `comparison.md`；空补丁计入未解决，
评分基础设施错误单独列出。单次五题结果不能外推为全部课程任务的稳定收益。
