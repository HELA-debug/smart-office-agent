"""docx_utils.py —— Agent 操作 .docx 的通用函数库。

为什么单独抽这一层：真实文档加工经常是「统一正文 → 重排标题 → 加表格 → 替换措辞」，
如果每次让模型现场拼 XML，样式常量会散落一地、`w:eastAsia` 漏写导致中文变宋体以外的字体。
这里把常用预设和操作固化成常量 + 函数，脚本里 `from docx_utils import *` 直接用。

设计约定（对应 docs/docx-knowledge-base-2026-10-25.md）：
- 字号、字体、行距、缩进、页面这些「词」全部来自 `services/doc_lexicon.py`，
  本文件只负责取用与落到 XML——加字号/改行距去改那张表，别在这里另写一个数字；
- 最小改动：函数默认只处理「你指定的范围」，不做全量重置；
- 中文字体一律同时写 `w:rFonts/@w:eastAsia`，否则 Word 里中文字体不生效；
- 返回改动计数，方便脚本打印「改了 N 处」给用户核对。
"""

from __future__ import annotations

import contextlib
import datetime
import os
import shutil
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

try:  # 脚本工作目录里 *_utils.py 是平铺复制的，没有包结构，只能绝对导入
    from .doc_lexicon import (
        DOC_TYPES,
        FONT_ROLES,
        FONTS,
        HEADING_SCALES,
        LINE_DOUBLE,
        LINE_FIXED_22,
        LINE_FIXED_28,
        LINE_LOOSE,
        LINE_ONE_HALF,
        LINE_SINGLE,
        LINE_TIGHT,
        PAGES,
        TABLE_STYLES,
        heading_specs,
        page_spec,
        resolve_doc_type,
        resolve_font,
        resolve_indent,
        resolve_line,
        resolve_size,
    )
except ImportError:  # pragma: no cover - 沙箱里平铺运行时走这条
    from doc_lexicon import (  # type: ignore[no-redef]
        DOC_TYPES,
        FONT_ROLES,
        FONTS,
        HEADING_SCALES,
        LINE_DOUBLE,
        LINE_FIXED_22,
        LINE_FIXED_28,
        LINE_LOOSE,
        LINE_ONE_HALF,
        LINE_SINGLE,
        LINE_TIGHT,
        PAGES,
        TABLE_STYLES,
        heading_specs,
        page_spec,
        resolve_doc_type,
        resolve_font,
        resolve_indent,
        resolve_line,
        resolve_size,
    )

__all__ = [
    "DOC_TYPES",
    "FONT_BODY",
    "FONT_BODY_GONGWEN",
    "FONT_BODY_MODERN",
    "FONT_CODE",
    "FONT_H1",
    "FONT_H2",
    "FONT_H3",
    "FONT_H4",
    "FONT_NOTE",
    "FONT_QUOTE",
    "FONT_TABLE",
    "FONT_TITLE",
    "HEADING_SCALE",
    "LINE_DOUBLE",
    "LINE_FIXED_22",
    "LINE_FIXED_28",
    "LINE_LOOSE",
    "LINE_ONE_HALF",
    "LINE_SINGLE",
    "LINE_TIGHT",
    "PAGE_BRIEF",
    "PAGE_COMPACT",
    "PAGE_DEFAULT",
    "PAGE_GONGWEN",
    "PAGE_LETTER",
    "PAGE_MEMO",
    "PAGE_PRESETS",
    "PAGE_RESUME",
    "PAGE_THESIS",
    "TABLE_STYLES",
    "add_page_number",
    "add_table_simple",
    "apply_body",
    "apply_headings",
    "backup",
    "ensure_doc",
    "insert_ordered",
    "read_report",
    "repeat_header",
    "replace_text",
    "resolve_doc_type",
    "resolve_font",
    "resolve_indent",
    "resolve_line",
    "resolve_size",
    "set_font",
    "set_indent_chars",
    "set_left_indent_chars",
    "set_page",
    "set_para",
    "set_rfonts",
    "shade_cell",
]

# --------------------------------------------------------------------------- #
# 样式预设：默认值 = 通用中文办公文档；公文 = GB/T 9704
# --------------------------------------------------------------------------- #

PAGE_PRESETS = {name: page_spec(name) for name in PAGES}
PAGE_DEFAULT = PAGE_PRESETS["default"]
PAGE_COMPACT = PAGE_PRESETS["compact"]
PAGE_GONGWEN = PAGE_PRESETS["gongwen"]
PAGE_THESIS = PAGE_PRESETS["thesis"]
PAGE_RESUME = PAGE_PRESETS["resume"]
PAGE_LETTER = PAGE_PRESETS["letter"]
PAGE_BRIEF = PAGE_PRESETS["brief"]
PAGE_MEMO = PAGE_PRESETS["memo"]


def ensure_doc(doc):
    """把「文件路径」自动换成 Document 对象。

    模型写脚本时最常犯的错，是把路径直接丢给 read_report / apply_body，
    报出来却是 `'str' object has no attribute 'paragraphs'`——一句看不出所以然的话，
    于是它再猜一次、再错一次。这里统一兜住：
    传 str / Path 就按路径打开，传 Document 原样返回，传 None 给一句能照着改的话。
    """
    if doc is None:
        raise ValueError(
            "没有拿到 docx：请传入 Document 对象或 .docx 文件路径（素材在 $OA_INPUT_DIR）"
        )
    if isinstance(doc, (str, os.PathLike)):
        path = Path(doc)
        if not path.is_file():
            raise FileNotFoundError(f"找不到 docx 文件：{path}（素材在 $OA_INPUT_DIR）")
        return Document(str(path))
    if not hasattr(doc, "paragraphs"):
        raise TypeError(
            f"这不是 docx 对象（拿到的是 {type(doc).__name__}）：请传 Document 或 .docx 路径"
        )
    return doc


# (中文字体, 西文/数字字体, 字号 pt)
# 数字与字体名一律从 services/doc_lexicon.py 取：改字号只改那一张表，
# 这里和 doc_render 的产品版式不会各说一套。
FONT_BODY = (*FONTS["宋体"], resolve_size("小四"))  # 正文 小四
FONT_BODY_GONGWEN = (*FONTS["仿宋_GB2312"], resolve_size("三号"))  # 公文正文 三号
FONT_BODY_MODERN = (*FONTS["微软雅黑"], 11)  # 简历 / 商务
FONT_H1 = (*FONTS["黑体"], resolve_size("三号"))  # 一级标题 三号
FONT_H2 = (*FONTS["黑体"], resolve_size("四号"))  # 二级标题 四号
FONT_H3 = (*FONTS["宋体"], resolve_size("小四"))  # 三级标题 小四加粗
FONT_H4 = (*FONTS["宋体"], resolve_size("小四"))  # 四级标题 小四加粗
FONT_TABLE = (*FONTS["宋体"], resolve_size("五号"))  # 表格 五号
FONT_NOTE = (*FONTS["宋体"], resolve_size("小五"))  # 脚注 小五
FONT_TITLE = (*FONTS[FONT_ROLES["title"]], resolve_size("二号"))  # 标题 宋体二号（全文最大）
FONT_QUOTE = (*FONTS["楷体"], resolve_size("小四"))  # 引用、批示、摘录
FONT_CODE = (*FONTS["Consolas"], resolve_size("小五"))  # 代码 / 命令 / 字段名

# 标题层级刻度：一套文档只用一套，别在同一篇里 h1 用 16、h2 用 15——层级看不出差别
# 时，读者只能靠编号猜结构。顺序是 (一级, 二级, 三级, 四级) 的字号。
HEADING_SCALE: dict[str, tuple[float, ...]] = {
    name: tuple(spec[2] for spec in heading_specs(name)) for name in HEADING_SCALES
}

_DEFAULT_HEADING_MAP: dict[str, tuple[str, str, float, bool]] = {
    f"Heading {index}": spec for index, spec in enumerate(heading_specs("report"), start=1)
}


# --------------------------------------------------------------------------- #
# 底层：字体 / 段落
# --------------------------------------------------------------------------- #

#: `w:pPr` 子元素的合法顺序（ECMA-376 CT_PPr）。Word 对乱序是能忍的，WPS 不是：
#: `w:ind` 写在 `w:jc` 后面时，WPS 直接忽略缩进——用户看到的「WPS 里首行不缩进、
#: 表格没框线」就是这一条。所以凡是不走 python-docx 托管的元素（pBdr / shd /
#: tblBorders / tblLayout），一律按这张表插到该在的位置，不再 append 到底。
_PPR_ORDER = (
    "w:pStyle",
    "w:keepNext",
    "w:keepLines",
    "w:pageBreakBefore",
    "w:framePr",
    "w:widowControl",
    "w:numPr",
    "w:suppressLineNumbers",
    "w:pBdr",
    "w:shd",
    "w:tabs",
    "w:suppressAutoHyphens",
    "w:kinsoku",
    "w:wordWrap",
    "w:overflowPunct",
    "w:topLinePunct",
    "w:autoSpaceDE",
    "w:autoSpaceDN",
    "w:bidi",
    "w:adjustRightInd",
    "w:snapToGrid",
    "w:spacing",
    "w:ind",
    "w:contextualSpacing",
    "w:mirrorIndents",
    "w:suppressOverlap",
    "w:jc",
    "w:textDirection",
    "w:textAlignment",
    "w:textboxTightWrap",
    "w:outlineLvl",
    "w:divId",
    "w:cnfStyle",
    "w:rPr",
    "w:sectPr",
    "w:pPrChange",
)

#: `w:tblPr` 的合法顺序（CT_TblPr）。
_TBLPR_ORDER = (
    "w:tblStyle",
    "w:tblpPr",
    "w:tblOverlap",
    "w:bidiVisual",
    "w:tblStyleRowBandSize",
    "w:tblStyleColBandSize",
    "w:tblW",
    "w:jc",
    "w:tblCellSpacing",
    "w:tblInd",
    "w:tblBorders",
    "w:shd",
    "w:tblLayout",
    "w:tblCellMar",
    "w:tblLook",
    "w:tblCaption",
    "w:tblDescription",
    "w:tblPrChange",
)

#: `w:tcPr` 的合法顺序（CT_TcPr）。
_TCPR_ORDER = (
    "w:cnfStyle",
    "w:tcW",
    "w:gridSpan",
    "w:hMerge",
    "w:vMerge",
    "w:tcBorders",
    "w:shd",
    "w:noWrap",
    "w:tcMar",
    "w:textDirection",
    "w:tcFitText",
    "w:vAlign",
    "w:hideMark",
    "w:headers",
    "w:cellIns",
    "w:cellDel",
    "w:cellMerge",
    "w:tcPrChange",
)


def _local(tag: str) -> str:
    """`{ns}tblBorders` → `w:tblBorders`（顺序表里写的是带前缀的名字）。"""
    return "w:" + tag.rsplit("}", 1)[-1] if "}" in tag else tag


def insert_ordered(parent, child, order=_PPR_ORDER):
    """按 OOXML 的元素顺序把 child 插进 parent（同名旧节点先删掉，避免出现两份）。

    返回 child，方便链式写法。**凡是手写 XML 的节点都要走这里**：append 到底
    在 Word 里看不出问题，到 WPS 里就是「格式丢了」。
    """
    tag = child.tag
    for old in parent.findall(tag):
        parent.remove(old)
    index = order.index(_local(tag)) if _local(tag) in order else len(order)
    for position, existing in enumerate(list(parent)):
        existing_index = (
            order.index(_local(existing.tag)) if _local(existing.tag) in order else len(order)
        )
        if existing_index > index:
            parent.insert(position, child)
            return child
    parent.append(child)
    return child


def set_rfonts(rpr, cn: str, en: str):
    """在 rPr 上写中英文字体，位置交给 python-docx（`w:rFonts` 必须是第一个子节点）。

    以前这里是 `rpr.append(fonts)`：字体排到了字号/颜色后面，WPS 认不出来，
    中文就退回默认字体——「字体没保留」的另一半原因。
    """
    fonts = rpr.get_or_add_rFonts()
    fonts.set(qn("w:ascii"), en)
    fonts.set(qn("w:hAnsi"), en)
    fonts.set(qn("w:eastAsia"), cn)
    return fonts


def set_font(
    run,
    cn: str = FONT_BODY[0],
    en: str = FONT_BODY[1],
    size: float = FONT_BODY[2],
    bold: bool | None = None,
    spacing: float | None = None,
    color: RGBColor | None = None,
    *,
    font: str | None = None,
):
    """设置一个 run 的字体。

    spacing：字符间距（pt），正数加宽、负数紧缩。写的是 `w:spacing/@w:val`，
    单位是 1/20 pt，所以 pt * 20。

    font：中英文字体一起指定（`set_font(run, font="Consolas")`）。模型常这么写，
    等价于 cn=en=font；给了 font 就以它为准，别再让它因为「多了一个参数」整段失败。
    """
    if font:
        cn = en = font
    run.font.name = en
    run.font.size = Pt(size)
    if bold is not None:
        # None = 保持原加粗状态：正文统一字体时不该把用户/脚本设的粗体抹掉
        run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    set_rfonts(rPr, cn, en)
    if spacing is not None:
        node = rPr.find(qn("w:spacing"))
        if node is None:
            node = OxmlElement("w:spacing")
            rPr.append(node)
        node.set(qn("w:val"), str(round(spacing * 20)))
    return run


_ALIGN_ALIASES = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "centre": WD_ALIGN_PARAGRAPH.CENTER,
    "middle": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "both": WD_ALIGN_PARAGRAPH.JUSTIFY,
    "distribute": WD_ALIGN_PARAGRAPH.DISTRIBUTE,
}


def _coerce_align(value):
    """align='center' 这种字符串也认——模型十次有八次按字符串写。"""
    if not isinstance(value, str):
        return value
    key = value.strip().lower()
    if key in _ALIGN_ALIASES:
        return _ALIGN_ALIASES[key]
    return None


def set_indent_chars(p, chars: float = 2, size: float = FONT_BODY[2]) -> None:
    """首行缩进按「字符」写：`w:firstLineChars="200"` = 首行缩进 2 字符。

    为什么不用 pt：`first_line_indent = Pt(24)` 在小四下正好两格，换成四号就变成
    1.7 格——同一份文档里字号一改，缩进就跟着错位。Word 的「特殊格式：首行缩进
    2 字符」存的就是 firstLineChars，写它才和用户手动设的完全一致。

    同时写 `w:firstLine`（twip）兜底：WPS / LibreOffice / python-docx 读的是这个。
    节点位置交给 `pPr.get_or_add_ind()`：`w:ind` 必须排在 `w:spacing` 之后、`w:jc` 之前，
    手写 append 会排到最后，WPS 会当它不存在。
    """
    ppr = p._p.get_or_add_pPr()
    ind = ppr.get_or_add_ind()
    ind.set(qn("w:firstLineChars"), str(round(chars * 100)))
    ind.set(qn("w:firstLine"), str(round(chars * size * 20)))


def set_left_indent_chars(p, chars: float, size: float = FONT_BODY[2]) -> None:
    """整段左缩进按「字符」写：`w:leftChars="200"` = 整段右移 2 字符。

    和 `set_indent_chars` 的取向一样，只是改的是 `left` 而不是 `firstLine`。
    缩进用 pt 存的话，二号字的标题缩 2 字符和五号字的正文缩 2 字符会变成同一个
    宽度——一眼就能看出两级标题没对齐。

    `chars=0` 时直接写 0，用来把素材/模板带进来的缩进清掉（粘贴来的标题常带着
    上一份文档的缩进，不清就会越贴越右）。
    """
    ppr = p._p.get_or_add_pPr()
    ind = ppr.get_or_add_ind()
    ind.set(qn("w:leftChars"), str(round(chars * 100)))
    ind.set(qn("w:left"), str(round(chars * size * 20)))


def set_para(
    p,
    line=LINE_ONE_HALF,
    indent_pt: float = 24,
    before: float = 0,
    after: float = 0,
    align=WD_ALIGN_PARAGRAPH.JUSTIFY,
    hanging: bool = False,
    *,
    size: float | None = None,
    bold: bool | None = None,
    font: str | None = None,
    cn: str | None = None,
    en: str | None = None,
    space_before: float | None = None,
    space_after: float | None = None,
    line_spacing=None,
    alignment=None,
    first_line_indent: float | None = None,
    indent_chars: float | None = None,
):
    """段落格式。

    line：浮点=倍数行距，`Pt(22)` 这类 Length=固定行距；
    indent_pt：首行缩进 pt（0 表示不缩进）；hanging=True 改为悬挂缩进（列表用）；
    indent_chars：首行缩进几个字符（2 = 空两格，中文正文的默认），优先于 indent_pt。

    宽容参数：`set_para(p, size=16, bold=True, align='center', space_after=10)`
    是模型最常写的形状（段落与字体一把梭）。这些别名照着 run 上的属性设置，
    不认的话一次误写就白跑一整轮脚本。
    """
    if space_after is not None:
        after = space_after
    if space_before is not None:
        before = space_before
    if line_spacing is not None:
        line = line_spacing
    if first_line_indent is not None:
        indent_pt = first_line_indent
    if alignment is not None:
        align = alignment
    align = _coerce_align(align)
    if align is None:
        align = WD_ALIGN_PARAGRAPH.JUSTIFY
    line = resolve_line(line)

    pf = p.paragraph_format
    pf.line_spacing = line
    if hanging:
        if indent_pt:
            pf.left_indent = Pt(indent_pt)
            pf.first_line_indent = Pt(-indent_pt)
    elif indent_chars is not None:
        set_indent_chars(p, indent_chars, size if size is not None else FONT_BODY[2])
    elif indent_pt:
        pf.first_line_indent = Pt(indent_pt)
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.alignment = align

    wants_font = size is not None or bold is not None or font or cn or en
    if wants_font:
        runs = list(p.runs)
        # 空段落没有 run：先补一个空的，否则 size/bold 会被静默丢掉，
        # 用户看到的就是「我说了 16pt 却是正文大小」。
        if not runs:
            with contextlib.suppress(Exception):
                runs = [p.add_run("")]
        for run in runs:
            set_font(
                run,
                cn=cn or font or FONT_BODY[0],
                en=en or font or FONT_BODY[1],
                size=size if size is not None else FONT_BODY[2],
                bold=bold,
            )
    return p


def apply_body(
    doc,
    cn: str = FONT_BODY[0],
    en: str = FONT_BODY[1],
    size: float = FONT_BODY[2],
    line=LINE_ONE_HALF,
    indent_pt: float | None = None,
    include_empty: bool = False,
    *,
    indent_chars: float | None = 2,
) -> int:
    """正文段落统一格式，返回处理过的段落数。

    只动 style=Normal 的段落：标题、题注、表格里的段落保持原样，
    避免把「Heading 1」也拉成 12pt。空段落默认跳过（不参与缩进与行距重置）。

    默认首行缩进 2 字符（中文正文的「空两格」）；要顶格就传 `indent_chars=0`，
    想按 pt 精确控制就传 `indent_pt=`（两者都给时 indent_pt 优先）。
    """
    doc = ensure_doc(doc)
    touched = 0
    for p in doc.paragraphs:
        if p.style.name != "Normal":
            continue
        if not include_empty and not p.text.strip():
            continue
        if indent_pt is not None:
            set_para(p, line=line, indent_pt=indent_pt)
        else:
            set_para(p, line=line, indent_pt=0, indent_chars=indent_chars, size=size)
        for r in p.runs:
            set_font(r, cn, en, size)
        touched += 1
    return touched


def _heading_map_for(scale: str | None) -> dict[str, tuple[str, str, float, bool]]:
    """按刻度取四级标题的字体与字号。

    字体也跟着刻度走（公文二级是楷体、商务报告二级是黑体），所以不能只换字号——
    只换字号会让「同一套刻度」在不同文档里长得不一样。
    """
    if not scale:
        return _DEFAULT_HEADING_MAP
    specs = heading_specs(scale)
    return {f"Heading {index}": spec for index, spec in enumerate(specs, start=1)}


def apply_headings(doc, mapping: dict | None = None, scale: str | None = None) -> int:
    """按层级设置标题样式，返回生效的层级数。

    mapping 形如 {"Heading 1": ("黑体", "Arial", 16, True)}；
    `st.element.rPr` 在部分模板里是 None，这里用 get_or_add_rPr 兜住。

    只想定「这套标题多大」而不想逐个报字号时传 scale（report / gongwen / thesis / compact）。
    """
    doc = ensure_doc(doc)
    mapping = mapping or _heading_map_for(scale)
    applied = 0
    for name, (cn, en, size, bold) in mapping.items():
        try:
            style = doc.styles[name]
        except KeyError:  # 模板里没有这个样式名就跳过，不要中断整个脚本
            continue
        style.font.name = en
        style.font.size = Pt(size)
        style.font.bold = bold
        set_rfonts(style.element.get_or_add_rPr(), cn, en)
        # 小节标题一律左对齐、不吃首行缩进：居中是「文档大标题」的专属信号。
        # 样式是从 Normal 继承的（Normal 两端对齐），不显式钉住，长标题换行时会被拉开字距，
        # 看着就像「居中的大字」——用户会以为分不清哪一行才是全文标题。
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
        style.paragraph_format.first_line_indent = Pt(0)
        applied += 1
    return applied


def _preset_key(name: str) -> str:
    """预设名的宽容解析。

    模型写出 `set_page(doc, preset="PAGE_DEFAULT")` 的频率不低——它把常量名当字符串传了。
    这种错看起来像「不支持这种模板」，其实只是大小写和前缀；就地认掉，别让它白跑一趟。
    """
    key = str(name).strip().lower()
    for prefix in ("page_", "page-", "page "):
        if key.startswith(prefix):
            key = key[len(prefix) :]
            break
    return key.replace("-", "_").replace(" ", "")


def set_page(doc, spec: dict | str | None = None, preset: str | None = None) -> int:
    """设置纸张与页边距，返回节数。

    spec 可以传 PAGE_* 字典，也可以直接传预设名（"default"/"gongwen"/"thesis"…，
    也认 "PAGE_DEFAULT" 这种常量名）；
    也接受 `set_page(doc, preset="gongwen")` 这种写法——模型经常这么写。
    """
    doc = ensure_doc(doc)
    name = preset if isinstance(preset, str) else (spec if isinstance(spec, str) else None)
    if name is not None:
        key = _preset_key(name)
        if key not in PAGE_PRESETS:
            raise KeyError(
                f"未知页面预设：{name}；可用：{'、'.join(PAGE_PRESETS)}"
                "（传预设名或 PAGE_* 常量本身，不要传字符串 'PAGE_XXX' 以外的自造名）"
            )
        spec = PAGE_PRESETS[key]
    spec = spec or PAGE_DEFAULT
    if not isinstance(spec, dict):
        raise TypeError(f"页面参数应为 PAGE_* 字典或预设名，收到 {type(spec).__name__}")
    count = 0
    for sec in doc.sections:
        sec.page_width = spec["width"]
        sec.page_height = spec["height"]
        sec.top_margin = spec["top"]
        sec.bottom_margin = spec["bottom"]
        sec.left_margin = spec["left"]
        sec.right_margin = spec["right"]
        count += 1
    return count


# --------------------------------------------------------------------------- #
# 表格
# --------------------------------------------------------------------------- #


def _set_borders(table, edges: dict[str, tuple[str, int]]) -> None:
    """写 `w:tblBorders`：edges 形如 {"top": ("single", 12), "insideH": ("nil", 0)}。"""
    tblPr = table._tbl.tblPr
    borders = tblPr.find(qn("w:tblBorders"))
    if borders is None:
        borders = insert_ordered(tblPr, OxmlElement("w:tblBorders"), _TBLPR_ORDER)
    for edge, (val, size) in edges.items():
        node = borders.find(qn(f"w:{edge}"))
        if node is None:
            node = OxmlElement(f"w:{edge}")
            borders.append(node)
        node.set(qn("w:val"), val)
        node.set(qn("w:sz"), str(size))
        node.set(qn("w:color"), "000000")


def _bottom_border(paragraph, size: int = 8) -> None:
    """给段落加下框线（三线表的栏目线）。"""
    pPr = paragraph._p.get_or_add_pPr()
    pBdr = pPr.find(qn("w:pBdr"))
    if pBdr is None:
        pBdr = insert_ordered(pPr, OxmlElement("w:pBdr"), _PPR_ORDER)
    bottom = pBdr.find(qn("w:bottom"))
    if bottom is None:
        bottom = OxmlElement("w:bottom")
        pBdr.append(bottom)
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:color"), "000000")


def add_table_simple(
    doc,
    header,
    rows,
    style: str = "triple",
    font=FONT_TABLE,
    header_fill: str | None = None,
    repeat: bool = True,
):
    """插入表格：style="triple" 三线表 / "grid" 全框线 / "zebra" 隔行浅底 / "plain" 无框线。

    表头加粗并可选浅灰底纹，跨页自动重复表头；列宽按页面可用宽度均分。
    样式名写成同义词也认（`TABLE_STYLES`：「三线表」「全部框线」「斑马纹」「无边框」）。
    """
    doc = ensure_doc(doc)
    style = TABLE_STYLES.get(str(style).strip().lower(), style)
    cols = len(header)
    table = doc.add_table(rows=len(rows) + 1, cols=cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    for j, title in enumerate(header):
        cell = table.rows[0].cells[j]
        cell.text = str(title)
        for paragraph in cell.paragraphs:
            set_para(paragraph, line=LINE_SINGLE, indent_pt=0, align=WD_ALIGN_PARAGRAPH.CENTER)
            for run in paragraph.runs:
                set_font(run, font[0], font[1], font[2], bold=True)
        if header_fill:
            shade_cell(cell, header_fill)

    for i, row in enumerate(rows, start=1):
        for j in range(cols):
            value = row[j] if j < len(row) else ""
            cell = table.rows[i].cells[j]
            cell.text = str(value)
            for paragraph in cell.paragraphs:
                set_para(paragraph, line=LINE_SINGLE, indent_pt=0, align=WD_ALIGN_PARAGRAPH.LEFT)
                for run in paragraph.runs:
                    set_font(run, font[0], font[1], font[2])

    if style == "grid":
        _set_borders(
            table,
            {
                "top": ("single", 4),
                "bottom": ("single", 4),
                "left": ("single", 4),
                "right": ("single", 4),
                "insideH": ("single", 4),
                "insideV": ("single", 4),
            },
        )
    elif style == "zebra":
        # 隔行浅底：框线照样画全，但偶数行铺一层极浅的灰——列一多，眼睛就靠这层
        # 色带认行，否则读到第三列必定串行。
        _set_borders(
            table,
            {
                "top": ("single", 4),
                "bottom": ("single", 4),
                "left": ("single", 4),
                "right": ("single", 4),
                "insideH": ("single", 4),
                "insideV": ("single", 4),
            },
        )
        for index, row in enumerate(table.rows[1:], start=1):
            if index % 2 == 0:
                for cell in row.cells:
                    shade_cell(cell, "F5F7FA")
    elif style == "triple":
        # 三线表：只留顶线、栏目线、底线，其余置 nil（不是 sz=0，Word 里 0 仍会画细线）
        _set_borders(
            table,
            {
                "top": ("single", 12),
                "bottom": ("single", 12),
                "left": ("nil", 0),
                "right": ("nil", 0),
                "insideH": ("nil", 0),
                "insideV": ("nil", 0),
            },
        )
        for cell in table.rows[0].cells:
            for paragraph in cell.paragraphs:
                _bottom_border(paragraph, size=8)
    elif style == "plain":
        _set_borders(
            table,
            {edge: ("nil", 0) for edge in ("top", "bottom", "left", "right", "insideH", "insideV")},
        )

    if repeat and len(table.rows) > 1:
        repeat_header(table.rows[0])
    return table


def repeat_header(row) -> None:
    """表头跨页重复（`w:tblHeader`）。"""
    trPr = row._tr.get_or_add_trPr()
    node = OxmlElement("w:tblHeader")
    node.set(qn("w:val"), "true")
    trPr.append(node)


def shade_cell(cell, fill: str = "EEF1F6") -> None:
    """单元格底纹（表头浅灰）。`w:shd` 在 tcPr 里排在 tcBorders 之后、noWrap 之前。"""
    tcPr = cell._tc.get_or_add_tcPr()
    shd = tcPr.find(qn("w:shd"))
    if shd is None:
        shd = insert_ordered(tcPr, OxmlElement("w:shd"), _TCPR_ORDER)
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)


# --------------------------------------------------------------------------- #
# 文本替换
# --------------------------------------------------------------------------- #


def _replace_in_paragraph(paragraph, old: str, new: str) -> int:
    hits = 0
    for run in paragraph.runs:
        if old in run.text:
            hits += run.text.count(old)
            run.text = run.text.replace(old, new)
    if hits:
        return hits
    # 跨 run 的情况（Word 常把一句话拆成多个 run）：整段合并回第一个 run，
    # 段落与首个 run 的格式保留，代价是段内局部加粗会丢——比「替换不掉」可接受。
    if old in paragraph.text:
        hits = paragraph.text.count(old)
        merged = paragraph.text.replace(old, new)
        runs = paragraph.runs
        if runs:
            runs[0].text = merged
            for run in runs[1:]:
                run.text = ""
        return hits
    return 0


def replace_text(doc, old: str, new: str) -> int:
    """全文替换（正文 + 表格 + 页眉页脚），返回替换次数。

    old 为空字符串时直接返回 0：空串在 Python 里「处处匹配」，会把整段文字写坏。
    """
    if not old:
        return 0
    doc = ensure_doc(doc)
    total = 0
    for paragraph in doc.paragraphs:
        total += _replace_in_paragraph(paragraph, old, new)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    total += _replace_in_paragraph(paragraph, old, new)
    for section in doc.sections:
        for part in (section.header, section.footer):
            for paragraph in part.paragraphs:
                total += _replace_in_paragraph(paragraph, old, new)
    return total


# --------------------------------------------------------------------------- #
# 页码 / 备份 / 只读审计
# --------------------------------------------------------------------------- #


def add_page_number(target, align: str = "center", prefix: str = "", suffix: str = "") -> int:
    """页脚插入 PAGE 域（python-docx 不会自动算页码，Word/WPS 打开后由域刷新）。

    target 可以整份 Document（每节都加）或单个 section——模型写 `add_page_number(doc)`
    比 `add_page_number(doc.sections[0])` 自然得多，而写错 `doc.footer` 就直接报
    `'Document' object has no attribute 'footer'`。返回处理过的节数。
    """
    sections = getattr(target, "sections", None)
    if sections is None:
        sections = [target]  # 传进来的是单个 section
    count = 0
    for section in sections:
        _add_page_number_to_section(section, align=align, prefix=prefix, suffix=suffix)
        count += 1
    return count


def _add_page_number_to_section(
    section, align: str = "center", prefix: str = "", suffix: str = ""
) -> None:
    paragraph = (
        section.footer.paragraphs[0]
        if section.footer.paragraphs
        else section.footer.add_paragraph()
    )
    paragraph.alignment = {
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "居中": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
        "右": WD_ALIGN_PARAGRAPH.RIGHT,
        "left": WD_ALIGN_PARAGRAPH.LEFT,
        "左": WD_ALIGN_PARAGRAPH.LEFT,
    }.get(str(align or "center").strip().lower(), WD_ALIGN_PARAGRAPH.CENTER)
    if prefix:
        paragraph.add_run(prefix)
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = "PAGE"
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._r.append(begin)
    run._r.append(instr)
    run._r.append(end)
    if suffix:
        paragraph.add_run(suffix)


def backup(src: str, out_dir: str) -> str:
    """修改前备份原件：<名>_备份_<时间戳>.docx，写到 out_dir（不碰原件）。"""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name, ext = os.path.splitext(os.path.basename(src))
    target = os.path.join(out_dir, f"{name}_备份_{stamp}{ext}")
    shutil.copy2(src, target)
    return target


def read_report(doc) -> dict:
    """只读审计：段落数、字符数、表格数、各样式使用情况。

    改之前跑一次、改之后跑一次，两份报告对比就是「这次改了什么」。
    """
    doc = ensure_doc(doc)
    styles: dict[str, int] = {}
    chars = 0
    for paragraph in doc.paragraphs:
        chars += len(paragraph.text)
        styles[paragraph.style.name] = styles.get(paragraph.style.name, 0) + 1
    return {
        "paragraphs": len(doc.paragraphs),
        "chars": chars,
        "tables": len(doc.tables),
        "sections": len(doc.sections),
        "styles": styles,
    }
