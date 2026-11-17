"""pdf_utils.py —— Agent 操作 .pdf 的通用函数库（读 + 拼 + 生成）。

能力边界（对应 docs/pdf-knowledge-base-2026-10-25.md）：
- 读：页数、元数据、每页文本量、是否加密、是否扫描件（无文本层）；
- 拼：合并、按页/按区间拆分、旋转、加水印（文字平铺）；
- 写：用 reportlab 生成中文 PDF（标题/正文/项目符号/表格），页码可选。

已知边界：
- 扫描件没有文本层，`extract_pages` 只能拿到空字符串 —— 这类必须走 OCR，不要假装读到了；
- 用 CID 字体（STSong-Light）写出的中文，pypdf 提取时可能拿到 CID 码而非汉字，
  所以「自己生成的中文 PDF 再用 pypdf 读回来」不能作为文本校验手段；
- 不提供 PDF→docx 转换：版面还原不可靠，宁可让用户选「重排一版」。
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4, LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

__all__ = [
    "PAGE_PRESETS",
    "PDF_BODY_FONT",
    "PDF_HEADING_FONT",
    "backup",
    "extract_pages",
    "make_pdf",
    "merge_pdfs",
    "read_report",
    "render_markdown_pdf",
    "rotate_pages",
    "split_pdf",
    "watermark",
]

# --------------------------------------------------------------------------- #
# 版式预设：与 docx 的 PAGE_* 保持同一套名字，便于脚本复用
# --------------------------------------------------------------------------- #

PAGE_PRESETS: dict[str, dict[str, Any]] = {
    "default": {
        "size": A4,
        "margin": {"left": 2.54 * cm, "right": 2.54 * cm, "top": 2.54 * cm, "bottom": 2.54 * cm},
    },
    "compact": {
        "size": A4,
        "margin": {"left": 2.0 * cm, "right": 2.0 * cm, "top": 2.0 * cm, "bottom": 2.0 * cm},
    },
    "gongwen": {
        "size": A4,
        "margin": {"left": 2.8 * cm, "right": 2.6 * cm, "top": 3.7 * cm, "bottom": 3.5 * cm},
    },
    "letter": {
        "size": LETTER,
        "margin": {"left": 2.54 * cm, "right": 2.54 * cm, "top": 2.54 * cm, "bottom": 2.54 * cm},
    },
}

# 字号不在这里写第二份：同一份稿子出 docx 和出 PDF 必须一样大，正文小四就是小四。
# 版式名两边不同（PDF 叫 default，docx 叫 report），这里只做名字对齐。
_PDF_TO_DOCX_PRESET = {"default": "report", "compact": "compact", "gongwen": "gongwen"}


def _docx_layout(preset: str) -> Any:
    """同名版式在 docx 那边的定义（字号、标题尺寸都从这儿取）。

    延迟导入：doc_render 会拉进 python-docx，PDF 这条路上不一定用得上；
    反过来 doc_render 不依赖本模块，不成环。
    """
    from .doc_render import PRESETS

    return PRESETS.get(_PDF_TO_DOCX_PRESET.get(preset, "report"), PRESETS["report"])

PDF_BODY_FONT = "STSong-Light"  # reportlab 内置中文 CID 字体，不需要额外字体文件
PDF_HEADING_FONT = "STSong-Light"


def _ensure_font() -> str:
    """注册中文字体（幂等）。返回可用字体名，失败时退回 Helvetica 保证不中断。"""
    try:
        pdfmetrics.getFont(PDF_BODY_FONT)
    except KeyError:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont(PDF_BODY_FONT))
        except Exception:  # pragma: no cover - reportlab 版本差异兜底
            return "Helvetica"
    return PDF_BODY_FONT


def _styles(preset: str = "default") -> dict[str, ParagraphStyle]:
    """一套段落样式。

    中文必须开 CJK 断行：reportlab 默认只看空格断词，一整段中文会被当成一个
    「超长单词」硬劈，行尾位置随缘；而且行内没有可拉伸的空格，两端对齐也就落不到实处。
    开了 CJK，字与字之间都是合法断点，两端对齐靠分配字间距把每行撑满版心——
    和 Word 里中文两端对齐是同一套做法。

    对齐按层级分工：文首标题块（大标题 / 副标题 / 信息行）居中，各级小节标题
    从版心左缘起行，正文两端对齐——和 docx 那边是同一套。
    """
    font = _ensure_font()
    # 字号从 docx 那套版式取：同一份稿子出 docx 和出 PDF，字必须一样大，
    # 否则用户对比两个文件的第一句就是「怎么这个字小一圈」。
    layout = _docx_layout(preset)
    body = layout.body_size
    # 1.5 倍行距：Word 的单倍行高约是字号的 1.2 倍，1.5 倍 ≈ 1.8 × 字号
    leading = round(body * 1.8)
    heading_pt = layout.heading_sizes[0]
    sub_heading_pt = layout.heading_sizes[1]
    cjk = "CJK"
    return {
        "title": ParagraphStyle(
            "title",
            fontName=font,
            fontSize=layout.title_size,
            leading=layout.title_size + 10,
            alignment=TA_CENTER,
            wordWrap=cjk,
            spaceAfter=6,
        ),
        # 副标题：比正文大一档、居中、加粗——大标题下面那行「基于 xx 的实验」。
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName=font,
            fontSize=max(layout.subtitle_size, body + 2.0),
            leading=max(layout.subtitle_size, body + 2.0) + 6,
            alignment=TA_CENTER,
            wordWrap=cjk,
            spaceAfter=12,
        ),
        # 文首信息行（实验名称 / 姓名 学号 专业 日期）：居中、不缩进、与正文同号。
        "byline": ParagraphStyle(
            "byline",
            fontName=font,
            fontSize=body,
            leading=leading + 2,
            alignment=TA_CENTER,
            wordWrap=cjk,
            spaceAfter=3,
        ),
        "h1": ParagraphStyle(
            "h1",
            fontName=font,
            fontSize=heading_pt,
            leading=heading_pt + 8,
            alignment=TA_LEFT,
            wordWrap=cjk,
            spaceBefore=10,
            spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2",
            fontName=font,
            fontSize=sub_heading_pt,
            leading=sub_heading_pt + 6,
            alignment=TA_LEFT,
            wordWrap=cjk,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=font,
            fontSize=body,
            leading=leading,
            alignment=TA_JUSTIFY,
            wordWrap=cjk,
            firstLineIndent=body * 2,
            spaceAfter=4,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontName=font,
            fontSize=body,
            leading=leading,
            alignment=TA_LEFT,
            wordWrap=cjk,
            leftIndent=body * 1.6,
            bulletIndent=body * 0.6,
            spaceAfter=3,
        ),
        "table": ParagraphStyle(
            "table", fontName=font, fontSize=body - 1.5, leading=leading - 3, wordWrap=cjk
        ),
        "note": ParagraphStyle(
            "note",
            fontName=font,
            fontSize=body - 2,
            leading=leading - 4,
            wordWrap=cjk,
            textColor=colors.grey,
        ),
    }


class _JustifiedParagraph(Paragraph):
    """正文段落：中文按「字间距」铺满版心，而不是靠 PDF 的词间距。

    reportlab 的 `TA_JUSTIFY` 只设 Tw（词间距），而 Tw 只作用于半角空格。中文句子里
    没有空格，Tw 无处可施，每行于是退回左对齐、右边缘一条毛边——用户选了「两端对齐」
    却看不出差别，等于没选。这里自己铺行：非末行算出剩余宽度，用 `setCharSpace`
    均摊到每个字上（Word 里调中文字间距是同一件事），行尾正好压在版心右缘。

    只接管「纯文本 + 单片段」的段落。带行内标记（`<b>`、`<br/>`）、条目符号的段落
    frags 不止一个，仍交回 reportlab 原生 `drawPara`——那条路径本来也不归这里重画。
    """

    def drawPara(self, debug: int = 0) -> None:  # type: ignore[override]
        blPara = self.blPara
        style = self.style
        lines = blPara.lines
        if (
            debug
            or blPara.kind != 0
            or style.alignment != TA_JUSTIFY
            or not lines
            or getattr(self, "bulletText", None)
        ):
            return Paragraph.drawPara(self, debug)

        canvas = self.canv
        font_name = blPara.fontName
        font_size = blPara.fontSize
        leading = style.leading
        last_index = len(lines) - 1

        canvas.saveState()
        canvas.setFillColor(blPara.textColor)
        y = self.height - getattr(blPara, "ascent", font_size)
        for index, (_extra, words) in enumerate(lines):
            text = "".join(str(word) for word in words)
            if not text:
                y -= leading
                continue
            indent = style.firstLineIndent if index == 0 else 0
            char_space = 0.0
            if index != last_index:
                slack = self.width - indent - pdfmetrics.stringWidth(text, font_name, font_size)
                # Tc 加在每个字形之后（含行尾那一个），所以按字符数摊，不按「间隙」数摊。
                # 行本来就被撑满、或算法算超了（slack < 0）就不动，宁可右边缘略短一分。
                if slack > 0:
                    char_space = slack / len(text)
            if char_space:
                # 字间距只存在于文本对象里（canvas 上没有 setCharSpace），一行一个对象
                tx = canvas.beginText(indent, y)
                tx.setFont(font_name, font_size, leading)
                tx.setCharSpace(char_space)
                tx.textOut(text)
                canvas.drawText(tx)
            else:
                canvas.setFont(font_name, font_size)
                canvas.drawString(indent, y, text)
            y -= leading
        canvas.restoreState()


def _escape(text: Any) -> str:
    """Paragraph 会解析 mini-HTML：正文里的 & < > 必须转义，否则整页生成失败。"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


# --------------------------------------------------------------------------- #
# 读
# --------------------------------------------------------------------------- #


def _open(path: str | Path, password: str = "") -> PdfReader:
    reader = PdfReader(str(path), strict=False)
    if reader.is_encrypted:
        # 空口令能开的加密 PDF 很常见（只加密权限不加密内容）
        try:
            reader.decrypt(password or "")
        except Exception as exc:  # pragma: no cover - 依赖具体文件
            raise ValueError(f"PDF 已加密，需要口令：{exc}") from exc
    return reader


def extract_pages(path: str | Path, pages: Iterable[int] | None = None) -> list[dict[str, Any]]:
    """按页抽文本。pages 为 1 起的页码；不传则整篇。"""
    reader = _open(path)
    total = len(reader.pages)
    wanted = (
        sorted({int(item) for item in pages if 1 <= int(item) <= total})
        if pages
        else list(range(1, total + 1))
    )
    result: list[dict[str, Any]] = []
    for page_no in wanted:
        try:
            text = reader.pages[page_no - 1].extract_text() or ""
        except Exception:
            text = ""
        result.append({"page": page_no, "chars": len(text.strip()), "text": text})
    return result


def read_report(path: str | Path) -> dict[str, Any]:
    """先体检再动手：页数、加密、元数据、每页文本量、疑似扫描页。"""
    path = Path(path)
    reader = _open(path)
    pages = extract_pages(path)
    empty = [item["page"] for item in pages if item["chars"] == 0]
    meta = {}
    try:
        raw = reader.metadata or {}
        meta = {str(key).lstrip("/"): str(value) for key, value in raw.items()}
    except Exception:  # pragma: no cover - 损坏的元数据
        meta = {}
    return {
        "file": path.name,
        "pages": len(pages),
        "encrypted": bool(reader.is_encrypted),
        "metadata": meta,
        "text_chars": sum(item["chars"] for item in pages),
        "empty_pages": empty,
        "scanned": len(empty) == len(pages) and len(pages) > 0,
        "per_page_chars": [(item["page"], item["chars"]) for item in pages],
    }


# --------------------------------------------------------------------------- #
# 拼
# --------------------------------------------------------------------------- #


def merge_pdfs(paths: Sequence[str | Path], out_path: str | Path) -> dict[str, Any]:
    writer = PdfWriter()
    used: list[str] = []
    for item in paths:
        reader = _open(item)
        for page in reader.pages:
            writer.add_page(page)
        used.append(Path(item).name)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as handle:
        writer.write(handle)
    return {"out": str(out), "files": used, "pages": len(writer.pages)}


def split_pdf(
    path: str | Path,
    out_dir: str | Path,
    every: int | None = None,
    ranges: Sequence[tuple[int, int]] | None = None,
) -> list[str]:
    """两种拆法：每 N 页一份（every），或按 1 起的闭区间列表（ranges）。"""
    reader = _open(path)
    total = len(reader.pages)
    stem = Path(path).stem
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    plans: list[tuple[int, int]] = []
    if ranges:
        plans = [(max(1, a), min(b, total)) for a, b in ranges if a <= total and b >= a]
    else:
        step = max(1, int(every or total))
        plans = [(start, min(start + step - 1, total)) for start in range(1, total + 1, step)]
    outputs: list[str] = []
    for index, (start, end) in enumerate(plans, start=1):
        writer = PdfWriter()
        for page_no in range(start, end + 1):
            writer.add_page(reader.pages[page_no - 1])
        out = target / f"{stem}_p{start}-{end}.pdf" if len(plans) > 1 else target / f"{stem}.pdf"
        with out.open("wb") as handle:
            writer.write(handle)
        outputs.append(str(out))
        if index > 200:  # pragma: no cover - 防御极端页数
            break
    return outputs


def rotate_pages(
    path: str | Path, out_path: str | Path, pages: Iterable[int], degrees: int = 90
) -> str:
    reader = _open(path)
    writer = PdfWriter()
    wanted = {int(item) for item in pages}
    for index, page in enumerate(reader.pages, start=1):
        if not wanted or index in wanted:
            page.rotate(int(degrees) % 360)
        writer.add_page(page)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as handle:
        writer.write(handle)
    return str(out)


def watermark(path: str | Path, out_path: str | Path, text: str, opacity: float = 0.12) -> str:
    """斜向平铺文字水印：每页用 reportlab 画一层，再叠到原页面上。"""
    from io import BytesIO

    from reportlab.pdfgen import canvas

    font = _ensure_font()
    reader = _open(path)
    writer = PdfWriter()
    for page in reader.pages:
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        buffer = BytesIO()
        layer = canvas.Canvas(buffer, pagesize=(width, height))
        layer.saveState()
        layer.setFillColor(colors.grey, alpha=max(0.02, min(opacity, 0.6)))
        layer.setFont(font, 28)
        layer.translate(width / 2, height / 2)
        layer.rotate(35)
        for row in range(-1, 2):
            layer.drawCentredString(0, row * 90, text)
        layer.restoreState()
        layer.save()
        buffer.seek(0)
        overlay = PdfReader(buffer).pages[0]
        page.merge_page(overlay)
        writer.add_page(page)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as handle:
        writer.write(handle)
    return str(out)


# --------------------------------------------------------------------------- #
# 写
# --------------------------------------------------------------------------- #


def _table_block(rows: Sequence[Sequence[Any]], style: ParagraphStyle) -> Table:
    data = [[Paragraph(_escape(cell), style) for cell in row] for row in rows]
    table = Table(data, hAlign="LEFT", repeatRows=1 if rows else 0)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B9C0CC")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF1F6")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


_SUBTITLE_STOP = ("。", "！", "？", ".", "!", "?")


def _looks_like_subtitle(text: str) -> bool:
    """紧跟大标题的那一行短句（「基于 Wokwi 的 ESP32 物联网仿真实验」）。

    判据三条：短（不超过一行）、不带句末标点、不是「字段：值」信息行。
    放宽一点就会把正文第一段判成副标题——那样整段被居中，比不居中更难看。
    """
    line = (text or "").strip()
    if not line or len(line) > 40:
        return False
    if any(mark in line for mark in _SUBTITLE_STOP):
        return False
    from .doc_render import looks_like_byline

    return not looks_like_byline(line)


def make_pdf(
    out_path: str | Path,
    title: str = "",
    blocks: Sequence[dict[str, Any]] = (),
    preset: str = "default",
    page_numbers: bool = True,
    footer_text: str = "",
    subtitle: str = "",
) -> dict[str, Any]:
    """生成 PDF。

    blocks 支持的类型：
    - {"type": "h1"|"h2", "text": "..."}
    - {"type": "p", "text": "..."}（正文首行缩进）
    - {"type": "bullet", "text": "..."}
    - {"type": "table", "rows": [[...], ...]}（第一行当表头）
    - {"type": "pagebreak"}
    """
    spec = PAGE_PRESETS.get(preset, PAGE_PRESETS["default"])
    styles = _styles(preset)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=spec["size"],
        leftMargin=spec["margin"]["left"],
        rightMargin=spec["margin"]["right"],
        topMargin=spec["margin"]["top"],
        bottomMargin=spec["margin"]["bottom"],
        title=title or out.stem,
    )

    flow: list[Any] = []
    pending = list(blocks)
    # 文首大标题只有一处居中。调用方没给 title 时，把第一个 h1 提上来当大标题——
    # 否则整篇最上面那行会以「小节标题」的身份左对齐（用户报过：docx 里居中，
    # 换成 PDF 就不居中了）。文本与已给的 title 相同时也吃掉，免得排两遍。
    promoted = False
    if pending and str(pending[0].get("type") or "") == "h1":
        head = str(pending[0].get("text") or "").strip()
        if head and (not title or head == title.strip()):
            title = title or head
            pending = pending[1:]
            promoted = True
    if title:
        flow.append(Paragraph(_escape(title), styles["title"]))
    # 标题块下面那两行：副标题、信息行（实验名称 / 姓名 学号 专业 日期）。
    # 它们和小节标题一样，排在文档最上面却又是「非正文」——一律居中、不首行缩进。
    from .doc_render import looks_like_byline  # 延迟导入：doc_render 不反依赖本模块

    # 大标题是从 blocks 里提上来的（markdown 那条路），才继续往下认副标题：
    # 调用方显式给了 title 时，紧跟其后的多半就是第一节正文第一段，
    # 一句不带句号的短句被当成副标题居中，整段排版就散了。
    if not subtitle and promoted and pending:
        first = pending[0]
        head_text = str(first.get("text") or "").strip()
        if str(first.get("type") or "") == "p" and _looks_like_subtitle(head_text):
            subtitle = head_text
            pending = pending[1:]
    if subtitle:
        flow.append(Paragraph(_escape(subtitle), styles["subtitle"]))
    while pending:
        line = str(pending[0].get("text") or "").strip()
        if str(pending[0].get("type") or "") != "p" or not looks_like_byline(line):
            break
        flow.append(Paragraph(_escape(line), styles["byline"]))
        pending = pending[1:]
    counts = {"h1": 0, "h2": 0, "p": 0, "bullet": 0, "table": 0}

    for block in pending:
        kind = str(block.get("type") or "p")
        if kind == "pagebreak":
            flow.append(PageBreak())
            continue
        if kind == "table":
            rows = block.get("rows") or []
            if rows:
                flow.append(_table_block(rows, styles["table"]))
                flow.append(Spacer(1, 6))
                counts["table"] += 1
            continue
        text = str(block.get("text") or "")
        if not text.strip():
            continue
        if kind in ("h1", "h2"):
            flow.append(Paragraph(_escape(text), styles[kind]))
            counts[kind] += 1
        elif kind == "bullet":
            flow.append(Paragraph(_escape(text), styles["bullet"], bulletText="•"))
            counts["bullet"] += 1
        else:
            # 正文走自己那条「按字铺满」的段落：reportlab 原生 justify 对中文无效
            flow.append(_JustifiedParagraph(_escape(text), styles["body"]))
            counts["p"] += 1

    if not flow:
        # 空文档（只有标题或干脆没内容）也要出 1 页，否则读回来 0 页很反直觉
        flow.append(Paragraph(" ", styles["body"]))

    def _decorate(canvas, document) -> None:
        canvas.saveState()
        canvas.setFont(_ensure_font(), 9)
        canvas.setFillColor(colors.grey)
        if footer_text:
            canvas.drawString(spec["margin"]["left"], 1.4 * cm, footer_text)
        if page_numbers:
            canvas.drawRightString(
                spec["size"][0] - spec["margin"]["right"], 1.4 * cm, f"第 {document.page} 页"
            )
        canvas.restoreState()

    doc.build(flow, onFirstPage=_decorate, onLaterPages=_decorate)
    return {
        "out": str(out),
        "bytes": out.stat().st_size,
        "preset": preset,
        "blocks": counts,
        "page_numbers": page_numbers,
    }


def render_markdown_pdf(
    md_text: str, out_path: str | Path, preset: str = "default"
) -> dict[str, Any]:
    """把简单 Markdown（#/## 标题、- 列表、| 表格、空行分段）排成 PDF。"""
    blocks: list[dict[str, Any]] = []
    table_lines: list[str] = []

    def flush_table() -> None:
        nonlocal table_lines
        if not table_lines:
            return
        rows: list[list[str]] = []
        for line in table_lines:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if all(set(cell) <= set("-: ") for cell in cells):
                continue  # 分隔行 |---|---|
            rows.append(cells)
        if rows:
            blocks.append({"type": "table", "rows": rows})
        table_lines = []

    for raw in (md_text or "").splitlines():
        line = raw.rstrip()
        if line.strip().startswith("|"):
            table_lines.append(line)
            continue
        flush_table()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("### "):
            blocks.append({"type": "h2", "text": stripped[4:]})
        elif stripped.startswith("## "):
            blocks.append({"type": "h1", "text": stripped[3:]})
        elif stripped.startswith("# "):
            blocks.append({"type": "h1", "text": stripped[2:]})
        elif stripped.startswith(("- ", "* ")):
            blocks.append({"type": "bullet", "text": stripped[2:]})
        else:
            blocks.append({"type": "p", "text": stripped})
    flush_table()
    return make_pdf(out_path, title="", blocks=blocks, preset=preset)


def backup(src: str | Path, out_dir: str | Path) -> str:
    """改动前先备份：返回副本路径，脚本把路径打印给用户即可追溯。"""
    source = Path(src)
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source.stem}.bak{source.suffix}"
    shutil.copy2(source, target)
    return str(target)


def safe_open_error(exc: Exception) -> str:
    """把 pypdf 的底层异常翻成一句用户能看懂的话。"""
    if isinstance(exc, PdfReadError):
        return "PDF 结构损坏或不是标准 PDF（可能是改了后缀的图片/网页）"
    if isinstance(exc, FileNotFoundError):
        return "文件不存在"
    return str(exc) or exc.__class__.__name__
