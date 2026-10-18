# 代码检索实现说明

本页说明 `code_search`、`repo_map`、`code_context`、`find_definition`、`find_references` 和
确定性 `repo_brief` 的实现，以及 Docker/Local 一致性、索引缓存、在线归因和离线评测边界。
核心索引在 `src/minisweagent/retrieval/repository.py`；brief 和关系扫描分别放在
`brief.py` / `brief_tool.py` 和 `relations.py`，它们与索引一样不依赖容器内安装包。

## 为什么是自包含文件

`code_search.py` 不假设目标容器里安装了 `mini-swe-agent`。它读取 `repository.py` 的源码，
拼成 `python -c` 脚本在 `LocalEnvironment` 或 `DockerEnvironment` 中执行。因此索引、BM25、
repo map 和上下文组装保持单文件、Python 3.6+ 可解析；brief 与关系扫描则在执行时把各自的
源码和 `repository.py` 一起注入。拆成运行期互相 `import` 的模块会破坏容器内执行路径，除非
额外做打包或安装。

## AST 索引

`SymbolVisitor` 记录：

- `path`、限定名 `name`、`kind`（class/function/method）；
- 起止行、签名、docstring 和源码片段；
- 变量与模块级条目，供 `find_definition` 使用。

索引枚举优先使用 `git ls-files --cached --others --exclude-standard`，因此会包含未跟踪的新
Python 文件、遵守 `.gitignore`；非 git 目录回退到 `os.walk`。语法错误文件、超过 1 MB 的文件、
符号链接逃逸和虚拟环境目录会被跳过，并记录在 `skipped`。

## BM25 与符号/文件分离

符号检索只对 class/function/method 评分，文件检索只对 `<module>` 条目评分。两者分别使用
自己的文档频率和平均长度，避免此前 `<module>` 全文件文档混入“符号级 BM25”的问题。
BM25 参数为 `k1=1.5, b=0.75`，文档由路径、签名、docstring 和源码组成，并对符号名命中加
一个小的二值奖励。

`code_search` 返回 JSON：路径、符号名、类型、行范围、签名、docstring 和原始 BM25 分数。
它不返回代码正文，适合让 Agent 再决定读哪个文件。

## repo_map

- 带 query：按 BM25 符号排名输出 `path:start-end signature`，受 `max_chars` 约束。
- 空 query：使用轻量结构重要性排序。它统计 AST 中 `Load` 上下文的 `Name` 引用（不把参数名、
  属性名当引用），方法继承所属类的引用度，过滤通用名、私有名和测试/文档路径。这不是 Aider
  的引用图 PageRank，只是没有向量依赖的近似。

输出永远不包含 `<module>` 伪符号；空 query 会排除 tests/docs/tutorials/examples 等路径。

## code_context

`code_context` 在文件级与符号级候选之间做 reciprocal-rank fusion，优先产品代码，最多保留一个
测试/文档文件；每个文件最多取两个最具体的符号（类包含方法时保留方法，并补类头），输出签名和
限定行数的片段，受 `max_chars` 和 `snippet_lines` 约束。分数按本次候选的最大值归一化，仅表示
相对排名，不是概率。

`context_files()` 复用同一选择逻辑，供离线评测统计文件命中。

## 索引缓存

大仓库（默认 ≥100 个 Python 文件）的索引会写入
`<tempdir>/minisweagent-index-cache/index-<hash>.json.gz`。缓存键包含真实根路径、索引版本和
所有候选文件的 `mtime/ctime/size` 指纹；文件修改、新增、删除或 `.gitignore` 变化都会使缓存失效。
写入使用临时文件加 `os.replace`，并发读不会看到半个文件。缓存不保存源码正文，命中后按行范围
从工作副本读取片段。

可通过 `MINISWEAGENT_INDEX_CACHE=0` 关闭缓存。一次性离线评测建议关闭，避免把 50 份大索引写进
`/tmp`。

在本机对 Django 浅克隆（2,927 个 Python 文件、46,414 个条目）的测量：冷启动约 9.5 秒（含写缓存），
命中约 0.6–0.7 秒；搜索本身为 40–170 毫秒。容器内的绝对数字会随镜像和 CPU 变化，但“解析远贵于
搜索”的比例不变。

## Docker 与 Local 一致性

`find_definition` 通过 `workspace_root(env)` 取容器工作目录，并用 `ensure_within_workspace`
在环境内执行 `realpath -m` 检查路径边界。SWE-bench 配置把 `cwd` 固定为 `/testbed`；工具不暴露
任意 `root` 参数，因此索引读取的是任务容器里的真实工作副本，而不是宿主机目录。

## Issue-aware 仓库简报（repo_brief）

`repo_brief` 是确定性的、不调用模型的预检索层。`brief.py` 从 issue 文本中保守地抽取：

- 文件路径（含 traceback 中的 `File "...", line N`）；
- 反引号标识符、`def`/`class` 名、qualified name、下划线/CamelCase 标识符；
- 异常名和 `test_*` 名。

随后按“路径/堆栈帧 → 精确符号定义 → BM25/上下文候选”的优先级生成一个受字符预算约束的
brief，包含布局摘要、命中/未命中的 hint、候选文件和建议的第一动作。它只输出位置和签名，不
输出大段源码；源码片段仍由 `code_context` 按需读取。

`brief.py` 不 import `minisweagent`，`brief_tool.py` 会把 `repository.py` 与 `brief.py` 的源码
一起注入容器执行，因此 Docker 和 Local 的行为一致。索引失败时 brief 返回空字符串并 fail open，
不会阻止 Agent 启动。

`DefaultAgent` 的 `retrieval_policy` 有三种取值：

| 值 | 行为 |
| --- | --- |
| `gate` | 旧行为：第一个动作必须是 `code_search`/`repo_map`/`code_context` 之一 |
| `brief` | 不设 gate；在任务文本后注入 `<repository_brief>`，由模型选择下一步 |
| `off` | 不 gate、不注入 brief |

`repo_brief`、`repo_brief_max_chars`、`repo_brief_max_files` 是独立配置项。`retrieval.yaml`
使用 `brief` 策略；`retrieval_gate.yaml` 保留旧 gate 组；`brief_only.yaml` 只开 brief、不开
BM25 工具，用来隔离“预检索上下文”和“工具可用性”。

## 引用与调用关系（find_references）

`find_references` 是一个轻量的关系扫描，不宣称完整的类型解析。它按目标符号过滤文件文本，
只对包含目标字符串的文件做 AST 解析，记录：

- `Call` 的 callee、`Attribute` 读取、`Name` 读取；
- `class ... (Base)` 的基类；
- `import` / `from ... import ...` 的导入名和别名。

结果按 `(path, line, name, owner)` 去重，同一行同时出现 attribute 和 call 时保留 call；输出
定义、引用位置、owner 和一行上下文。它适合回答“改这个符号可能影响谁”，但不是编译器级
引用图；完全限定的动态调用、`getattr` 和跨语言引用可能漏掉。

## 在线轨迹归因

`retrieval_audit.py` 读取保存的 `*.traj.json`，对每题记录：首轮检索查询、top-k 路径、gold
排名、检索后是否读取 gold、是否编辑 gold、分类（`retrieval_miss`、`retrieved_not_read`、
`read_not_edited`、`edited_not_resolved`、`resolved` 等）。它把“检索失败”和“检索成功但
规划/编辑/测试失败”分开。

`experiments/gate-20261017/retrieval_audit.md` 的结果是：5/5 题的 gold 文件进入首轮检索
top-10，5/5 读取了 gold，4/5 编辑了 gold，但只有 3/5 解决。Matplotlib-20826 的 `axis.py`
排第 3，模型也读到了相关代码，但没有形成编辑，50 步耗尽；Django-11532 读取并编辑了
`message.py`，失败来自更大的邮件测试集。因此这组数据的瓶颈不是“检索召回”，而是
“检索后的收敛/编辑/验证”。

## 离线评测

两套用例都只使用官方 `problem_statement` 作为 query，官方补丁中的 `.py` 文件作为 gold：

- `experiments/localization_verified5/`：5 题，代码副本按 base commit 固定；`checkouts/`
  被 gitignore 忽略，使用 `python experiments/localization_verified5/prepare_checkouts.py`
  在新机器上重建并写 `checkouts_manifest.json`；
- `experiments/localization_verified50/`：50 题，提供 `cases.json`，复用五题的冻结抓取脚本
  `python experiments/localization_verified5/prepare_checkouts.py --cases ... --output ...`；
  代码副本不入库，manifest 记录每个副本的 HEAD 与 Python 文件数。

五题结果（当前实现）：

| 方法 | Recall@5 | Hit@5 | MRR |
| --- | ---: | ---: | ---: |
| 文件级 BM25 | 0.54 | 0.80 | 0.50 |
| 符号级 BM25 | 0.34 | 0.60 | 0.63 |
| 上下文选择 | 0.54 | 0.80 | 0.64 |
| 确定性 `repo_brief` | 0.88 | 1.00 | 0.90 |

`repo_brief` 行使用相同的五个 base commit；本机通过
`--checkouts-root experiments/localization_verified50/checkouts` 复用了 50 题副本，结果在
`experiments/localization_verified5/brief_result.json`。它仍然只使用 issue 文本和 AST 索引，
不读取 gold patch。Brief 的优势主要来自路径/堆栈帧解析和“精确符号 → BM25”的优先级；五题
样本仍不足以说明在线解决率提升。

50 题复核（同一套 `verified50_tasks.json`，9 个仓库、50 个 base commit）：

| 方法 | Recall@5 | Hit@5 | MRR |
| --- | ---: | ---: | ---: |
| 文件级 BM25 | 0.534 | 0.60 | 0.467 |
| 符号级 BM25 | 0.531 | 0.60 | 0.437 |
| 上下文选择 | **0.691** | **0.76** | **0.560** |
| 确定性 `repo_brief` | 0.645 | 0.68 | 0.488 |

上下文选择相对文件级 BM25 多命中 11 道题、只在 1 道题上丢失命中。`repo_brief` 在五题
上达到 0.88，但 50 题回落到 0.645，说明“优先相信 issue 中显式路径/符号”的策略会过拟合小样本；
当前更稳的候选生成器是上下文选择，而不是 brief。两者都还没有在线 A/B。

五题样本不足以支持“检索带来解决率提升”的结论。`experiments/pilot_20261017` 中 retrieval 组
从未调用检索工具；`gate-20261017` 强制调用后是 baseline 4/5、retrieval 3/5。这些实验说明
工具可用不等于工具有效，后续应扩大题目、配对重复运行，并单独评估“返回片段”对在线步骤数和
解决率的影响。

## 已知边界

- `find_references` 是文本匹配 + AST 的近似关系扫描，不是 Aider 式跨文件引用图、PageRank
  或类型解析；动态调用、`getattr` 和跨语言引用可能漏掉；
- 没有 tree-sitter 多语言解析和 Token 级二分预算；索引仍是 Python-only；
- 没有 Embedding/向量库；当前五题结果和项目文档都不支持先加这一层；
- 空 query 的结构排序只是引用计数近似，不能替代真正的 repo map；
- `repo_brief` 和 `code_context` 都还没有在线 A/B；离线文件命中不能证明解决率提升；
- gate 组的 treatment 同时包含“工具可用”“提示词”和“强制首步”三个变化，不能单独归因于
  检索质量。新实验使用 `brief` 策略，并用 `retrieval_gate.yaml` / `brief_only.yaml` 分离
  这两个因素。
