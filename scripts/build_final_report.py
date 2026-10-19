"""Build the 2026-10-19 CS427 project report as a DOCX."""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables_final" / "report_20261019.docx"
FONT = "PingFang SC"
MONO = "Menlo"


def set_run_font(run, size: float | None = None, bold: bool | None = None, color=None):
    run.font.name = FONT
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if color is not None:
        run.font.color.rgb = RGBColor(*color)


def body(doc, text: str, *, size: float = 10.5, space_after: float = 5, bold: bool = False):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = 1.25
    r = p.add_run(text)
    set_run_font(r, size=size, bold=bold)
    return p


def bullet(doc, text: str, *, size: float = 10.5):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    set_run_font(r, size=size)
    return p


def heading(doc, text: str, level: int = 1):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12 if level == 1 else 8)
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    set_run_font(r, size=17 if level == 1 else 13, bold=True, color=(0x1F, 0x3B, 0x57))
    return p


def shade(cell, hex_color: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    tc_pr.append(shd)


def table(doc, headers: list[str], rows: list[list[str]], widths: list[float] | None = None):
    table_obj = doc.add_table(rows=1, cols=len(headers))
    table_obj.style = "Table Grid"
    table_obj.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = table_obj.rows[0].cells
    for i, text in enumerate(headers):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        set_run_font(r, size=9, bold=True, color=(0xFF, 0xFF, 0xFF))
        shade(hdr[i], "2F5597")
    for row in rows:
        cells = table_obj.add_row().cells
        for i, text in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER if i else WD_ALIGN_PARAGRAPH.LEFT
            r = p.add_run(str(text))
            set_run_font(r, size=9)
    if widths:
        for row in table_obj.rows:
            for i, width in enumerate(widths):
                row.cells[i].width = Cm(width)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table_obj


def code(doc, text: str):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    p.paragraph_format.line_spacing = 1.0
    r = p.add_run(text)
    r.font.name = MONO
    r._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), MONO)
    r.font.size = Pt(8.5)
    return p


def setup(doc):
    section = doc.sections[0]
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)
    normal.font.size = Pt(10.5)
    normal.paragraph_format.line_spacing = 1.25


def build():
    doc = Document()
    setup(doc)

    # Cover
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(60)
    r = p.add_run("CS427 Coding Agent 项目报告")
    set_run_font(r, size=26, bold=True, color=(0x1F, 0x3B, 0x57))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("基于 mini-swe-agent 的工具、记忆、检索与修复工作流")
    set_run_font(r, size=14, color=(0x44, 0x54, 0x6A))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_before = Pt(20)
    r = p.add_run("2026-10-19 · xiaofei9289")
    set_run_font(r, size=11, color=(0x59, 0x59, 0x59))

    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run("https://github.com/xiaofei9289/2025Fall_CS427_agent")
    set_run_font(r, size=9, color=(0x2F, 0x55, 0x97))

    doc.add_page_break()

    heading(doc, "摘要", 1)
    body(
        doc,
        "本项目在 mini-swe-agent 上扩展了一个面向 GitHub Issue 修复的 Coding Agent："
        "保留“模型输出动作 → 环境执行 → observation”的简单循环，增加文件/检索/测试工具、"
        "可审计的上下文记忆、Python AST 代码检索、证据驱动的修复工作流，以及可取消/恢复的"
        "持久化任务服务。重点不是堆功能，而是把配置、题目、源码快照、轨迹、补丁和官方评分"
        "关联起来，使每次结果都能复核。",
    )
    body(
        doc,
        "结论先行：工程实现和可复现性较强，离线 localization 有明确信号；但 2026-10-19 的 "
        "A/B/C p2final（A 9/10、B 7/10、C 7/10，C 仅 3 次 memory_search，C−B=0）是一次"
        "有效 run，却不是检索的因果实验。当前不能声称 memory/search 提升 SWE-bench；"
        "repair workflow 也还没有在线对照。报告因此把“已验证的工程能力”和“尚未验证的性能"
        "收益”明确分开。四臂工具 ablation 的首轮结果为 8/8/9/9，但 plain retrieval 臂"
        "没有调用任何检索工具，因此同样不能归因于工具效应。",
    )

    heading(doc, "1. 系统设计", 1)
    body(
        doc,
        "系统由六层组成：Agent 循环、工具注册表、记忆策略、代码检索、修复工作流和任务服务。"
        "所有动作仍遵循统一协议：一次只允许一个 bash 或 tool 动作；工具返回 "
        "{output, returncode}；observation 以同样格式回传。这样轨迹可以线性审计，"
        "不同工具不会改变 Agent 的基本控制流。",
    )
    table(
        doc,
        ["模块", "核心实现", "设计目标"],
        [
            ["Agent 循环", "default.py / MemoryAgent / RepairAgent", "统一 action/observation；预算与终止语义"],
            ["工具", "tools/ + 注册表", "容器/本机一致；路径限制、输出上限、错误回传"],
            ["记忆", "memory/history.py、memory/abc/", "完整轨迹保留；摘要 + 可检索历史；预算可审计"],
            ["检索", "retrieval/repository.py 等", "AST 索引、BM25、context、repo_brief、引用扫描"],
            ["修复工作流", "agents/workflow.py、repair/", "LOCALIZE→REPRODUCE→PATCH→VERIFY→FINALIZE"],
            ["服务", "service/ + FastAPI", "任务队列、独立工作副本、取消/恢复、checkpoint"],
        ],
        widths=[3.0, 6.4, 7.2],
    )
    body(
        doc,
        "设计上最重要的三个约束是：目标环境内执行、源码/配置冻结、失败可解释。"
        "检索索引在 /testbed 内执行；实验启动器冻结 src 并校验 digest；预算违规、空补丁、"
        "评测错误、缺失轨迹都会进入报告，而不是被静默丢弃。",
    )

    heading(doc, "2. 工具扩展", 1)
    body(
        doc,
        "工具层覆盖读写、行选择读取、多文件读取、文本搜索、replace、定义查找、代码检索、"
        "引用扫描、测试执行和 TODO。所有容器工具通过 env.execute 执行，并在返回前限制输出"
        "长度；路径操作经过工作区校验。",
    )
    table(
        doc,
        ["工具", "用途", "环境路径", "测试"],
        [
            ["read_file / write_file", "基础读写", "env + host", "单测"],
            ["refined_read_file", "按行/范围/head/tail/around 读取", "env + host", "单测"],
            ["read_many_files", "多文件、单文件行数/总字符预算", "env + host", "单测"],
            ["search_file_content", "文件内文本/正则搜索", "env + host", "单测"],
            ["replace", "精确文本替换", "env + host", "单测"],
            ["find_definition", "AST 精确符号查询", "env + host", "Docker slow"],
            ["code_search / repo_map / code_context", "BM25、仓库地图、预算化片段", "env + host", "Docker slow（新增）"],
            ["find_references", "调用/导入/基类轻量扫描", "env + host", "Docker slow（新增）"],
            ["run_tests", "执行验证命令并记录结果", "env", "单测"],
        ],
        widths=[4.2, 5.4, 2.6, 3.4],
    )
    body(
        doc,
        "仍需补的作业要求是“工具有效性”的正式 ablation：当前证明的是工具可用、"
        "容器兼容和单测覆盖，不是每个工具都能提升解决率。建议按 baseline / file-tools / "
        "retrieval / retrieval+brief 四组做 10 题 × 2 轮，指标包括 resolved、空补丁、"
        "官方文件读取/编辑/验证和成本。",
    )

    heading(doc, "3. 记忆：A/B/C 设计与结果", 1)
    body(
        doc,
        "A/B/C 使用同一模型、10 题、400 步、每题 10 美元和 8000 估算 token 预算：",
    )
    table(
        doc,
        ["Arm", "策略", "超限后", "memory_search"],
        [
            ["A", "window", "丢最旧完整 turn", "无"],
            ["B", "summary", "丢最旧 turn + 证据摘要", "无"],
            ["C", "summary_search", "同 B", "有；另含 C-only 指令与 gate"],
        ],
        widths=[1.4, 3.4, 7.2, 4.6],
    )
    body(
        doc,
        "p2final 是完整 generation + official grading 的有效 run：",
    )
    table(
        doc,
        ["Arm", "Resolved", "Empty", "Cost", "Calls", "Search calls"],
        [
            ["A", "9/10", "1", "$0.3046", "1156", "0"],
            ["B", "7/10", "1", "$0.5413", "538", "0"],
            ["C", "7/10", "0", "$0.6526", "635", "3"],
        ],
        widths=[1.5, 2.2, 2.0, 2.6, 2.4, 3.0],
    )
    bullet(doc, "C 只有 3 次 memory_search；7 道题没有检索。C−B=0，B−A/C−A 均为 −0.2。")
    bullet(doc, "C 的指令、gate 和 provider 兼容层共同改变了 treatment，C−B 不能解释为“检索效应”。")
    bullet(doc, "gate 只拦 replace/write_file 和含 COMPLETE_TASK 的提交；bash 编辑路径仍可绕过。")
    bullet(doc, "历史 50 题 baseline 42/50、memory-on 40/50，成本约 7 倍；单轮方差 37/40/42，2 题差异不可解释。")

    heading(doc, "3.1 Sham-search 控制（2026-10-19）", 2)
    body(
        doc,
        "为把“有用检索”与“只是多了一个工具/提示/gate”分开，增加 C-sham 控制：同名、同 schema、"
        "同描述、同 gate，但 memory_search 始终返回 No matching messages，retrieval_tokens=0。"
        "C-real 与 C-sham 使用同一源码、5 题、同一预算和提示，只有返回内容不同。",
    )
    table(
        doc,
        ["C 变体", "Resolved", "Cost", "Calls", "Search calls"],
        [
            ["real", "4/5", "$0.1802", "185", "5"],
            ["sham", "4/5", "$0.3599", "294", "8"],
        ],
        widths=[2.6, 2.6, 3.0, 2.8, 3.2],
    )
    bullet(doc, "两者解决同一组任务（11333、14855、15315、8721），都失败 11532；没有 real-only 或 sham-only。")
    bullet(doc, "sham 更贵、检索更多，说明无内容时模型会重试/重读；这不是检索有效的证据。")
    bullet(doc, "5 题没有统计功效；只能说明当前 C 在这组题上没有可见收益，不能证明检索普适无效。")
    body(
        doc,
        "因此当前结论是：memory 基础设施可运行、可审计，但没有证明性能收益；A（window）"
        "在本轮最好。sham 控制也没有显示检索收益。若继续研究，需要覆盖 bash 写操作的 gate、"
        "按“证据确实被挤出”选任务、以及 10 题 × 2–3 轮的 C-real/C-sham 对照；"
        "当前不应继续 50 题 memory 实验。",
    )

    heading(doc, "4. 代码检索", 1)
    body(
        doc,
        "检索层使用标准库 AST 构建符号索引，遵守 Git ignore，跳过符号链接、大文件和解析失败"
        "文件；BM25 用于文件和符号排序；repo_map 输出预算化符号清单；code_context 进一步"
        "给出路径、行号、签名和代码片段；repo_brief 从 issue 中抽取路径、堆栈帧和反引号"
        "符号，在任务开始时注入；find_references 做轻量调用/导入/基类扫描。大仓库索引"
        "按根路径和 mtime/ctime/size 指纹缓存，可用环境变量关闭。",
    )
    table(
        doc,
        ["方法（50 题离线）", "Recall@5", "Hit@5", "MRR"],
        [
            ["文件级 BM25", "0.534", "0.60", "0.467"],
            ["符号级 BM25", "0.531", "0.60", "0.437"],
            ["上下文选择", "0.691", "0.76", "0.560"],
            ["repo_brief", "0.645", "0.68", "0.488"],
        ],
        widths=[7.0, 3.2, 3.2, 3.2],
    )
    body(
        doc,
        "5 题 repo_brief 的 0.88/1.00/0.90 在 50 题回落到 0.645/0.68/0.488，是明显的小样本"
        "过拟合。更重要的在线证据来自 gate 审计：5/5 官方文件进入首轮 top-10、5/5 被读取、"
        "4/5 被编辑、3/5 解决。瓶颈是“检索后收敛/编辑/验证”，不是“找不到文件”。"
        "Django 2,927 文件冷启动约 9.4–9.6 秒，缓存命中约 0.6–0.7 秒。",
    )

    heading(doc, "4.1 四臂工具 ablation（2026-10-19，一轮）", 2)
    body(
        doc,
        "同一源码、10 题、2 workers、官方 grading；四臂分别为 baseline、brief、retrieval、gate。",
    )
    table(
        doc,
        ["Arm", "Resolved", "Cost", "Calls", "Retrieval tool calls"],
        [
            ["baseline", "8/10", "$0.1023", "217", "0"],
            ["brief", "8/10", "$0.0806", "201", "0"],
            ["retrieval", "9/10", "$0.0499", "139", "0"],
            ["gate", "9/10", "$0.1014", "268", "10"],
        ],
        widths=[2.4, 2.4, 2.8, 2.6, 4.0],
    )
    bullet(doc, "retrieval 臂没有调用任何 code_search/repo_map/code_context/find_references；9/10 不能归因于检索工具。")
    bullet(doc, "gate 强制调用了 repo_map/code_search，与 retrieval 同为 9/10，但成本约 2 倍、调用 268 vs 139。")
    bullet(doc, "四臂均 10/10 completed，无空补丁、无评分错误；A/B 的 8/10 与 C/D 的 9/10 只差 1 题，单轮不显著。")
    body(
        doc,
        "按预注册规则，工具调用为 0 时停止同一 config 的第二轮；先修工具曝光，或把 gate 明确当作"
        "package treatment。当前不能声称工具提升了解决率。",
    )
    body(
        doc,
        "随后把四个 config 的 step_limit 从 400 降到 250。四臂实际最大调用为 91，"
        "250 不会 binding，因此既有 A/B/D 结果仍成立。给 retrieval 加“首次编辑前至少调用一次"
        "检索工具”的提示后，3 题 smoke 为 2/3、1 次 code_context；10 题 recheck 为 9/10、"
        "2 次 code_context、$0.0730。只有 2/10 题真正用了检索工具，解决数未变，treatment "
        "仍基本未执行。",
    )

    heading(doc, "5. 修复工作流与服务", 1)
    body(
        doc,
        "RepairAgent 在 DefaultAgent 外增加 evidence ledger 和提交门：记录测试运行、diff "
        "指纹、失败 ID 和验证状态；strict 模式下未验证提交会被阻止。run_tests 工具把测试"
        "结果写入结构化 observation；默认 workflow_enabled=false，不改变旧行为。"
        "服务层提供 FastAPI、SQLite 队列、独立 worker/工作副本、取消/恢复、checkpoint 和"
        "候选补丁原子保存。",
    )
    body(
        doc,
        "这部分目前只有单测/台式机 checks 和服务生命周期验证，没有 workflow on/off 的"
        "SWE-bench 对照。它能说明“可以这样组织修复流程”，不能说明“提高了解决率”。"
        "服务端配置测试通过也不等于官方隐藏测试通过。",
    )

    heading(doc, "6. 可复现性与测试", 1)
    bullet(doc, "本机：690 passed, 18 skipped, 52 deselected；Ruff 通过。")
    bullet(doc, "台式机：checks 419 passed, 11 deselected；slow gate 9 passed。")
    bullet(doc, "所有 SWE-bench run 记录 source fingerprint、题目列表、配置和官方评分；实验目录保留历史结果。")
    bullet(doc, "新增 tests/tools/test_retrieval_docker.py，覆盖 code_context / find_references 的容器路径（slow）。")
    code(doc, "pytest -q\npytest -q -m slow\npython scripts/verify_v2_baseline.py")
    body(
        doc,
        "边界：Mac 本机没有 Docker daemon；provider 会出现空/截断响应和原生 DSML 格式；"
        "这些必须在台式机端到端运行中验证。单测全绿不等于官方评分通过。",
    )

    heading(doc, "7. 总体评估", 1)
    table(
        doc,
        ["结论", "证据", "判断"],
        [
            ["平台可复现", "freeze/manifest/audit/官方评分/688 测试", "支持"],
            ["离线检索有信号", "50 题 context selection 0.691 vs 0.534", "支持（仅离线）"],
            ["memory/search 提升解决率", "p2final C−B=0；C 仅 3 次 search；sham 4/5 vs 4/5", "不支持"],
            ["repair 提升解决率", "只有单测/checks", "未验证"],
            ["工具提升效果", "四臂 8/8/9/9；250 recheck 9/10、2 calls", "未验证/不支持"],
        ],
        widths=[5.6, 8.0, 3.2],
    )
    body(
        doc,
        "工程评分应看“可运行、可复现、可解释、边界诚实”；研究评分应看“多轮、held-out、"
        "在线、效应量”。本项目前者强，后者仍弱。当前最有价值的资产是冻结/审计基础设施、"
        "50 题 localization 集和失败归因，而不是某个单轮成绩。",
    )

    heading(doc, "8. 下一步", 1)
    bullet(doc, "P0：最终报告与交付物纳入 p2final 负结果；不再声称 memory/search 提升。")
    bullet(doc, "P0：memory 以负结果收尾；sham 5 题无收益，不再跑 50 题 memory 对照。")
    bullet(doc, "P1：工具组 ablation（10 题 × 2 轮）；没有增益的工具只保留工程价值。")
    bullet(doc, "P1：retrieval 四臂在线 gate（baseline / brief_only / retrieval / retrieval_gate），重点看检索后编辑/验证。")
    bullet(doc, "P1：repair workflow off/on 5–10 题，测 empty patch、verified patch、resolved。")
    bullet(doc, "P2：拆 repository.py（782 行）、把 provider 兼容移到 adapter、统一文档与测试数字。")

    heading(doc, "附录：关键产物", 1)
    table(
        doc,
        ["产物", "位置"],
        [
            ["p2final 报告", "experiments/memory_abc_20261019/PILOT_P2FINAL_20261019.md"],
            ["sham 控制", "experiments/memory_abc_20261019/SHAM_20261019.md"],
            ["A/B/C 对照", "experiments/memory_abc_20261019/comparison_pilot_p2final.md"],
            ["5 题 localization", "experiments/localization_verified5/"],
            ["50 题 localization", "experiments/localization_verified50/"],
            ["四臂工具 ablation", "experiments/ablation5v5_20261018/FOUR_ARM_20261019.md"],
            ["检索归因", "experiments/gate-20261017/retrieval_audit.md"],
            ["检索设计", "docs/retrieval.md"],
            ["服务/部署", "deployment/README.md"],
        ],
        widths=[4.2, 12.0],
    )

    doc.save(OUT)
    print(OUT)


if __name__ == "__main__":
    build()
