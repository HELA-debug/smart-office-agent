"""docx 版式引擎（services/doc_render）单元测试。

这一层是「一份 Markdown 同时变成 Word 和预览 HTML」的地方，所以断言集中在两件事：
结构有没有被如实还原（标题层级、表格、列表），以及两条路是不是同一份结构。
版式数字（字号/行距/间距）只挑关键的几条卡住，不逐像素断言——那是设计稿的事。
"""

from __future__ import annotations

import io
from pathlib import Path

from app.services.doc_render import (
    PRESETS,
    blocks_from_sections,
    blocks_to_html,
    parse_markdown,
    preset_with_style,
    render_docx_blocks,
    resolve_preset,
)
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt

BODY = """## 一句话结论
账号密码、短信验证码两条链路已完成联调。

## 进度：做了什么

| 事项 | 本周结果 |
|---|---|
| 账号密码登录联调 | 完成 |
| 短信验证码登录联调 | 完成 |

## 需要拍板的一件事
- 影响：第三方通道高峰期 3% 失败率
- 建议动作：增加备用通道

## 风险与问题
1. 短信通道 3% 失败率。
2. 接口总数未提供。
"""


def _kinds(blocks) -> list[str]:
    return [block.kind for block in blocks]


def test_parse_markdown_keeps_heading_levels_lists_and_tables() -> None:
    blocks = parse_markdown(BODY)

    # 「- 」条目不再是列表：一条一段（中文稿没有项目符号，靠空两格分句）；
    # 「1. 」仍然是「有编号的一串」，序号是信息，渲染时写进行首。
    assert _kinds(blocks) == [
        "heading",
        "paragraph",
        "heading",
        "table",
        "heading",
        "paragraph",
        "paragraph",
        "heading",
        "number",
    ]
    headings = [block.text for block in blocks if block.kind == "heading"]
    assert headings == ["一句话结论", "进度：做了什么", "需要拍板的一件事", "风险与问题"]

    table = next(block for block in blocks if block.kind == "table")
    assert table.header == ["事项", "本周结果"]
    assert len(table.rows) == 2


def test_plain_chinese_numbered_lines_become_headings() -> None:
    """模型不带 `##`、直接写「一、结论」时也要认成标题。

    认成列表项的话，正文会顶出一个「1. 一、结论」的圆点，整篇层级就毁了。
    区分靠「短 + 不带句读」：列表项是句子，句子里有逗号或句号。
    """
    blocks = parse_markdown(
        "一、一句话结论\n这周的活干完了。\n\n（一）子项\n内容。\n\n二、风险\n1. 短信通道 3% 失败率。\n"
    )

    kinds = [(block.kind, block.level) for block in blocks]
    assert kinds[:3] == [("heading", 2), ("paragraph", 0), ("heading", 3)]
    html = blocks_to_html("标题", blocks)
    # 原文编号保留，不能被自动编号叠成「一、一、…」
    assert '<h2 class="doc-h1">一、一句话结论</h2>' in html


def test_parse_markdown_treats_code_fence_as_opaque() -> None:
    """围栏里的表格行不能被当成表格——那是命令输出，不是文档结构。"""
    blocks = parse_markdown("```\n| a | b |\n|---|---|\n```\n")

    assert _kinds(blocks) == ["code"]
    assert "| a | b |" in blocks[0].text


def test_heading_numbering_is_automatic_and_rewrites_existing_numbers() -> None:
    """标题序号由渲染器统一给：作者写没写编号、写的是哪一套，都按同一种重排。

    「二、」下面挂一个作者手写的「2.1」，一篇里两套编号并排，看着像两个人拼的。
    """
    html = blocks_to_html(
        "标题",
        parse_markdown("## 结论\n正文\n\n## 一、已有编号\n正文\n\n### 细节\n正文\n"),
    )

    assert '<h2 class="doc-h1">一、结论</h2>' in html
    # 旧的「一、」被剥掉，按顺序重排成「二、」——不能叠成「二、一、已有编号」
    assert '<h2 class="doc-h1">二、已有编号</h2>' in html
    assert "一、一、" not in html and "二、一、" not in html
    assert '<h3 class="doc-h2">（一）细节</h3>' in html

    # 「2.1 测试数据记录」这类层级小数同理：按 decimal 方案重排成「1.1 测试数据记录」
    decimal = blocks_to_html(
        "标题", parse_markdown("### 2.1 测试数据记录\n正文\n"), numbering="decimal"
    )
    assert '<h3 class="doc-h2">1.1 测试数据记录</h3>' in decimal


def test_numbering_switches_with_the_document_type(tmp_path: Path) -> None:
    """同一份小节，五种文档类型排出五种编号。

    编号是文体的一部分：周报用「一、」「（一）」，论文与方案用「1.1.1」，
    合同用「第一条」，纪要与手册不编号，公文用国标那套四层序数。

    中文方案的三级起不编号：中文没有通行的纯中文三级序号，硬凑只能借「1.」
    「①」这类外来的，就又变成汉字阿拉伯混排了。层级靠字号与缩进区分。
    """
    blocks = parse_markdown("## 概况\n正文\n\n### 数据\n正文\n\n#### 节点\n正文\n\n## 计划\n正文\n")
    expected = {
        "cn": ["一、概况", "（一）数据", "节点", "二、计划"],
        "decimal": ["1. 概况", "1.1 数据", "1.1.1 节点", "2. 计划"],
        "article": ["第一条 概况", "（一）数据", "节点", "第二条 计划"],
        "none": ["概况", "数据", "节点", "计划"],
        "gb": ["一、概况", "（一）数据", "1. 节点", "二、计划"],
    }
    for scheme, labels in expected.items():
        html = blocks_to_html("标题", blocks, numbering=scheme)
        for label in labels:
            assert f">{label}<" in html, (scheme, label)

        path = tmp_path / f"{scheme}.docx"
        render_docx_blocks(path, title="标题", blocks=blocks, numbering=scheme)
        texts = [
            p.text
            for p in Document(str(path)).paragraphs
            if p.style.name.startswith("Heading") and p.text.strip()
        ]
        assert texts == labels, scheme


def test_preview_and_docx_share_the_same_numbering(tmp_path: Path) -> None:
    """预览是「一、摘要」、下载是「1. 摘要」，用户会以为拿错了文件。"""
    blocks = parse_markdown("## 摘要\n正文\n")
    path = tmp_path / "same.docx"
    render_docx_blocks(path, title="标题", blocks=blocks, numbering="decimal")
    docx_headings = [
        p.text
        for p in Document(str(path)).paragraphs
        if p.style.name.startswith("Heading") and p.text.strip()
    ]

    assert docx_headings == ["1. 摘要"]
    assert '<h2 class="doc-h1">1. 摘要</h2>' in blocks_to_html("标题", blocks, numbering="decimal")


def test_preview_html_mirrors_the_same_structure() -> None:
    html = blocks_to_html("工作周报", parse_markdown(BODY), subtitle="登录模块联调 · 结论先行")

    assert '<p class="doc-lead">登录模块联调 · 结论先行</p>' in html
    assert '<h2 class="doc-h1">一、一句话结论</h2>' in html
    assert "<table><thead><tr><th>事项</th>" in html
    # 条目排成正文段落，预览里不出现圆点列表；有序条目的序号写在行首
    assert "<ul>" not in html and "<li>" not in html
    assert "<p>影响：第三方通道高峰期 3% 失败率</p>" in html
    assert "<p>1. 短信通道 3% 失败率。</p>" in html
    # 行内加粗不能把星号原样吐出来
    assert "**" not in html


def test_blocks_from_sections_turns_dash_lines_into_paragraphs() -> None:
    """骨架路径：句子列表里混着「- 」条目时，去掉符号、一条一段。"""
    blocks = blocks_from_sections(
        [
            {"heading": "本周进展", "paragraphs": ["完成联调。", "- 覆盖 12 个接口", "- 压测通过"]},
            {"heading": "备注", "paragraphs": ["以上摘自周会记录。"]},
        ]
    )

    assert _kinds(blocks) == [
        "heading",
        "paragraph",
        "paragraph",
        "paragraph",
        "heading",
        "paragraph",
    ]
    assert [block.text for block in blocks if block.kind == "paragraph"] == [
        "完成联调。",
        "覆盖 12 个接口",
        "压测通过",
        "以上摘自周会记录。",
    ]


def test_docx_renders_title_heading_and_table(tmp_path: Path) -> None:
    path = tmp_path / "report.docx"
    render_docx_blocks(
        path, title="工作周报 2026-W45", blocks=parse_markdown(BODY), subtitle="结论先行"
    )

    document = Document(str(path))
    styles = [(paragraph.style.name, paragraph.text) for paragraph in document.paragraphs]
    # 文档标题走 Title 样式：Word 导航窗格与 mammoth 的 styleMap 都按样式名认标题
    assert styles[0] == ("Title", "工作周报 2026-W45")
    assert ("Heading 1", "一、一句话结论") in styles
    # 副标题是标题下的一行小字，不是正文第一段
    assert styles[1][1] == "结论先行"

    assert len(document.tables) == 1
    table = document.tables[0]
    assert table.rows[0].cells[0].text == "事项"
    # 表头有底纹、字号比正文小一档
    assert (
        table.rows[0]
        .cells[0]
        ._tc.tcPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}shd")
        is not None
    )


def test_docx_keeps_paragraph_spacing_and_cjk_font(tmp_path: Path) -> None:
    path = tmp_path / "spacing.docx"
    render_docx_blocks(path, title="标题", blocks=parse_markdown("## 小节\n正文内容。\n"))

    document = Document(str(path))
    body = next(p for p in document.paragraphs if p.text == "正文内容。")
    assert body.paragraph_format.line_spacing == 1.5
    assert body.paragraph_format.space_after is not None
    run = body.runs[0]
    # 正文默认宋体小四（12pt）——这是国内办公文档的通行写法
    assert run.font.size is not None and round(run.font.size.pt, 1) == 12.0
    # 中文字体必须同时写 w:eastAsia，否则 Word 用模板默认字体
    xml = run._element.xml
    assert "w:eastAsia" in xml and "宋体" in xml


def test_body_paragraph_indents_two_characters_the_word_way(tmp_path: Path) -> None:
    """首行缩进要写成「2 字符」（w:firstLineChars=200），不是写死 24pt。

    写死 pt 的后果：字号一换，24pt 就不再是两格，同一篇里缩进深浅不一。
    """
    path = tmp_path / "indent.docx"
    render_docx_blocks(
        path, title="标题", blocks=parse_markdown("## 小节\n正文内容。\n\n列表：\n\n- 短条目\n")
    )

    document = Document(str(path))
    body = next(p for p in document.paragraphs if p.text == "正文内容。")
    ind = body._p.pPr.find(qn("w:ind"))
    assert ind is not None
    assert ind.get(qn("w:firstLineChars")) == "200"
    # firstLine 兜底给 WPS / python-docx 读：2 字符 × 12pt = 480 twip
    assert ind.get(qn("w:firstLine")) == "480"
    # 「- 」条目同样排成正文段落：空两格、不带项目符号，和上一段一模一样
    item = next(p for p in document.paragraphs if p.text == "短条目")
    assert item._p.pPr.find(qn("w:ind")).get(qn("w:firstLineChars")) == "200"
    assert not any("·" in run.text for p in document.paragraphs for run in p.runs)


def test_doc_style_overlay_only_touches_what_the_user_picked() -> None:
    """输入区「文档格式」点的那几项叠到预设上，没点的照旧。

    这里卡两件容易做错的事：
    1. **只给字号**时，字体 / 行距 / 缩进不能被一起顶掉——用户改一个数字，
       整篇换字体换行距，他会以为面板点了就全乱。
    2. **首行缩进 0** 必须真的生效：0 是「顶格」，不是「没填」。
       前端传的是字符串 `"0"`，后端转成数字后若被当成假值丢掉，
       用户选「不缩进」预览里还空两格，会判定「你没按我说的做」。
    """
    base = PRESETS["report"]

    only_size = preset_with_style(base, {"size": "三号"})
    assert only_size.body_size == base.body_size + 4  # 小四 12 → 三号 16
    assert only_size.cn_font == base.cn_font
    assert only_size.body_line == base.body_line
    assert only_size.body_indent == base.body_indent
    assert only_size.body_align == base.body_align

    flat = preset_with_style(base, {"indent_chars": 0, "align": "左对齐"})
    assert flat.body_indent == 0.0
    assert flat.body_align == "left"

    # 没给任何值 = 不干预（连对象都不该换掉）
    assert preset_with_style(base, {}) is base
    assert preset_with_style(base, None) is base


def test_title_is_centered_serif_and_the_largest_type(tmp_path: Path) -> None:
    """大标题：居中、宋体、全文最大——三件事都得是默认，而不是靠模型记得。"""
    path = tmp_path / "title.docx"
    render_docx_blocks(path, title="W46 周报", blocks=parse_markdown("## 小节\n正文。\n"))

    document = Document(str(path))
    title = document.paragraphs[0]
    assert title.style.name == "Title"
    assert title.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert (
        title.runs[0]._element.find(qn("w:rPr")).find(qn("w:rFonts")).get(qn("w:eastAsia"))
        == "宋体"
    )

    for preset in PRESETS.values():
        biggest = max(preset.body_size, preset.table_size, *preset.heading_sizes)
        assert preset.title_size > biggest, preset.name


def test_justified_body_and_left_aligned_headings(tmp_path: Path) -> None:
    """正文两端对齐，各级小节标题左对齐、从版心左缘起行。

    居中只给**文首标题块**（大标题 / 副标题 / 信息行）：那三行是「这是题目、这是
    谁的材料」的信号。小节标题一居中，读者每翻一节都要把视线拉回页面中间重找起行
    位置，长稿尤其累——所以标题左、正文两端对齐，规则钉死在渲染器上，不指望模型记。
    也短暂试过把正文整段居中：右侧是「对称」了，可每行的起行位置都随行长漂移。
    """
    path = tmp_path / "align.docx"
    blocks = parse_markdown(
        "## 摘要\n正文。\n\n### 测试数据记录\n七组数据。\n\n#### 细节\n补充。\n"
    )
    render_docx_blocks(path, title="W46 周报", blocks=blocks)

    document = Document(str(path))
    assert document.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER  # Title
    headings = [p for p in document.paragraphs if p.style.name.startswith("Heading")]
    assert headings, "样例里没有小节标题，断言没意义"
    for paragraph in headings:
        assert paragraph.alignment == WD_ALIGN_PARAGRAPH.LEFT, paragraph.text
        # 标题不吃首行缩进：缩进是「段落从哪起」的信号，标题左缘要能对齐版心
        indent = paragraph.paragraph_format.first_line_indent
        assert not indent or indent == Pt(0), paragraph.text

    # 正文（含列表条目）：两端对齐 + 首行缩进两格，两件事都要落在段落属性上
    body = [p for p in document.paragraphs if p.style.name == "Normal" and p.text.strip()]
    assert body, "样例里没有正文段落，断言没意义"
    for paragraph in body:
        assert paragraph.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY, paragraph.text
        ind = paragraph._p.pPr.find(qn("w:ind"))
        assert ind.get(qn("w:firstLineChars")) == "200", paragraph.text

    # 样式级也要钉住：只改段落的话，模型脚本里「用了样式但没单独设对齐」的标题
    # 会退回 Normal 的两端对齐，被拉成满行
    for level in (1, 2, 3, 4):
        style = document.styles[f"Heading {level}"]
        assert style.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.LEFT


def test_subtitle_gets_its_own_style_so_the_preview_does_not_indent_it(tmp_path: Path) -> None:
    """副标题必须用 Subtitle 样式：预览按样式名把它认成 `.doc-lead`。

    以前它就是个普通段落。正文开始「首行缩进两格」之后，居中的副标题也跟着缩进
    两个字符，整行往右跑——看着像排版坏了，而不是「标题下面的一行小字」。
    """
    path = tmp_path / "subtitle.docx"
    render_docx_blocks(
        path,
        title="W46 周报",
        blocks=parse_markdown("## 小节\n正文。\n"),
        subtitle="登录模块联调 · 结论先行",
    )

    document = Document(str(path))
    lead = document.paragraphs[1]
    assert lead.text == "登录模块联调 · 结论先行"
    assert lead.style.name == "Subtitle"
    assert lead.alignment == WD_ALIGN_PARAGRAPH.CENTER
    # Subtitle 样式自带斜体；副标题是一行说明，不是强调
    assert not any(run.font.italic for run in lead.runs)
    # 比正文大一档且加粗：字号一样只靠居中区分时，看着像正文第一段被居中了
    assert lead.runs[0].font.size > Pt(PRESETS["report"].body_size)
    assert lead.runs[0].font.bold


def test_preset_aliases_cover_how_people_describe_density() -> None:
    """模型会把用户的话原样塞进 layout：说「密一点」和说「说明书」得落到同一套。

    认不出的词会静默落回默认版式——用户明明要密的，出来还是正常版，他只会觉得
    「没听懂我说话」。所以同义词要按「用户怎么描述这东西」收，不按版式名收。
    """
    for word in (
        "紧凑",
        "精简",
        "扁平",
        "平铺",
        "密排",
        "高密度",
        "资料",
        "说明书",
        "手册",
        "附录",
        "速查",
        "dense",
        "tight",
        "manual",
        "handbook",
    ):
        assert resolve_preset(word) == "compact", word
    assert resolve_preset("公文") == "gongwen"
    assert resolve_preset("") == "report"


def test_preview_wraps_compact_document_to_shrink_it() -> None:
    """紧凑版式在预览里也要「更密」：整篇包一层 `.doc-compact`，CSS 才好整体缩一档。

    Word 那边靠字号（五号）、行距（1.25）、页边距（2cm）变密，预览没有这些参数，
    只能靠这个类。以前紧凑版式在预览里只做了一件事——把正文缩进清掉，结果既没变密，
    还把「段落从哪起」抹平了。
    """
    default_html = blocks_to_html("周报", parse_markdown("## 小节\n正文。\n"))
    assert "<p>正文。</p>" in default_html
    assert "doc-compact" not in default_html
    # 默认版式：正文两端对齐、首行缩进 2 字符（Word 里是 w:jc=both + w:ind firstLineChars=200）
    assert "doc-flat" not in default_html
    assert "--doc-indent:2em" in default_html
    # 两端对齐是默认值，不生成 doc-align-*：`.prose-docx p` 的基础规则本来就是 justify，
    # 只有用户显式改左/中/右时才需要那个类去覆盖
    assert "doc-align-" not in default_html

    dense_html = blocks_to_html("资料", parse_markdown("## 小节\n正文。\n"), preset="紧凑")
    assert "doc-body doc-compact" in dense_html
    # 缩进规则跟默认版式一致：只有公文那种「格式规定顶格」的才清缩进
    assert '<p class="doc-flat">' not in dense_html
    assert "<p>正文。</p>" in dense_html


def test_preview_html_centers_only_the_title(tmp_path: Path) -> None:
    """预览这条路同理：`h1.doc-title` 只有一个，小节标题从 h2 起。"""
    blocks = parse_markdown("## 摘要\n正文。\n\n### 二级\n内容。\n")
    html = blocks_to_html("W46 周报", blocks)

    assert html.count('class="doc-title"') == 1
    assert "<h1" in html and '<h2 class="doc-h1">一、摘要</h2>' in html
    assert "<h1>摘要" not in html  # 小节标题不能被当成文档标题
    # 第一行是版式包裹层（对齐/缩进/密度的 CSS 变量），大标题必须紧跟在它后面
    assert html.split("\n")[1].startswith('<h1 class="doc-title">')


def test_line_option_switches_body_line_spacing(tmp_path: Path) -> None:
    """行距除了默认 1.5，还要能单倍 / 多倍 / 固定值——一句话就该能改。"""
    for value, expected in (("单倍", 1.0), ("双倍", 2.0), ("1.25", 1.25)):
        path = tmp_path / f"{expected}.docx"
        render_docx_blocks(path, title="标题", blocks=parse_markdown("正文内容。\n"), line=value)
        body = next(p for p in Document(str(path)).paragraphs if p.text == "正文内容。")
        assert body.paragraph_format.line_spacing == expected, value

    # 固定值：Word 里存的是 twip，python-docx 读回来仍是 28pt
    path = tmp_path / "fixed.docx"
    render_docx_blocks(path, title="标题", blocks=parse_markdown("正文内容。\n"), line="固定值28磅")
    body = next(p for p in Document(str(path)).paragraphs if p.text == "正文内容。")
    assert body.paragraph_format.line_spacing == Pt(28)


def test_dash_items_never_come_out_with_bullet_markers(tmp_path: Path) -> None:
    """一份稿子满屏圆点，读起来像清单不像文章；中文正式稿里没有这一层。

    以前只在「这一组全是长句」时才转段落，混进一条短句整组就打回圆点，
    同一篇里一节是段落、一节是圆点——看着像排版坏了。现在一律排成段落。
    """
    long_sentence = (
        "本周完成「温湿度采集与 OLED 显示」项目实验，基于 Wokwi 浏览器端 ESP32 仿真平台复现。"
    )
    prose = parse_markdown(f"- {long_sentence}\n- {long_sentence}\n")
    assert _kinds(prose) == ["paragraph", "paragraph"]

    checklist = parse_markdown("- 影响：第三方通道 3% 失败率\n- 建议：增加备用通道\n")
    assert _kinds(checklist) == ["paragraph", "paragraph"]
    assert [block.text for block in checklist] == [
        "影响：第三方通道 3% 失败率",
        "建议：增加备用通道",
    ]

    path = tmp_path / "no-bullet.docx"
    render_docx_blocks(path, title="标题", blocks=parse_markdown("- 短条目\n- 另一条\n"))
    texts = [paragraph.text for paragraph in Document(str(path)).paragraphs]
    assert "短条目" in texts and "另一条" in texts
    assert not any(text.lstrip().startswith("·") for text in texts)


def test_docx_bytes_are_a_valid_zip(tmp_path: Path) -> None:
    path = tmp_path / "valid.docx"
    render_docx_blocks(path, title="标题", blocks=parse_markdown("正文。\n"))

    assert path.read_bytes()[:2] == b"PK"
    assert Document(io.BytesIO(path.read_bytes())).paragraphs[0].text == "标题"


def _left_chars(document: Document) -> list[str | None]:
    """小节标题的 w:leftChars；段落上根本没写 w:ind 时给 None。"""
    values: list[str | None] = []
    for paragraph in document.paragraphs:
        if not paragraph.style.name.startswith("Heading") or not paragraph.text.strip():
            continue
        ppr = paragraph._p.pPr
        ind = ppr.find(qn("w:ind")) if ppr is not None else None
        values.append(ind.get(qn("w:leftChars")) if ind is not None else None)
    return values


def test_headings_indent_by_level(tmp_path: Path) -> None:
    """1. 与 1.1 顶在同一条竖线上，读者只能靠多读一个编号判断层级。

    缩进写 `w:leftChars`（字符），不是 pt：二号字的 1 字符和五号字的 2 字符不是
    一个宽度，写死 pt 的话换个版式两级标题就歪了。公文是国标顶格，不在这一列。
    """
    blocks = parse_markdown("## 概况\n\n正文\n\n### 数据\n\n正文\n\n#### 节点\n\n正文\n")
    path = tmp_path / "indent.docx"
    render_docx_blocks(path, title="标题", blocks=blocks, numbering="decimal")

    assert _left_chars(Document(str(path))) == ["0", "100", "200"]


def test_gongwen_keeps_headings_flush_left(tmp_path: Path) -> None:
    """GB/T 9704 规定各级标题顶格左起——公文的居中/缩进都是格式错，不是审美问题。

    紧凑版式不在此列：它只是「更密」，层级规则跟默认版式一样（左对齐、逐级缩进）。
    """
    blocks = parse_markdown("## 概况\n\n正文\n\n### 数据\n\n正文\n")
    path = tmp_path / "gongwen.docx"
    render_docx_blocks(path, title="标题", blocks=blocks, preset="gongwen")
    doc = Document(str(path))
    heads = [p for p in doc.paragraphs if p.style.name.startswith("Heading") and p.text.strip()]
    assert heads, "样例里没有小节标题，断言没意义"
    for paragraph in heads:
        assert paragraph.alignment == WD_ALIGN_PARAGRAPH.LEFT, paragraph.text
    assert set(_left_chars(doc)) <= {None, "0"}  # 顶格，不缩进

    dense = tmp_path / "compact.docx"
    render_docx_blocks(dense, title="标题", blocks=blocks, preset="compact")
    ddoc = Document(str(dense))
    dheads = [p for p in ddoc.paragraphs if p.style.name.startswith("Heading") and p.text.strip()]
    assert dheads
    for paragraph in dheads:
        assert paragraph.alignment == WD_ALIGN_PARAGRAPH.LEFT, paragraph.text
    assert _left_chars(ddoc) == ["0", "100"]  # 逐级缩进，跟默认版式同一套


def test_preview_carries_the_level_class_for_indent() -> None:
    """预览靠 `.doc-hN` 缩进，和 Word 里的 `w:leftChars` 是同一套；
    顶格版式（公文）不输出这个类，CSS 就不会去缩。"""
    html = blocks_to_html("标题", parse_markdown("## 一\n\n正文\n\n### 二\n\n正文\n"))
    assert 'class="doc-h1"' in html
    assert 'class="doc-h2"' in html

    flat = blocks_to_html("标题", parse_markdown("## 一\n\n正文\n"), preset="公文")
    assert "doc-h1" not in flat


def test_byline_block_is_centered_and_not_indented(tmp_path: Path) -> None:
    """文首「姓名：… 学号：…」这类信息行跟标题一起居中，且不空两格。

    样例文档的标题块是四行：大标题、副标题、两行字段。信息行按正文排会多出两格
    首行缩进，还跟着两端对齐把字距拉开——一眼就不像落款。
    """
    path = tmp_path / "byline.docx"
    render_docx_blocks(
        path,
        title="实验二　光照自适应调光实验报告",
        subtitle="基于 Wokwi 的 ESP32 物联网仿真实验",
        blocks=parse_markdown(
            "姓名：敬一博　学号：202416320112　专业：智慧能源\n\n"
            "## 1 实验设备\n本实验在 Wokwi 的 ESP32 仿真平台完成。\n"
        ),
    )

    document = Document(str(path))
    byline = document.paragraphs[2]
    assert byline.text.startswith("姓名：敬一博")
    assert byline.style.name == "Normal"
    assert byline.alignment == WD_ALIGN_PARAGRAPH.CENTER
    ind = byline._p.pPr.find(qn("w:ind"))
    assert ind is None or ind.get(qn("w:firstLineChars")) in (None, "0")
    # 只认文首那一段：小节标题照样左对齐
    head = next(p for p in document.paragraphs if p.style.name.startswith("Heading"))
    assert head.alignment == WD_ALIGN_PARAGRAPH.LEFT


def test_byline_only_counts_before_the_first_heading() -> None:
    """正文里的「日期：2026-11-11」是数据，不能跟着居中。"""

    html = blocks_to_html(
        "标题",
        parse_markdown("姓名：张三　学号：2024001\n\n## 一节\n\n日期：2026-11-11　地点：机房\n"),
    )
    assert '<p class="doc-byline">姓名：张三　学号：2024001</p>' in html
    assert '<p>日期：2026-11-11　地点：机房</p>' in html
