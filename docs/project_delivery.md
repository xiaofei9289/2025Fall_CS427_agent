# CS427 Coding Agent：项目说明与交付边界

本项目基于 mini-swe-agent，把“给定公开仓库 Issue → 定位代码 → 修改 → 测试 → 导出补丁”的循环扩展为可记录、可比较、可通过 API 提交的工程原型。上游提供基本 Agent 循环、模型适配、执行环境和 SWE-bench 接入；本仓库的扩展集中在工具、记忆、代码检索、实验审计和持久化服务。简历中应明确这一来源，不把整个框架写成独立自研。

## 已形成的能力

| 能力 | 实现证据 | 可以说明的工程判断 |
| --- | --- | --- |
| 工具执行 | 读写、搜索、替换、定义定位，统一 action/observation | 工具协议、环境内执行、错误回传 |
| 记忆 | salient history、会话持久化、memory_search、ContextVar | 上下文预算、可检索历史、并发任务隔离 |
| 代码检索 | 在目标环境构建 Python AST，BM25 与符号排序，repo_map，带片段的 code_context，跨进程索引缓存，issue-aware repo_brief，find_references 轻量关系扫描 | 避免宿主索引与真实工作副本不一致；减少重复解析；把排序结果变成可读、可预算的上下文；把“找到”推进到“影响面” |
| 评测 | 固定题目、预算、配置和源码快照，预测/轨迹/评分关联审计，retrieval_audit 区分检索未命中/未读/未编辑/验证失败 | 可复核的结果口径，识别数据缺失及混跑；避免把下游失败误归因为检索 |
| 服务 | FastAPI、SQLite、独立 worker/工作副本、取消与恢复、checkpoint | 长任务生命周期、恢复语义与累计预算 |
| 可观测性 | 每任务事件游标、模型耗时/成本/usage、工具耗时、验收日志 | 根据失败证据定位问题，而非只看最终回答 |
| 交付 | Docker/Compose 定义、台式机运行说明、候选补丁下载 | 从本地脚本到可操作服务的边界 |

## 面试可用的介绍

“我基于 mini-swe-agent 做了一个面向 GitHub Issue 修复的 Coding Agent 项目。除了扩展文件操作和记忆工具，我重点补了两块工程能力：一是把配置、题目和源码快照固定下来，关联预测补丁、执行轨迹和官方测试，避免结果混跑；二是把任务做成持久化 API，每个任务使用独立工作副本和进程，可以取消、保存 checkpoint 并恢复。恢复时保留累计调用预算，遇到动作中断会先检查工作区，避免重复执行修改。”

一个可具体说明的工程问题来自台式机集成测试：调用方先读到 succeeded，再拉取事件时，结束事件可能尚未提交。原因是两次数据库写入之间存在可见性窗口。修复将任务终态、结果和结束事件放进同一 SQLite 事务，保留原测试验证该读后读契约；相关日志在 `desktop_validation` 中。这是任务状态与可观测记录需要一起设计的实例。

另一个问题由官方验收发现：diff 清洗的 `.strip()` 去掉了末尾换行，导致新增函数的补丁无法应用。修复保留 diff 的尾部结构，回归直接使用导出字节执行真实 Git 应用，并校验文件内容。实验保留原始错误，再对两组全部补丁的副本统一补齐末尾 LF，单独验收，没有根据成绩重跑模型。

强制检索实验还暴露了策略边界问题：默认 Agent 的首步限制会影响服务继承的提交动作。服务 worker 现已明确关闭这条实验限制；服务配置改用 `repo_brief` 预注入候选路径/符号，保留检索工具供模型选择。实验入口另设 `retrieval_gate.yaml` 复现强制首步。服务执行、取消、恢复与空补丁验收用例用于防止这类改动破坏任务生命周期。

历史 19/50 → 25/50 只能描述为两个课程版本的观察值，不能归因于新增检索、记忆或服务化。最初两轮台式机五题评分中，工具未被调用时是 baseline 3/5、retrieval 4/5；强制先调用 `code_search` 后是 baseline 4/5，retrieval 3/5（另外 1 题未通过、1 题空补丁）。空补丁按未解决计入分母。这些单次五题结果不足以证明总体提升。服务端配置的 pytest 通过同样不等于 SWE-bench 的隐藏验收通过。

`experiments/gate-20261017/retrieval_audit.md` 进一步把“检索成功”和“修复成功”拆开：五题的官方文件都进入首轮检索 top-10、都被读取，四题被编辑，但只有三题解决。Matplotlib-20826 读到了 `axis.py` 却没有形成编辑，Django-11532 编辑了 `message.py` 但更大的邮件测试集失败。这说明下一步的瓶颈是检索后的收敛、编辑和验证，而不是继续增加召回；在 50 题配对实验完成前，不应宣称检索提升了解决率。

离线五题的确定性 `repo_brief` 把候选文件 Hit@5 从 0.80 提到 1.00，MRR 从 0.50 提到 0.90（见 `experiments/localization_verified5/brief_result.json`）。它仍然是离线、五题、只测排序的结果；在线收益需要 `brief_only` / `retrieval` 对照验证。

50 题复核修正了五题的乐观结论：上下文选择 Recall@5 为 0.691、Hit@5 为 0.76、MRR 为 0.560，文件级 BM25 为 0.534/0.60/0.467，符号级 BM25 为 0.531/0.60/0.437，确定性 `repo_brief` 回落到 0.645/0.68/0.488。上下文选择相对文件级 BM25 多命中 11 题、只丢 1 题；`repo_brief` 的五题 Hit@5=1.00 没有在 50 题保持，说明“优先相信 issue 中显式路径/符号”会过拟合小样本。这些结果只说明候选排序，不是 SWE-bench 解决率；详见 `experiments/localization_verified50/result.json`。

## 已补上的证据

台式机 `desktop_run.py` 的 build、checks、demo、grading 均已退出码 0。五题官方日志和对照表在 `experiments/pilot_20261017`。`django__django-11532` 两组都修好了目标测试，但 18 个原有邮件测试在 SMTP `EHLO` 上报 ASCII 编码错误。demo 使用确定性模型走通提交、工具调用、pytest、补丁下载，并在 API 容器重启后保留 `n_calls=2`；该演示不作为模型性能证据。

最终回归在 `PC-20230218RALO`（`192.168.1.11`）的 Linux 容器中完成：239 项通过、9 项 slow 测试未运行，静态检查通过。预算收尾、候选补丁导出、Docker 服务演示及重启验证已通过。记录见 [desktop_validation](../desktop_validation/README.md)。

本轮补充了临近预算上限的收尾提示，并在独立验收前原子保存候选补丁；验收超时后仍可下载修改。结果区分主动提交、退出后恢复和验收状态，轨迹保留原始预算耗尽原因。实现说明见 [预算收尾与候选补丁保全](budget_finalization.md)。

同工具、同硬预算的五题收尾对照已完成：原始关闭组为 3 题通过、1 题失败、1 题补丁应用错误；原始开启组 5/5。两组统一补齐末尾换行后的独立验收为关闭组 3/5、开启组 5/5。提示只在 Matplotlib 一题触发，且修复在提示前已经存在；邮件题的分差发生在没有触发提示的任务中。因此不能将整组分差归因于收尾。两组总调用数为 104 和 109，生成耗时为 263.51 和 340.29 秒，也没有总体节省调用或延迟的证据。估算生成成本合计 0.04391898 美元，评分没有新增模型调用。详见 [实验报告](../experiments/budget_20261017/README.md)。

真实业务部署、用户量、长期稳定性、分布式执行、OAuth/多租户隔离尚未被本项目验证。RAG、MCP、工作流框架和云部署应随目标岗位及具体用例选择；不要把未使用的技术补成简历关键词。面向训练/强化学习岗位，本项目还缺数据构建、训练和策略评测经验，需要另一条实验路线。

面向 Agent 应用工程岗位，下一步优先补两类证据：在相同第 45 步对话与工作区上分叉，验证收尾提示对最后五次调用的实际作用；再选择真实使用场景，留下用户反馈、完成率、延迟和成本记录。更大任务集应包含未参与调参的验证题，并增加重复运行。多租户和分布式执行应在实际部署需求出现后补充。

## 2026-10-19 最终收敛结果

A/B/C memory p2final 在 10 题 pilot 上完成 generation + official grading，`valid=True`：

| Arm | Policy | Resolved | Cost | API calls | Search calls |
| --- | --- | ---: | ---: | ---: | ---: |
| A | window | **9/10** | $0.3046 | 1156 | 0 |
| B | summary | 7/10 | $0.5413 | 538 | 0 |
| C | summary_search | 7/10 | $0.6526 | 635 | **3** |

C 只有 3 次 `memory_search`，7 题没有检索；C−B = 0，B−A / C−A 均为 −0.2。结论是：
**这是一次有效 run，但不是检索的因果实验**。C 的 `memory_search` 指令、gate 和
provider 兼容层共同改变了 treatment，且 gate 仍被 bash 编辑路径绕过。当前不能声称
memory/search 提升 SWE-bench；A（window）在本轮最好。详见
[PILOT_P2FINAL_20261019.md](../experiments/memory_abc_20261019/PILOT_P2FINAL_20261019.md)
和 [comparison](../experiments/memory_abc_20261019/comparison_pilot_p2final.md)。

Sham-search 控制（5 题，同源码/提示/gate，只有返回内容不同）：C-real 4/5、C-sham 4/5，
同一组 11333/14855/15315/8721 通过，11532 都失败；real 成本 $0.1802，sham $0.3599。
没有 real-only 或 sham-only，说明当前 C 在这组题上没有检索收益，但 5 题没有统计功效。
详见 [SHAM_20261019.md](../experiments/memory_abc_20261019/SHAM_20261019.md)。结论是
memory 以负结果收尾，不再跑 50 题 memory 对照；若继续，需要按“证据确实被挤出”选任务并做
10 题 × 2–3 轮 C-real/C-sham。

离线 localization 50 题显示 context selection 的 Recall@5 0.691、Hit@5 0.76，
高于文件级 BM25 的 0.534 / 0.60；5 题 `repo_brief` 的 0.88/1.00 是过拟合，50 题回落到
0.645/0.68。检索在线收益仍未验证；gate 审计显示 5/5 找到官方文件、4/5 编辑、3/5 解决，
瓶颈在检索后的收敛和验证。

当前回归：本机 **690 passed, 18 skipped, 52 deselected**；台式机 checks **419 passed**，
slow gate **9 passed**。新增 `tests/tools/test_retrieval_docker.py` 覆盖 `code_context` 和
`find_references` 的容器路径（slow）。完整报告见
[report_20261019.pdf](../deliverables_final/report_20261019.pdf)。

## 演示顺序

1. 展示 API 提交的仓库、Issue、任务 ID 和状态变化。
2. 展示 events 中一次模型调用、一次工具操作和验收记录。
3. 取消一个执行中的任务，恢复后展示调用数继续累计、工作副本保留。
4. 下载补丁与测试日志；清楚解释 configured tests 和官方 SWE-bench 验收的区别。
5. 展示 comparison 报告、源码指纹以及一个失败案例的证据链。

运行命令见 [deployment/README.md](../deployment/README.md)。后续所有测试和镜像准备均在台式机进行。
