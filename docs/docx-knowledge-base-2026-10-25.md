# Office Agent 文档操作知识库（大而全版）

> 项目：office-agent-mvp · 配套 `code.run_python`（python-docx 为主，win32com 增强）
> 日期：2026-10-25
> 定位：Agent 操作 .docx 文档的完整知识储备——样式预设体系、常用需求场景库、
> python-docx 通用函数库、知识充分版提示词。数据体量对标"人工操作 WPS 的常用经验"。

---

## 〇、方案概览

| 项 | 选择 | 说明 |
|---|---|---|
| 文档格式 | `.docx`（Word / WPS 均兼容） | 不接受 `.doc`（旧二进制格式）作为编辑对象，可读取后另存为 docx |
| 主库 | `python-docx` | 项目已安装；读写段落、样式、表格、页边距、字体、行距的主力 |
| 增强库 | `win32com`（可选，仅 Windows + 本机装有 WPS/Word） | 处理 python-docx 覆盖不到的高级能力：域、修订/批注、样式继承、目录更新、页面背景等，通过 COM 调用 `KWPS.Application`（WPS 文字）或 `Word.Application` |
| 辅助库 | `pypdf`（已装）、`openpyxl`（已装） | 跨格式读取（PDF 提取内容、xlsx 汇总），供加工后回写 docx |
| 执行通道 | 项目既有 `code.run_python` | 受控目录执行；`$OA_INPUT_DIR` 读素材（目录）、`$OA_OUTPUT_DIR` 写产物，执行完自动登记为产物 |

**能力定位**：Agent 不直接改文档，而是「读文档 → 生成最小改动脚本 → 交给 `code.run_python` 执行 → 回读校验 → 报告改动」。

**文档修改原则（总纲，高于一切具体规则）**：
1. **最小改动**：只改用户点名的范围，未点名的段落、样式、页眉页脚、图片一律不动。
2. **先读后改**：任何修改前先完整读取文档结构与现状，输出「将改动清单」再执行。
3. **留备份**：修改前把原文件复制为 `<name>_备份_<时间戳>.docx`（放 `$OA_OUTPUT_DIR`，不覆盖原件）。
4. **格式跟随**：若文档已有自己的字体/间距体系，以文档现状为准，仅修正不一致处；不强行套用默认值。
5. **不编造内容**：插入的数据/文字必须有来源（用户提供或读取自素材），不得臆造。
6. **可回滚**：脚本结束打印改动摘要（改了哪些段落/样式/表格），供用户核对。

---

## 一、样式预设体系

> 对应常见排版工具里的「页面 / 字体 / 行距」等设置项，全部预设为常量，
> Agent 按场景选用，不每次现场发挥。默认值 = 通用中文办公文档；公文 = GB/T 9704。

### 1.1 页面预设

| 预设名 | 纸张 | 页边距（上/下/左/右 cm） | 适用 |
|---|---|---|---|
| word 默认 | A4 | 2.54 / 2.54 / 3.18 / 3.18 | 通用 |
| 紧凑 | A4 | 2.0 / 2.0 / 2.0 / 2.0 | 资料、说明书 |
| 公文 | A4 | 3.7 / 3.5 / 2.8 / 2.6 | 党政机关公文 |
| 论文 | A4 | 2.5 / 2.5 / 3.0 / 3.0 | 毕业论文、期刊 |
| 简历 | A4 | 1.5 / 1.5 / 2.0 / 2.0 | 简历、报名表 |
| 信函 | A4 | 2.54 / 2.54 / 3.0 / 3.0 | 函件、合同 |

页眉页脚规则：保留原件；新建文档默认页眉空、页脚居中页码（正文首起）；不擅自加横线。

### 1.2 字体预设（中文 / 西文 / 字号）

| 元素 | 中文字体 | 西文数字 | 字号 | 备注 |
|---|---|---|---|---|
| 正文 | 宋体 | Times New Roman | 小四 12pt | 通用 |
| 正文（公文） | 仿宋_GB2312 | Times New Roman | 三号 16pt | GB/T 9704 |
| 正文（简历/PPT） | 微软雅黑 | Segoe UI | 11pt | 商务现代 |
| 一级标题 | 黑体 | Arial | 三号 16pt | 通用 |
| 一级标题（公文） | 黑体 | Arial | 二号 22pt | 标题居中 |
| 二级标题 | 黑体 | Arial | 四号 14pt | 通用 |
| 三级标题 | 宋体 | Times New Roman | 四号 14pt 加粗 | 通用 |
| 表格内容 | 宋体 | Times New Roman | 五号 10.5pt | 通用 |
| 注释/脚注 | 宋体 | Times New Roman | 小五 9pt | 通用 |

**中文字距**（对应截图「字体：中文字距」项，字符间距 `w:spacing`）：
- 标准：0（默认）
- 加宽：+2pt（标题强调、封面）
- 紧缩：-0.5pt（密集排版、表格内）
- 公文标题：可加宽 1pt 增强庄重感

**强制规则**：中文字体必须同时写 `w:eastAsia`；西文数字走 Times New Roman/与正文一致；
强调只用加粗；全文默认黑色。

### 1.3 标题层级与编号预设

| 层级 | 样式 | 字体/字号 | 编号样式 |
|---|---|---|---|
| 一 | Heading 1 | 黑体 16pt(公文 22pt 居中) | 一、二、三、… |
| 二 | Heading 2 | 黑体 14pt | （一）（二）（三）… |
| 三 | Heading 3 | 宋体 14pt 加粗 | 1. 2. 3. … |
| 四 | Heading 4 | 宋体 12pt 加粗 | （1）（2）（3）… |

编号用多级列表自动编号，禁止手敲。

### 1.4 行距预设

| 预设名 | 值 | 适用 |
|---|---|---|
| 单倍 | line_spacing=1.0 | 表格、清单、图注 |
| 1.5 倍 | 1.5 | 通用正文（默认） |
| 2 倍 | 2.0 | 学生作业、批改留白 |
| 固定 22pt | Pt(22) | 简历紧凑 |
| 固定 28pt | Pt(28) | 公文正文 |

### 1.5 段落预设

- 缩进：正文首行 2 字符（小四=24pt，公文三号=32pt）；列表用悬挂缩进。
- 对齐：正文两端对齐；标题左对齐或居中（按场景）；表格文字居中或左对齐。
- 段前段后：正文 0/0；标题 6pt/6pt；图表题注 6pt/12pt。
- 禁止用连续空段落制造间距（用段前段后控制）。

### 1.6 表格预设

| 类型 | 框线 | 表头 | 字号 | 适用 |
|---|---|---|---|---|
| 三线表 | 顶/栏目/底线 1.5pt | 加粗 | 五号 | 报告、论文 |
| 全框线 | 全边框 0.5pt | 加粗+浅灰底 | 五号 | 台账、清单 |
| 网格表 | 全框线+列宽均分 | 加粗 | 五号 | 报名表、登记表 |

表格前后各留 1 个空段（单倍行距）；列宽显式设置，禁止单元格文字失控换行。

### 1.7 列表与编号

- 有序：1. 2. 3.（正文）；一、（一）1.（标题下内容）
- 无序：· 或 –（统一一种，不混用）
- 多级列表用 Word 内置 List Number / List Bullet 样式链，禁止手敲序号。

### 1.8 图片与对象约定

- 图片保持原尺寸/原位置；需要调整时**等比缩放**，禁止拉伸变形（`width`/`height` 同比例改）。
- 图片默认居中，下方附图注「图 1 …」（五号加粗，段前 6pt 段后 12pt）。
- 文本框、形状、嵌入对象（Excel 表、公式）保留原状，不移动、不重排，除非用户点名。
- 图注编号随章节递增（图 1-1、图 1-2…），与表注编号体系（表 1-1…）分离。
- 图片无法用 python-docx 精确定位时，标注建议位置并交由 WPS/Word 手动微调，不硬排。

### 1.9 页眉页脚与页码约定

- 默认保留原件页眉页脚；用户要求新建时才设置。
- 新建页码：页脚居中，正文从第 1 页起（首页不同可关闭）；封面/目录页不计页码。
- 公文：页码「— 1 —」形式（宋体 4 号数字），单页右、双页左。
- 页眉内容：默认空或「文档标题」；不加横线，除非文档已有该风格。

---

## 二、常用需求场景库（40+ 场景，按类路由）

> Agent 收到需求后先归入场景，再套用「样式预设 + 操作要点」。括号内为典型触发词。

### A. 通用文档处理
1. **新建空白文档**（新建/写一份/起草）→ 默认样式预设（A4、正文宋体小四、1.5 倍行距、首行缩进 2 字符）。
2. **全文排版整理**（排版/整理格式/统一格式）→ 全文扫 Normal 段落应用正文预设、标题应用 Heading、表格应用三线表。
3. **格式统一**（格式不统一/有的粗有的细）→ 遍历 runs 清除手写格式，统一字体字号。
4. **改写润色**（改写/润色/优化表达）→ 保留段落与样式，只换文字，语言风格贴近原文，不改变事实。
5. **校对纠错**（校对/错别字/标点）→ 只改错字与明显标点，不动措辞，输出改动清单。
6. **压缩篇幅**（删减/精简/缩到 X 页）→ 优先删冗余句、合并重复段，保留标题层级与结论。
7. **合并文档**（合并/合成一份）→ 多 docx 顺序合并，统一样式预设，标题接续编号。
8. **拆分文档**（拆分/按章拆开）→ 按一级标题拆多文件，命名「文档名_第X章.docx」。
9. **转 PDF**（转 PDF）→ win32com 导出或 LibreOffice 转换；保留原 docx 不动。
10. **批量替换**（替换/把 A 改成 B）→ 逐段文本替换，保留原 run 格式；支持正则（明确时）。

### B. 职场文书
11. **通知**（发通知/通知文件）→ 标题黑体居中 + 正文宋体小四 + 落款单位/日期右对齐。
12. **函件/便函**（函/致函/复函）→ 称呼顶格、正文首行缩进、落款右对齐。
13. **请示/报告**（请示/汇报/报告）→ 一文一事；标题 + 缘由 + 事项 + 结语「妥否，请批示」。
14. **会议纪要**（纪要/会议记录）→ 标题 + 时间地点主持出席 + 议题逐条（编号）+ 决议加粗或【决议】标记。
15. **工作周报/日报**（周报/日报/工作汇报）→ 表格式或条目式：本周完成/下周计划/问题风险。
16. **述职报告**（述职）→ 引言 + 履职情况（分条）+ 不足 + 改进计划。
17. **工作计划/总结**（计划/总结）→ 目标 + 分项任务（编号）+ 时间节点；总结加「成效/不足/展望」。
18. **规章制度**（制度/管理办法/细则）→ 章条式：第一章…第一条…；标题黑体、条文宋体小四。
19. **公告/通告**（公告/通告）→ 标题居中 + 正文 + 发布日期。
20. **声明/澄清**（声明/辟谣）→ 标题 + 主体 + 生效说明 + 落款。

### C. 学术与教学
21. **论文排版**（论文/毕设）→ 论文预设（A4 2.5/2.5/3/3）；摘要、关键词、正文、参考文献章节；标题四级；自动目录。
22. **作业排版**（作业/答卷）→ 页眉「课程-姓名-学号」；题号编号；2 倍行距留批改空间。
23. **教案**（教案/教学设计）→ 教学目标/重难点/过程（导入-新授-练习-小结）/板书/作业，条目式。
24. **试卷排版**（试卷/出题）→ 卷头（学校/科目/时长/满分）+ 大题型标题 + 小题编号 + 密封线说明；字号五号紧凑。
25. **开题报告**（开题）→ 选题背景/研究现状/研究内容/方法/进度表（表格）。
26. **参考文献整理**（参考文献/引用）→ GB/T 7714 顺序编号 [1]…，作者/题名/刊名/年卷期页，统一格式。

### D. 商务与合同
27. **合同/协议**（合同/协议/条款）→ 合同预设；标题 + 双方信息 + 条款编号 + 签署栏；金额大写与小写一致。
28. **报价单**（报价/报价单）→ 表格：序号/项目/规格/单价/数量/小计/总计；表头加粗。
29. **标书**（标书/投标）→ 封面 + 目录 + 商务/技术/报价三部分；页码规范；目录自动生成。
30. **方案/策划案**（方案/策划/计划书）→ 背景/目标/方案/执行/预算/风险；标题层级 + 表格预算。
31. **商业计划书**（商业计划书/BP）→ 摘要 + 市场/产品/团队/财务/融资，图表化数据表格。
32. **介绍信/委托书**（介绍信/委托书）→ 称呼 + 事项 + 期限 + 单位盖章栏。

### E. 个人事务
33. **简历**（简历/CV）→ 简历预设；个人信息 + 教育经历 + 工作/项目 + 技能 + 自我评价；一页优先。
34. **求职信/辞职信**（求职信/辞职信）→ 称呼 + 正文 + 落款；辞职信需致谢与交接说明。
35. **申请书**（申请书/入党申请/入团申请）→ 称谓 + 申请事项 + 理由 + 表态 + 落款。
36. **各类证明**（证明/在职证明/收入证明）→ 标题居中 + 正文「兹证明…」+ 单位盖章栏 + 日期。
37. **贺词/致辞/发言稿**（贺词/致辞/发言稿）→ 称谓顶格 + 开场 + 分条 + 结语；口语化、有节奏。
38. **检讨书/感谢信/邀请函**（检讨/感谢信/邀请函）→ 按对应格式：称谓、正文、敬语、落款。
39. **请假条/假条**（请假条）→ 称谓 + 请假事由时长 + 敬请批准 + 落款日期。

### F. 营销与宣传
40. **公众号文章 docx 版**（公众号/推文）→ 标题 + 小标题层级 + 段落短、留白多；可加分隔符。
41. **新闻稿**（新闻稿/宣传稿）→ 导语（5W）+ 正文 + 结尾背景；标题醒目、正文宋体小四。
42. **宣传单/海报文案**（宣传单/海报文案）→ 主标语 + 卖点条目 + 行动号召 + 联系方式。
43. **产品介绍**（产品介绍/说明书）→ 概述 + 功能特性（编号）+ 参数表 + 使用说明。

### G. 批量与自动化
44. **批量套模板**（套模板/批量生成）→ 读取模板 docx，按数据（xlsx/csv）逐条复制模板并替换占位符，产物按条目命名。
45. **批量改格式**（全部改成/统一改成）→ 遍历目录所有 docx，统一字体/行距/页边距，输出改动统计。
46. **批量插页眉/页码**（每份都加/统一加页眉）→ 遍历设置 sections.header 与页码域。
47. **按模板合并导出**（汇总/合并导出）→ 多数据 → 多份文档或一份汇总表。
48. **文档审计报告**（统计/有多少页/字数）→ 输出字数、段落、表格、页数清单（只读不改）。

---

## 三、python-docx 通用函数库（Agent 直接套用）

```python
# -*- coding: utf-8 -*-
"""docx_utils.py —— Office Agent 文档操作通用函数库"""
import os, re, shutil, datetime
from docx import Document
from docx.shared import Pt, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

# ---------- 样式预设常量（按需选用，勿现场发挥） ----------
PAGE_DEFAULT = dict(width=Cm(21.0), height=Cm(29.7),
                    top=Cm(2.54), bottom=Cm(2.54), left=Cm(3.18), right=Cm(3.18))
PAGE_GONGWEN = dict(width=Cm(21.0), height=Cm(29.7),
                    top=Cm(3.7), bottom=Cm(3.5), left=Cm(2.8), right=Cm(2.6))
FONT_BODY = ("宋体", "Times New Roman", 12)      # 正文 小四
FONT_BODY_GW = ("仿宋_GB2312", "Times New Roman", 16)  # 公文正文 三号
FONT_H1 = ("黑体", "Arial", 16)                  # 一级标题
FONT_H2 = ("黑体", "Arial", 14)                  # 二级标题
FONT_H3 = ("宋体", "Times New Roman", 14)        # 三级标题（加粗）
FONT_TABLE = ("宋体", "Times New Roman", 10.5)   # 表格 五号

def _set_font(run, cn="宋体", en="Times New Roman", size=12, bold=False, spacing=None):
    """设置 run 字体：中文字体必须写 eastAsia；spacing=字符间距(pt)"""
    run.font.name = en
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = None  # 保持黑色
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = rPr.makeelement(qn("w:rFonts"), {}); rPr.append(rFonts)
    rFonts.set(qn("w:eastAsia"), cn)
    if spacing is not None:
        rPr.set(qn("w:spacing"), str(int(spacing * 20)))  # 半磅单位

def set_para(p, line=1.5, indent_pt=24, before=0, after=0,
             align=WD_ALIGN_PARAGRAPH.JUSTIFY, hanging=False):
    """段落格式：line=倍行距或 Pt 固定值；indent_pt=首行缩进(pt)，0 则无"""
    pf = p.paragraph_format
    pf.line_spacing = line if isinstance(line, float) else line
    if indent_pt:
        pf.first_line_indent = Pt(indent_pt)
    if hanging:
        pf.first_line_indent = Pt(-indent_pt)
        pf.left_indent = Pt(indent_pt)
    pf.space_before = Pt(before); pf.space_after = Pt(after)
    pf.alignment = align

def apply_body(doc, cn=FONT_BODY[0], en=FONT_BODY[1], size=FONT_BODY[2],
               line=1.5, indent_pt=None):
    """全文 Normal 段落套用正文格式（indent_pt 默认=2 字符）"""
    if indent_pt is None: indent_pt = size * 2
    for p in doc.paragraphs:
        if p.style.name != "Normal" or not p.text.strip(): continue
        set_para(p, line=line, indent_pt=indent_pt)
        for r in p.runs: _set_font(r, cn, en, size)

def apply_headings(doc, mapping=None):
    """标题样式表：{'Heading 1':('黑体','Arial',16,True), ...}"""
    mapping = mapping or {
        "Heading 1": ("黑体", "Arial", 16, True),
        "Heading 2": ("黑体", "Arial", 14, True),
        "Heading 3": ("宋体", "Times New Roman", 14, True),
    }
    for name, (cn, en, size, bold) in mapping.items():
        st = doc.styles[name]
        st.font.name = en; st.font.size = Pt(size); st.font.bold = bold
        st.element.rPr.rFonts.set(qn("w:eastAsia"), cn)

def set_page(doc, spec=None):
    """页边距/纸张：spec 用 PAGE_DEFAULT 或 PAGE_GONGWEN 常量"""
    spec = spec or PAGE_DEFAULT
    for sec in doc.sections:
        sec.page_width = spec["width"]; sec.page_height = spec["height"]
        sec.top_margin = spec["top"]; sec.bottom_margin = spec["bottom"]
        sec.left_margin = spec["left"]; sec.right_margin = spec["right"]

def add_table_simple(doc, header, rows, style="triple"):
    """表格：style=triple 三线表 / grid 全框线"""
    t = doc.add_table(rows=len(rows) + 1, cols=len(header))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    if style == "grid":
        t.style = doc.styles["Table Grid"]
    for j, h in enumerate(header):
        cell = t.rows[0].cells[j]; cell.text = str(h)
        for r in cell.paragraphs[0].runs: _set_font(r, *FONT_TABLE, bold=True)
    for i, row in enumerate(rows, 1):
        for j, v in enumerate(row):
            cell = t.rows[i].cells[j]; cell.text = str(v)
            for r in cell.paragraphs[0].runs: _set_font(r, *FONT_TABLE)
    if style == "triple":  # 三线表：清边框，仅顶/栏目/底线
        tbl = t._tbl; tblPr = tbl.tblPr
        borders = tblPr.makeelement(qn("w:tblBorders"), {})
        for edge, sz in (("top", 12), ("bottom", 12), ("insideH", 0)):
            el = borders.makeelement(qn(f"w:{edge}"), {
                qn("w:val"): "single", qn("w:sz"): str(sz), qn("w:color"): "000000"})
            borders.append(el)
        tblPr.append(borders)
        # 栏目线（表头下）加粗
        for c in t.rows[0].cells:
            for p in c.paragraphs:
                pPr = p._p.get_or_add_pPr()
                pBdr = pPr.makeelement(qn("w:pBdr"), {})
                b = pBdr.makeelement(qn("w:bottom"), {
                    qn("w:val"): "single", qn("w:sz"): "8", qn("w:color"): "000000"})
                pBdr.append(b); pPr.append(pBdr)
    return t

def replace_text(doc, old, new):
    """全文替换并保留格式（old 为空段时跳过）"""
    n = 0
    for p in doc.paragraphs:
        for r in p.runs:
            if old in r.text:
                r.text = r.text.replace(old, new); n += 1
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    for r in p.runs:
                        if old in r.text:
                            r.text = r.text.replace(old, new); n += 1
    return n

def backup(src, out_dir):
    """修改前备份原件：<名>_备份_<时间戳>.docx"""
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name, ext = os.path.splitext(os.path.basename(src))
    bak = os.path.join(out_dir, f"{name}_备份_{ts}{ext}")
    shutil.copy2(src, bak)
    return bak

def read_report(doc):
    """只读审计：段落/表格/字符统计"""
    paras = len(doc.paragraphs)
    chars = sum(len(p.text) for p in doc.paragraphs)
    tables = len(doc.tables)
    return dict(paragraphs=paras, chars=chars, tables=tables)
```

**典型脚本骨架（Agent 每次生成时套用）**：

```python
# -*- coding: utf-8 -*-
import os
from docx import Document
from docx_utils import *   # 引入上方函数库（同目录）

SRC = os.path.join(os.environ["OA_INPUT_DIR"], "素材.docx")   # 目录；OA_INPUTS 是 JSON 清单
OUT = os.path.join(os.environ["OA_OUTPUT_DIR"], "产物.docx")
bak = backup(SRC, os.environ["OA_OUTPUT_DIR"])

doc = Document(SRC)
set_page(doc, PAGE_DEFAULT)          # 1 页面
apply_body(doc, line=1.5)            # 2 正文（宋体小四 1.5 倍行距 缩进2字符）
apply_headings(doc)                  # 3 标题层级
# ……按场景补充：表格/替换/新增段落……
doc.save(OUT)
print("备份:", bak); print("产物:", OUT)
```

---

## 四、Agent 提示词（知识充分版，可直接放入 system prompt）

```text
你是办公文档操作 Agent，用 Python 脚本操作 .docx 文档（Word / WPS 兼容），
目标：像资深文员操作 WPS 一样规范、专业、可预期地完成读、改、排版、批量整理。

【执行通道】
- 只生成 Python 脚本，交给 code.run_python 在受控目录执行；素材从 $OA_INPUT_DIR 读
  （目录，已按原文件名复制好；$OA_INPUTS 是 JSON 清单，不能当目录拼路径），
  产物写 $OA_OUTPUT_DIR，执行完自动登记为产物。
- 主库 python-docx；python-docx 覆盖不了的（域、修订、批注、目录更新、样式继承、转 PDF）
  且本机为 Windows + 装有 WPS/Word 时，用 win32com 调 KWPS.Application / Word.Application。
- 优先复用项目已有 docx_utils 函数库（set_page/apply_body/apply_headings/add_table_simple
  /replace_text/backup），不要每次重新发明；库不满足时再写专项代码。

【样式预设体系】（有用户要求或文档自身格式时，以用户与文档现状为准）
- 页面：A4；页边距默认 2.54/2.54/3.18/3.18，公文 3.7/3.5/2.8/2.6；保留原页眉页脚。
- 字体：正文宋体+西文 Times New Roman 小四 12pt；一级标题黑体三号 16pt；二级黑体四号 14pt；
  三级宋体四号加粗；表格五号 10.5pt；公文正文仿宋_GB2312 三号。
- 中文字体必须写 w:eastAsia；字符间距：标准 0/标题加宽 ≤2pt/表格可紧缩。
- 行距：正文 1.5 倍（公文固定 28pt）；表格与图注单倍；作业可 2 倍。
- 段落：正文首行缩进 2 字符（小四=24pt，三号=32pt）；段前段后 0；两端对齐。
- 标题用内置 Heading 样式（可生成目录），编号用多级列表，禁止手敲编号。
- 表格：报告论文用三线表，台账清单用全框线，登记表用网格表；表头加粗。
- 强调只用加粗，不用下划线/彩色；全文默认黑色；图片等比缩放不拉伸。

【常用需求路由】（收到需求先归类，再套预设与操作要点）
- 通用：新建/排版整理/格式统一/改写润色/校对纠错/压缩篇幅/合并拆分/批量替换/转 PDF。
- 职场：通知/函件/请示报告/会议纪要/周报日报/述职/计划总结/制度/公告/声明。
- 学术教学：论文/作业/教案/试卷/开题报告/参考文献(GB/T 7714)。
- 商务合同：合同/报价单/标书/方案/商业计划书/介绍信/委托书。
- 个人：简历/求职信/辞职信/申请书/证明/贺词致辞/检讨/感谢信/邀请函/请假条。
- 营销：公众号推文/新闻稿/宣传文案/产品介绍。
- 批量：套模板批量生成/批量改格式/批量插页眉页码/合并导出/文档审计(只读统计)。
每类场景的标题结构、称呼、落款、表格要求见项目文档 docx-knowledge-base。

【执行流程（必须按序）】
1. 读取：先完整读取文档结构与现状（段落/标题/表格/样式），确认对象与范围；
   模糊或越权处先问用户，不猜测、不扩大范围。
2. 计划：给出最小改动清单（改哪段/哪样式/改成什么）并获确认。
3. 备份：执行前 backup() 复制原件为 <名>_备份_<时间戳>.docx，绝不覆盖原件。
4. 改稿：一次脚本完成全部改动；样式用常量与 docx_utils，不写死魔法值。
5. 校验：回读产物逐项核对（字号/行距/缩进/标题层级/表格列宽/页码页数/替换次数），
   不符就地修脚本重跑，直到通过；替换类输出替换次数。
6. 报告：改动内容、遵循的预设、产物路径、备份路径、未实现项。

【安全与边界】
- 只操作 $OA_INPUT_DIR / $OA_OUTPUT_DIR 内文件；不触碰其他路径、不连网下载。
- 数据必须有来源（用户提供或读取自素材），不得编造；字数/页数/条目实数核对。
- utf-8 编码；文件名语义化中文名。
- 能力外（.doc 旧格式/损坏/加密/扫描件）如实说明，不假装成功；扫描件需先 OCR。
```

---

## 五、实施建议（接现有项目）

1. `docx_utils.py` 放 `backend/app/services/docx_utils.py`，被 `code.run_python` 的执行目录预置导入。
2. 提示词写入 Agent system prompt 或文档工具 tool description；样式常量集中一处，不散落。
3. smoke 用例：样例 `data/samples/meeting_notes.docx` 跑「统一正文+重排标题+三线表+替换」，
   断言字号 12pt、行距 1.5、表头加粗、替换次数正确。
4. 场景库随版本扩充：新增需求先补「场景库 + 操作要点」，再补 smoke，保持知识库同步。

---

## 六、python-docx 操作细节与常见坑（写脚本必备）

### 6.1 高频操作代码

```python
# -*- coding: utf-8 -*-
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_BREAK, WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# 分页符
# doc.add_page_break()                     # 段落后新起一页
# run.add_break(WD_BREAK.PAGE)             # run 内插入分页

# 分节符（新起一节）
# sec = doc.add_section(WD_SECTION.NEW_PAGE)  # 之后 sec.top_margin=... 独立设置

# 页脚页码域（正文第 1 页起）
def add_page_number(section, align="center"):
    p = section.footer.paragraphs[0]
    p.alignment = {"center": WD_ALIGN_PARAGRAPH.CENTER,
                   "right": WD_ALIGN_PARAGRAPH.RIGHT}[align]
    run = p.add_run()
    f1 = OxmlElement("w:fldChar"); f1.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = "PAGE"
    f2 = OxmlElement("w:fldChar"); f2.set(qn("w:fldCharType"), "end")
    run._r.append(f1); run._r.append(it); run._r.append(f2)

# 上标 / 下标
# run.font.superscript = True
# run.font.subscript = True

# 表格表头跨页重复
def repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    th = OxmlElement("w:tblHeader"); th.set(qn("w:val"), "true")
    trPr.append(th)

# 合并单元格
# a = table.cell(0, 0); b = table.cell(0, 1); a.merge(b)

# 单元格底纹（表头浅灰）
def shade_cell(cell, fill="EEF1F6"):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd"); shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill); tcPr.append(shd)

# 文档元数据
# doc.core_properties.title = "标题"
# doc.core_properties.author = "作者"
# doc.core_properties.keywords = "关键词"
# doc.core_properties.comments = "说明"
```

### 6.2 目录（TOC）

- python-docx **无法计算/更新目录页码**，只能插入 TOC 域；文档在 WPS/Word 打开后按 F9 或「更新域」才显示。
- 需要自动更新：用 win32com 打开 → `doc.TablesOfContents.Item(1).Update()` → 关闭，再交付。
- 提示词规则：涉及「目录」需求时，默认走 win32com 更新，并在报告里说明「目录已更新」；否则如实标注「需打开后更新域」。

### 6.3 超链接

- python-docx 无原生超链接 API，需手工构造 `w:hyperlink`（含 `w:rStyle` 与关系 id），或直接用 win32com：`sel.Hyperlinks.Add(sel.Range, Address, SubAddress, ..., TextToDisplay)`。
- 简化约定：普通链接需求优先 win32com；仅插入且不要求可点击时，可写成普通文本并附 URL。

### 6.4 常见坑（按踩坑频率排序）

| # | 坑 | 后果 | 规避 |
|---|---|---|---|
| 1 | 中文字体只设 `font.name` 不写 `w:eastAsia` | 中文仍显示默认字体 | 一律用 `_set_font`（已处理 eastAsia） |
| 2 | 直接 `style.font.size=` 只影响「之后」应用该样式的段落 | 已有正文不变 | 对既有文档遍历段落逐 run 设格式（`apply_body`） |
| 3 | `run.text = new` 整体赋值 | 丢掉 run 内混合格式（斜体/颜色） | 用 `replace_text` 分段替换，或按需重建 run |
| 4 | `cell.text = "x"` | 清空单元格已有段落格式、只留一个新 run | 想保留格式时操作 `cell.paragraphs[0].runs` |
| 5 | 忘记处理多个 section | 只改了第一节，后面分节页边距没变 | `for sec in doc.sections` 全部设置 |
| 6 | 表格无边框样式 | 三线表/全框线需显式设边框 | 用 `add_table_simple`（triple/grid） |
| 7 | 样式名 `Table Grid` 等在当前模板不存在 | `KeyError` 崩脚本 | try/except 回退到手工设边框 |
| 8 | 空段落参与遍历 | 误把空段当内容、误设格式 | `if not p.text.strip(): continue` |
| 9 | `doc.save(原路径)` | 覆盖原件且无备份 | 修改前必 `backup()`，产物存 `$OA_OUTPUT_DIR` |
| 10 | 加密/受保护文档 | python-docx 直接抛错 | 捕获异常并如实提示，不假装成功 |
| 11 | 超长文档整篇遍历 | 脚本慢（分钟级） | 只遍历目标样式/区域；大批量按章分块处理 |
| 12 | `add_picture` 传了过期 URL | IOError | 图片先下载到本地再插入（素材来自 `$OA_INPUT_DIR`） |

### 6.5 与 win32com 的边界（何时放弃 python-docx）

| 能力 | python-docx | win32com(WPS/Word) |
|---|---|---|
| 读写正文/样式/表格/页边距 | ✅ | ✅ |
| 中文 eastAsia 字体 | ✅（需手动） | ✅ |
| 目录更新、页码刷新 | ❌ | ✅ |
| 域（PAGE/DATE/REF…） | 仅插入不计算 | ✅ 全量 |
| 修订（Track Changes）、批注 | ❌ | ✅ |
| 转 PDF、另存格式 | ❌ | ✅ |
| 页眉页脚奇偶页、首页不同 | 部分 | ✅ |
| 红头文件、印章位等复杂版式 | 难 | ✅ |

规则：**python-docx 能解决的不用 COM**；涉及上表右侧能力时再用 win32com，且调用后必须正常 `Quit()` 释放进程。

---

## 七、校验与验收清单（交付前逐项核对）

> Agent 在「回读校验」步骤按此表逐项打勾；不满足项不得标记完成。

| # | 检查项 | 核对方法 |
|---|---|---|
| 1 | 文件可正常打开、无损坏 | `Document(OUT)` 不抛错；页数估算（`section`×分页符或 COM `ComputeStatistics`) |
| 2 | 字数/段落/表格数与预期一致 | `read_report()`；用户点名数字逐项实数核对 |
| 3 | 正文：字号 12pt、西文 TNR、中文字体宋体 | 抽查前 3 段 + 中间 1 段 + 末段 run 属性 |
| 4 | 行距 1.5 倍、首行缩进 2 字符、两端对齐 | `paragraph_format` 抽查 |
| 5 | 标题层级 Heading 1-3、编号连续无缺号 | 遍历 styles 名 + 列表编号检查 |
| 6 | 表格：框线类型正确、表头加粗、列宽未失控 | 抽查每个表格首行/边框 |
| 7 | 页眉页脚保留原件；新增页码存在且格式对 | 检查 sections.footer/header |
| 8 | 图片未变形、未丢图 | 抽查 images 计数与宽高比 |
| 9 | 替换类任务：替换次数 > 0 且无残留 | `replace_text` 返回计数；grep 旧串 |
| 10 | 备份文件存在且内容为原件 | `backup()` 返回值存在；大小与原件一致 |
| 11 | 无乱码（中文/西文） | 抽查特殊段落（标题、表格、页眉） |
| 12 | 文件名语义化、产物在 `$OA_OUTPUT_DIR` | 路径检查 |

---

## 八、异常与边界处理

| 场景 | 表现 | Agent 处理 |
|---|---|---|
| `.doc` 旧格式 | python-docx 无法打开 | 如实说明；建议先用 WPS/Word 另存为 docx，或用 win32com 读取转换 |
| 加密/密码文档 | 抛错 | 请用户提供密码；无密码则拒绝并说明 |
| 损坏/截断文件 | 解析异常 | 报告具体错误，不修复、不编造内容 |
| 扫描件 PDF | pypdf 提取无文字 | 说明需先 OCR（本地 OCR 引擎）再进 docx |
| 超大文档（>10MB/千段） | 脚本慢 | 分块处理、只动目标区域；告知耗时预期 |
| 字体缺失 | WPS 打开自动替换字体 | 提示所用字体需本机安装（如仿宋_GB2312） |
| 图片无法定位 | 位置偏移 | 标注建议位置，交人工微调，不硬排 |
| 需求越权（删改未点名内容） | — | 拒绝并请用户确认范围（最小改动原则） |

---

## 九、党政公文版式速查（GB/T 9704，用户点名公文时启用）

| 元素 | 规范 |
|---|---|
| 版头 | 发文机关标志红色（小标宋体），发文字号（如「×办发〔2026〕5 号」）3 号仿宋，签发人，红色分隔线 |
| 标题 | 2 号小标宋体字，居中，回行时词意完整、排列对称 |
| 主送机关 | 3 号仿宋，顶格，末尾用冒号 |
| 正文 | 3 号仿宋；一级标题黑体、二级标题楷体_GB2312、三级标题仿宋加粗、四级标题仿宋；首行缩进 2 字符 |
| 附件说明 | 正文下空一行左空 2 字，3 号仿宋「附件：1.×××」 |
| 发文机关署名 | 正文右下方，右空 2 字 |
| 成文日期 | 署名下，阿拉伯数字，右空 4 字 |
| 印章 | 端正、居中下压成文日期，不压正文 |
| 页码 | 4 号半角宋体阿拉伯数字，一字线「— 1 —」；单页码右空一字，双页码左空一字 |
| 版记 | 抄送机关、印发机关和印发日期，4 号仿宋，置于末页 |

> 启用条件：用户提到「公文 / 红头 / 发文字号 / 正式下发文件」等词时，样式切到公文预设
> （页面 3.7/3.5/2.8/2.6、正文仿宋三号、行距固定 28pt、标题黑体二号居中）。

