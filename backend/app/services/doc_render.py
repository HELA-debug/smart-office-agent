"""docx 版式引擎：一份 Markdown 正文 → 排好版的 Word 文档 / 预览 HTML。

**为什么要有这一层。** 以前 `doc.generate_report` 直接用 `add_heading(level=1)` +
`add_paragraph()` 往默认模板里写，出来的是「宋体 12pt + 蓝色 Calibri 标题 + 零间距」，
而同一份内容在界面预览里（`.prose-docx`）却是 22px 标题、18px 小节、27px 行高。
同一个文件在预览里好看、下载下来难看，用户会以为交付的东西是凑的。

这里的版式照着国内办公文档的通行写法刻：
    大标题 宋体二号、居中、加粗（全文最大）｜ 一级小节 黑体三号 ｜ 二级 黑体四号 ｜
    三级 宋体小四加粗 ｜ 正文 宋体小四、1.5 倍行距、首行缩进 2 字符 ｜ 表格 宋体五号
字号、字体、行距、缩进这些「词」都在 `services/doc_lexicon.py` 一张表里，
改字号或加字体只改那一处，预览与下载不会各说一套。

**输入为什么是 Markdown 而不是固定小节表。** 固定六节（摘要/进展/数据/风险/计划/来源）
能装下「周报」，装不下「结论先行 + 一张进度表 + 一件要拍板的事」这种真给人看的东西。
模型读完全文，最清楚该分几节、哪一节该是表格；让它直接写 Markdown，这里负责把
标题层级、列表、表格、引用、图注如实还原成 Word 结构，版式才不会把它写的东西压平。

一份 blocks 同时喂给 docx 和 HTML 预览：两条路走同一份结构，才不会出现
「预览里有表格、下载的 Word 里表格变成了几行竖线」。
"""

from __future__ import annotations

import contextlib
import html
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Length, Pt, RGBColor

from .doc_lexicon import (
    FONT_ROLES,
    FONTS,
    HEADING_SCALES,
    LINE_ONE_HALF,
    NUMBERING_SCHEMES,
    heading_indents,
    resolve_line,
    resolve_numbering,
    resolve_size,
)
from .docx_utils import (
    _PPR_ORDER,
    _TBLPR_ORDER,
    _TCPR_ORDER,
    insert_ordered,
    set_indent_chars,
    set_left_indent_chars,
    set_rfonts,
)

__all__ = [
    "PRESETS",
    "Block",
    "blocks_from_sections",
    "blocks_to_html",
    "parse_markdown",
    "preset_with_style",
    "render_docx_blocks",
    "resolve_preset",
]


# --------------------------------------------------------------------------- #
# 版式预设
# --------------------------------------------------------------------------- #
INK = RGBColor(0x1F, 0x23, 0x28)  # 标题：接近纯黑，屏幕上不刺眼
BODY = RGBColor(0x33, 0x38, 0x3F)  # 正文
MUTED = RGBColor(0x6B, 0x72, 0x80)  # 副标题 / 图注 / 引用
RULE = "D0D5DD"  # 表格线
HEAD_FILL = "F2F4F7"  # 表头底纹（和预览的 surface-sunken 同色系）

_ALIGN_MAP = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


@dataclass(frozen=True)
class Preset:
    """一套版式。字号是 pt，边距是 cm。

    字段按「从上到下」排：大标题 → 四级小节 → 正文 → 表格/图注 → 页面。
    字号一律按号数从 `services/doc_lexicon.py` 取（`resolve_size("小四")`），
    这里不写裸数字——否则「12pt」还会在别处出现第二个版本。
    """

    name: str
    cn_font: str = FONTS[FONT_ROLES["body"]][0]
    en_font: str = FONTS[FONT_ROLES["body"]][1]
    # 大标题：居中、加粗、全文最大（「最大」由 __post_init__ 兜住）
    title_font: str = FONT_ROLES["title"]
    title_size: float = 22.0
    title_align: str = "center"
    # 副标题（大标题下面那行小字）：比正文大一档、黑字、居中。
    # 0 是哨兵，构造时按正文 +2pt 补上——换版式（公文三号正文）时跟着一起变。
    subtitle_size: float = 0.0
    # 小节标题：一级 → 四级
    heading_fonts: tuple[str, str, str, str] = ("黑体", "黑体", "宋体", "宋体")
    heading_sizes: tuple[float, float, float, float] = (16.0, 14.0, 12.0, 12.0)
    # 小节标题对齐：左对齐、从版心左缘起行。
    # 「非正文一律居中」指的是**文首标题块**——大标题、副标题、实验名称/姓名学号
    # 这类信息行。小节标题不在此列：读者靠它定位「这一节从哪开始」，居中等于每节
    # 都要把视线拉回页面中间重找起行位置（用户给的样例文档就是这个排法）。
    heading_align: str = "left"
    # 正文：小四、1.5 倍行距、首行缩进 2 字符（中文的「空两格」）
    body_size: float = 12.0
    body_line: float | Length = LINE_ONE_HALF
    body_indent: float = 2.0
    # 正文对齐：两端对齐。中文排版里这是正式稿的默认——每行都撑满版心，
    # 右侧收成一条齐边；左对齐会把余量全堆在右边，长稿一页页翻过去右边缘毛糙。
    # 中文的字距本来就由标点与汉字均分，两端对齐拉开的那点间隙几乎看不出来，
    # 不像西文那样会出现「河流」。
    # 小节标题不受影响：它们各自带 left（见 apply_headings / blocks_to_html），
    # 否则标题换行时也会被拉成满行，字号再大就很怪。
    body_align: str = "justify"
    # 字型：正文要不要加粗 / 斜体 / 下划线（WPS 工具栏上的 B I U）
    body_bold: bool = False
    body_italic: bool = False
    body_underline: bool = False
    body_after: float = 6.0
    # 小节标题要不要逐级缩进（一级顶格，往下每级 +1 字符）。
    # 公文是「整篇顶格」的排法（GB/T 9704 强制），这里关掉；
    # 缩进量本身在 doc_lexicon.NUMBERING_INDENTS。
    heading_indent: bool = True
    # 预览里要不要整篇缩一档（字更小、行更紧）：只给紧凑版式用。
    # Word 那边的密度是字号/行距/页边距给的，预览得用 CSS 同步，否则两个版式
    # 打开来一模一样，用户会以为「紧凑」没生效。
    dense: bool = False
    table_size: float = 10.5
    note_size: float = 9.0
    margin_top: float = 2.2
    margin_bottom: float = 2.2
    margin_left: float = 2.4
    margin_right: float = 2.4
    head_fill: str = HEAD_FILL

    def __post_init__(self) -> None:
        """「大标题一定要是全文最大的」——不靠人记，构造时就保证。"""
        largest = max(self.body_size, self.table_size, *self.heading_sizes)
        if self.title_size <= largest:
            object.__setattr__(self, "title_size", largest + 2.0)
        if not self.subtitle_size:
            # 副标题 = 正文字号 + 2pt（小四 → 四号）。不能跟正文同号：字号一样时
            # 只能靠居中区分，一眼看过去像「正文第一段被居中了」。
            object.__setattr__(self, "subtitle_size", self.body_size + 2.0)


def _heading_fonts(scale: str) -> tuple[str, str, str, str]:
    rows = HEADING_SCALES[scale]
    return (rows[0][0], rows[1][0], rows[2][0], rows[3][0])


def _heading_sizes(scale: str) -> tuple[float, float, float, float]:
    rows = HEADING_SCALES[scale]
    return (
        resolve_size(rows[0][1]),
        resolve_size(rows[1][1]),
        resolve_size(rows[2][1]),
        resolve_size(rows[3][1]),
    )


PRESETS: dict[str, Preset] = {
    # 默认：商务报告 / 周报 / 纪要 / 方案。宋体正文（打印出来最像正式稿），
    # 标题宋体二号居中，小节黑体，正文小四、1.5 倍行距、两端对齐、首行缩进两格。
    "report": Preset(
        name="report",
        title_size=resolve_size("二号"),
        heading_fonts=_heading_fonts("report"),
        heading_sizes=_heading_sizes("report"),
        body_size=resolve_size("小四"),
        body_line=LINE_ONE_HALF,
        body_indent=2.0,
        table_size=resolve_size("五号"),
        note_size=resolve_size("小五"),
    ),
    # 党政公文（GB/T 9704 的字号与边距，正文仿宋三号）。
    "gongwen": Preset(
        name="gongwen",
        cn_font=FONTS["仿宋_GB2312"][0],
        en_font=FONTS["仿宋_GB2312"][1],
        title_size=resolve_size("二号"),
        heading_fonts=_heading_fonts("gongwen"),
        heading_sizes=_heading_sizes("gongwen"),
        body_size=resolve_size("三号"),
        body_line=LINE_ONE_HALF,
        body_indent=2.0,
        body_after=0.0,
        # 正文两端对齐、整篇顶格（GB/T 9704：每行 28 字要对齐版心）。对齐方式和默认
        # 版式一致，就不再重复声明——写两遍只会让人怀疑哪一份生效。
        # GB/T 9704：各级标题一律顶格、左起，缩进和居中都算「格式不合规」
        heading_indent=False,
        table_size=resolve_size("三号"),
        note_size=resolve_size("小五"),
        margin_top=3.7,
        margin_bottom=3.5,
        margin_left=2.8,
        margin_right=2.6,
    ),
    # 紧凑：资料、说明书、附录这类「一页要装下更多」的文档。
    # 排版规则和默认版式完全一致——标题逐级内缩、正文首行缩进两格。读者认的是同一套
    # 层级，换了版式照样能一眼找到段落从哪起；密度是靠字号（五号）、行距（1.25 倍）、
    # 段距（4pt）和更小的页边距（2cm）挤出来的，不是靠把缩进和层级抹平。
    "compact": Preset(
        name="compact",
        title_size=resolve_size("小二"),
        heading_fonts=_heading_fonts("compact"),
        heading_sizes=_heading_sizes("compact"),
        body_size=resolve_size("五号"),
        body_line=1.25,
        body_indent=2.0,
        body_after=4.0,
        dense=True,
        table_size=resolve_size("小五"),
        note_size=resolve_size("小五"),
        margin_top=2.0,
        margin_bottom=2.0,
        margin_left=2.0,
        margin_right=2.0,
    ),
}


#: 版式的口语叫法。「用户说要那种密一点的」，模型传 dense / 密排 也能落到紧凑版式。
#:
#: 收词的口径是「用户会怎么描述这份东西的密度」，不是「版式的别名表」：有人按观感说
#: （紧凑 / 扁平 / 平铺 / 密），有人按文件类型说（资料 / 说明书 / 手册 / 附录 / 速查），
#: 有人直接甩英文（dense / tight / manual）。这几条都会被模型原样塞进 layout，
#: 认不出就落回默认版式——那是「用户明明说了要密的，出来还是正常版」的静默走样。
_PRESET_ALIASES = {
    "default": "report",
    "商务": "report",
    "报告": "report",
    "正式": "report",
    "公文": "gongwen",
    "党政": "gongwen",
    "gov": "gongwen",
    "紧凑": "compact",
    "精简": "compact",
    "扁平": "compact",
    "平铺": "compact",
    "密排": "compact",
    "密集": "compact",
    "高密度": "compact",
    "flat": "compact",
    "dense": "compact",
    "tight": "compact",
    # 按文件类型说的：说明书、手册、附录、速查表本来就该按紧凑排
    "资料": "compact",
    "说明书": "compact",
    "手册": "compact",
    "附录": "compact",
    "速查": "compact",
    "manual": "compact",
    "handbook": "compact",
    "appendix": "compact",
}


def resolve_preset(name: str | None) -> str:
    """版式名 → PRESETS 的键；认不出落回 report（默认那套最主流）。

    落回默认要在这里做掉，不能把原词透传给调用方去 `.get(..., report)`——
    那样 `resolve_preset("顶格")` 会返回「顶格」这个不存在的键，调用方各自兜底，
    谁都说不清「版式到底定成了什么」。
    """
    key = str(name or "").strip().lower()
    resolved = _PRESET_ALIASES.get(key, key)
    return resolved if resolved in PRESETS else "report"


#: 「文档格式」里那些对齐叫法 → WD_ALIGN_PARAGRAPH 的键。
_STYLE_ALIGN = {
    "justify": "justify",
    "both": "justify",
    "两端": "justify",
    "两端对齐": "justify",
    "left": "left",
    "左": "left",
    "左对齐": "left",
    "center": "center",
    "居中": "center",
    "居中对齐": "center",
    "right": "right",
    "右对齐": "right",
}

# 字型（B / I / U）的三态词表。数字 1 / 0 不用单列：`_flag` 先把值转成字符串再查，
# "1" / "0" 已经覆盖了；而且在 set 里 `True == 1`，写进去只会被 ruff 判成重复项。
_STYLE_TRUE = {True, "1", "true", "yes", "on", "是", "开"}
_STYLE_FALSE = {False, "0", "false", "no", "off", "否", "关"}


def _flag(value: Any) -> bool | None:
    """三态布尔：认不出（没给）返回 None，别把「用户没点」当成「关掉」。"""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    key = str(value).strip().lower()
    if key in _STYLE_TRUE:
        return True
    if key in _STYLE_FALSE:
        return False
    return None


def preset_with_style(layout: Preset, style: dict[str, Any] | None) -> Preset:
    """把用户这一轮点的「文档格式」叠到版式预设上。

    只覆盖真正给了值的字段——用户只改字号，字体、行距、缩进仍跟预设走。
    这几项就是 WPS 工具栏上最常动的那一排（字体 / 字号 / 字型 / 行距 / 首行缩进 /
    对齐），给的词也照 WPS 的叫法收：既能传「小四」「1.5 倍」「左对齐」，
    也认 12.0 / 1.5 / "left" 这种规整值。
    """
    if not style:
        return layout
    patch: dict[str, Any] = {}

    cn = str(style.get("font") or style.get("font_cn") or "").strip()
    if cn in FONTS:
        patch["cn_font"], patch["en_font"] = FONTS[cn]
    en = str(style.get("font_en") or "").strip()
    if en:
        # 西文字体单独给时只换西文那一半：中文字体仍按上面（或预设）走
        patch["en_font"] = en

    size = style.get("size")
    if isinstance(size, (int, float)) and size > 0:
        patch["body_size"] = float(size)
    elif isinstance(size, str) and size.strip():
        with contextlib.suppress(KeyError, ValueError):
            patch["body_size"] = resolve_size(size.strip())

    line = style.get("line")
    if line not in (None, ""):
        with contextlib.suppress(ValueError, TypeError):
            patch["body_line"] = resolve_line(line)

    indent = style.get("indent_chars")
    if indent is not None and indent != "":
        with contextlib.suppress(TypeError, ValueError):
            patch["body_indent"] = max(0.0, float(indent))

    align = str(style.get("align") or "").strip().lower()
    if align in _STYLE_ALIGN:
        patch["body_align"] = _STYLE_ALIGN[align]

    for name, field_name in (
        ("bold", "body_bold"),
        ("italic", "body_italic"),
        ("underline", "body_underline"),
    ):
        flag = _flag(style.get(name))
        if flag is not None:
            patch[field_name] = flag

    return replace(layout, **patch) if patch else layout


# --------------------------------------------------------------------------- #
# 结构：一份文档 = 一串块
# --------------------------------------------------------------------------- #
@dataclass
class Block:
    """块级元素。kind 取值见 `_KINDS`。"""

    kind: str
    text: str = ""
    level: int = 0
    items: list[str] = field(default_factory=list)
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    caption: str = ""
    data: bytes | None = None


_KINDS = ("heading", "paragraph", "bullet", "number", "table", "quote", "figure", "rule", "code")


def _split_row(line: str) -> list[str]:
    """`| a | b |` → ["a", "b"]；容忍首尾没有竖线、单元格里带转义竖线。"""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    cells = re.split(r"(?<!\\)\|", text)
    return [cell.replace("\\|", "|").strip() for cell in cells]


_TABLE_SEP = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")


def _is_table_sep(line: str) -> bool:
    return bool(_TABLE_SEP.match(line)) and "-" in line


# 手写的中文序号标题。模型（和用户的原稿）经常不用 `##`，直接写「一、一句话结论」——
# 那是标题，不是「一、」开头的列表项。靠「短 + 不带句读」区分：列表项是句子，
# 会带逗号或句号，长度也压不住。
_CN_HEADING = re.compile(r"^[一二三四五六七八九十]{1,3}[、.．]\s*[^，。；！？,;]{1,22}$")
_CN_SUBHEADING = re.compile(r"^[（(][一二三四五六七八九十]{1,3}[)）]\s*[^，。；！？,;]{1,22}$")

_BULLET_LINE = re.compile(r"^([-*·•●○])\s+(.*)$")
_NUMBER_LINE = re.compile(r"^(?:\(?(\d{1,2})[.)）、]|([一二三四五六七八九十]{1,3})[、.])\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")

#: 句子已经收尾的标点。上一条以它结尾 → 下一行是新的一段，不是折行。
_SENTENCE_END = tuple("。！？；!?;…”』」）)")


def _is_wrapped_continuation(previous: str, candidate: str) -> bool:
    """下一行是上一条的折行，还是一段新内容？

    模型写长条目时常把一句折成两三行，折点落在逗号上；而新的一段一定是从
    上一句句号之后开始的。按「上一条收没收句」判断，比按缩进判断可靠——
    模型折行时经常不给缩进。
    """
    if candidate.startswith(("|", ">", "```", "#")):
        return False
    if _HEADING.match(candidate) or _BULLET_LINE.match(candidate) or _NUMBER_LINE.match(candidate):
        return False
    return not previous.rstrip().endswith(_SENTENCE_END)


def _strip_bullet_prefix(text: str) -> str:
    """去掉行首自带的圆点（「· 仿真平台：…」「• xxx」）。

    有的模型（和不少原稿）喜欢自己敲一个「· 」当作列表符号。这个符号在中文
    正式稿里没有位置——正文靠首行缩进两格分句，所以渲染前统一剥掉；
    但要给圆点的场合（真清单）由调用方自己决定，不在解析层偷偷加回来。
    """
    return re.sub(r"^\s*[·•●○▪]\s*", "", text or "")


def _append_items_or_paragraphs(blocks: list[Block], items: list[str]) -> None:
    """一组 `- ` 条目 → 一串正文段落（无项目符号）。

    中文正式稿里没有「· 」这一层：它的位置本来就由「首行缩进两格」顶着。
    以前只在「这一组全是长句」时才转段落，一组里混进一条短句，整组就打回圆点，
    同一份稿子上一节是段落、下一节是圆点，读者会以为排版坏了。现在一律排成
    段落——真要列清单的内容，本来就该写成表格。
    """
    blocks.extend(
        Block("paragraph", text=_strip_bullet_prefix(item))
        for item in items
        if (item or "").strip()
    )


def parse_markdown(text: str) -> list[Block]:
    """把 Markdown 切成块。

    只认「写文档真会用到的」那几样：标题、段落、有序/无序列表、表格、引用、
    分隔线、代码块。不追求完整 Markdown 兼容——多认一种就等于多一种模型能写、
    而渲染会静默丢掉的东西。认不出的行按正文段落处理，至少不丢字。
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    index = 0
    total = len(lines)

    while index < total:
        raw = lines[index]
        line = raw.strip()

        if not line:
            index += 1
            continue

        # 代码块：围栏里原样保留，不解析表格与标题
        if line.startswith("```"):
            index += 1
            buffer: list[str] = []
            while index < total and not lines[index].strip().startswith("```"):
                buffer.append(lines[index].rstrip())
                index += 1
            index += 1
            blocks.append(Block("code", text="\n".join(buffer)))
            continue

        heading = _HEADING.match(line)
        if heading:
            blocks.append(
                Block("heading", text=heading.group(2).strip(), level=len(heading.group(1)))
            )
            index += 1
            continue

        if _CN_SUBHEADING.match(line):
            blocks.append(Block("heading", text=line, level=3))
            index += 1
            continue

        if _CN_HEADING.match(line):
            # text 保留原文编号：自动编号那一层检测到已有编号就不会再加一层
            blocks.append(Block("heading", text=line, level=2))
            index += 1
            continue

        if re.fullmatch(r"(?:-{3,}|\*{3,}|_{3,})", line):
            blocks.append(Block("rule"))
            index += 1
            continue

        if line.startswith("|") and index + 1 < total and _is_table_sep(lines[index + 1]):
            header = _split_row(line)
            index += 2
            rows: list[list[str]] = []
            while index < total and lines[index].strip().startswith("|"):
                rows.append(_split_row(lines[index]))
                index += 1
            width = len(header)
            rows = [(row + [""] * width)[:width] for row in rows]
            blocks.append(Block("table", header=header, rows=rows))
            continue

        if line.startswith(">"):
            quoted: list[str] = []
            while index < total and lines[index].strip().startswith(">"):
                quoted.append(lines[index].strip().lstrip(">").strip())
                index += 1
            blocks.append(Block("quote", text="\n".join(item for item in quoted if item)))
            continue

        if _BULLET_LINE.match(line):
            items: list[str] = []
            while index < total:
                candidate = lines[index].strip()
                matched = _BULLET_LINE.match(candidate)
                if matched:
                    items.append(matched.group(2).strip())
                elif candidate and items and candidate.startswith(("  ", "\t")):
                    # 缩进的续行属于上一条，不另起一项
                    items[-1] += candidate.strip()
                elif not candidate:
                    # 空行不结束列表：一条条之间空一行在中文稿里很常见
                    if index + 1 < total and _BULLET_LINE.match(lines[index + 1].strip()):
                        index += 1
                        continue
                    break
                else:
                    break
                index += 1
            _append_items_or_paragraphs(blocks, items)
            continue

        numbered = _NUMBER_LINE.match(line)
        if numbered:
            items = []
            while index < total:
                candidate = lines[index].strip()
                matched = _NUMBER_LINE.match(candidate)
                if matched:
                    items.append(matched.group(3).strip())
                elif candidate and items and _is_wrapped_continuation(items[-1], candidate):
                    # 这一条自己被折成了两三行：并回上一条。
                    # 判据是「上一条还没收句」——折行处通常停在逗号上，而下一段
                    # 一定是从句号后面开始的。拼接不加空格：中文换行处本来就是同一个词。
                    items[-1] += candidate
                elif not candidate:
                    if index + 1 < total and _NUMBER_LINE.match(lines[index + 1].strip()):
                        index += 1
                        continue
                    break
                else:
                    break
                index += 1
            blocks.append(Block("number", items=[_strip_bullet_prefix(i) for i in items]))
            continue

        # 普通段落：连续的行合成一段（中文换行不加空格）
        paragraph: list[str] = [line]
        index += 1
        while index < total:
            candidate = lines[index].strip()
            if (
                not candidate
                or _HEADING.match(candidate)
                or candidate.startswith(("|", ">", "```"))
            ):
                break
            if _BULLET_LINE.match(candidate) or _NUMBER_LINE.match(candidate):
                break
            paragraph.append(candidate)
            index += 1
        blocks.append(Block("paragraph", text=_strip_bullet_prefix("".join(paragraph))))

    return blocks


def _paragraphs_as_blocks(paragraphs: Sequence[str]) -> list[Block]:
    """把「一串句子」还原成块：一行一段，`- ` 条目也当段落（去掉行首符号）。

    周报骨架（摘要/进展/风险…）给的是句子列表，里面混着「- 」条目；一条一段，
    别挤成一坨，也别排成一串圆点。
    """
    blocks: list[Block] = []
    for text in paragraphs:
        item = (text or "").strip()
        if not item:
            continue
        matched = _BULLET_LINE.match(item)
        blocks.append(
            Block(
                "paragraph",
                text=_strip_bullet_prefix(matched.group(2).strip() if matched else item),
            )
        )
    return blocks


def blocks_from_sections(sections: Sequence[dict[str, Any]]) -> list[Block]:
    """旧的 DocSection 列表 → blocks（没给 Markdown 正文时的兜底路径）。"""
    blocks: list[Block] = []
    for section in sections:
        heading = str(section.get("heading") or "").strip()
        if heading:
            blocks.append(Block("heading", text=heading, level=2))
        paragraphs = [str(item) for item in section.get("paragraphs") or []]
        # 一节里的段落一律一行一段：它们不是清单，前面挂圆点反而像待办
        blocks.extend(_paragraphs_as_blocks(paragraphs))
        for figure in section.get("images") or []:
            data = figure.get("data")
            if isinstance(data, bytes) and data:
                blocks.append(
                    Block("figure", data=data, caption=str(figure.get("caption") or "").strip())
                )
    return blocks


# --------------------------------------------------------------------------- #
# 编号：一级「一、」二级「（一）」三级「1.」四级「（1）」
# --------------------------------------------------------------------------- #
_CN_DIGITS = "一二三四五六七八九"


def _cn_number(value: int) -> str:
    if value <= 0:
        return str(value)
    if value < 10:
        return _CN_DIGITS[value - 1]
    if value == 10:
        return "十"
    if value < 20:
        return "十" + _CN_DIGITS[value - 11]
    tens, ones = divmod(value, 10)
    head = _CN_DIGITS[tens - 1] + "十"
    return head + (_CN_DIGITS[ones - 1] if ones else "")


_LEADING_NUMBER = re.compile(
    r"^\s*(?:"
    r"[一二三四五六七八九十]{1,3}\s*[、.．]"  # 一、
    r"|[（(]\s*[一二三四五六七八九十\d]{1,3}\s*[)）]"  # （一） / （1）
    r"|\d{1,2}(?:\.\d{1,2})+[、.．]?\s*"  # 1.1 / 2.1 / 1.1.1
    r"|\d{1,2}\s*[、.．)]\s*"  # 1. / 1、 / 1)
    r"|\d{1,2}\s+"  # 「1 引言」——编号后直接接空格
    r"|[①-⑩]\s*"  # ①
    r")"
)

#: 「3 个要点」「2 条建议」里的数字是数量词，不是章节号——剥掉会变成「一、个要点」。
_MEASURE_WORDS = "个项条种次年月日份名台组人类页件批笔位"


def _strip_leading_number(text: str) -> str:
    """剥掉标题开头自带的编号（「2.1 测试数据」→「测试数据」）。

    剥不掉就原样返回：判断不出是编号还是标题的一部分时，宁可留着。
    """
    matched = _LEADING_NUMBER.match(text)
    if not matched:
        return text
    prefix = matched.group(0).strip()
    rest = text[matched.end() :].strip()
    if not rest:
        return text
    if prefix.isdigit() and rest[0] in _MEASURE_WORDS:
        return text
    return rest


class _Numbering:
    """标题自动编号：先把原文自带的编号剥掉，再按方案重排。

    为什么不是「有编号就不动」：模型经常在汉字稿里写一节「二、」、下一节又写成
    「2.1」，一篇里两套编号并排出现（「二、」下面挂「2.1」），看着就像两个人拼的。
    编号是全文的秩序，只能有一套——剥掉旧的按顺序重数，层级和序号就永远对得上。

    方案取自 `doc_lexicon.NUMBERING_SCHEMES`（cn / decimal / article / none / gb），
    由文档类型决定：周报用「一、」「（一）」（三级以下不编号，中文没有通行的纯中文
    三级序号），论文与方案用「1.1.1」，合同用「第一条」，公文用国标那套四层序数，
    纪要和手册不编号（不编号的稿子原样保留作者写的编号，见 `none` 分支）。

    模板留空的那一级就是不编号：`label` 只剥号、不加号。所以中文方案的三级标题
    排出来就是「测试数据记录」本身，层级靠字号与缩进区分——不会出现「一、」下面
    挂个「1.」的汉字阿拉伯混排。
    """

    def __init__(self, scheme: str = "cn") -> None:
        self.scheme = scheme if scheme in NUMBERING_SCHEMES else "cn"
        self.counters = [0, 0, 0, 0]

    def label(self, level: int, text: str) -> str:
        clean = (text or "").strip()
        if not clean:
            return clean
        # 不编号的稿子（纪要、手册）本来就没序号；作者写了「第一步」这类，也照原样留着
        if self.scheme == "none":
            return clean
        clean = _strip_leading_number(clean)
        if not clean:  # 整条标题只有一个编号，剥完是空的——宁可留着编号也别留空标题
            return (text or "").strip()
        depth = max(1, min(level, 4))
        self.counters[depth - 1] += 1
        for deeper in range(depth, 4):
            self.counters[deeper] = 0
        # 稿子直接从二级小节开头时（第一行就是「### 2.1 …」），上级序号是 0，
        # 拼出来会变成「0.1」。缺的上级按第一级算，宁可当「1.1」也不能出现 0。
        for shallower in range(depth - 1):
            if not self.counters[shallower]:
                self.counters[shallower] = 1
        value = self.counters[depth - 1]
        # decimal 方案要「到这一级为止」的整串序号（1 / 1.1 / 1.1.1），
        # 所以把 counters 拼出来一起交给模板。
        dotted = ".".join(str(number) for number in self.counters[:depth])
        template = NUMBERING_SCHEMES[self.scheme][depth - 1]
        return template.format(cn=_cn_number(value), n=value, dot=dotted) + clean


# --------------------------------------------------------------------------- #
# 行内格式
# --------------------------------------------------------------------------- #
_INLINE = re.compile(r"(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*)")


def _inline_runs(text: str) -> list[tuple[str, bool, bool]]:
    """切成 (文字, 加粗, 等宽) 三段式的 run 列表。"""
    runs: list[tuple[str, bool, bool]] = []
    position = 0
    for matched in _INLINE.finditer(text or ""):
        if matched.start() > position:
            runs.append((text[position : matched.start()], False, False))
        token = matched.group(0)
        if token.startswith("**"):
            runs.append((token[2:-2], True, False))
        elif token.startswith("`"):
            runs.append((token[1:-1], False, True))
        else:
            runs.append((token[1:-1], False, False))
        position = matched.end()
    if position < len(text or ""):
        runs.append((text[position:], False, False))
    return runs or [(text or "", False, False)]


def strip_inline(text: str) -> str:
    """去掉行内标记，只留字（预览 HTML 会自己转义，表格分列要靠纯文本）。"""
    return _INLINE.sub(lambda matched: matched.group(0).strip("*`"), text or "")


# --------------------------------------------------------------------------- #
# 文首信息行（实验名称 / 姓名 学号 专业 日期）
# --------------------------------------------------------------------------- #
# 样例文档的标题块是三行：大标题、副标题、然后是两行「字段：值」的信息行，
# 三行一律居中、都不吃首行缩进。信息行不是标题，模型也不会给它加任何标记，
# 只能在渲染时认：字段名 + 两个以上冒号 + 不带句末标点。
BYLINE_KEYS: tuple[str, ...] = (
    "实验名称",
    "实验方式",
    "实验时间",
    "课程",
    "课题",
    "项目",
    "姓名",
    "学号",
    "专业",
    "班级",
    "院系",
    "学院",
    "单位",
    "部门",
    "指导教师",
    "指导老师",
    "报告人",
    "撰写人",
    "组员",
    "成员",
    "日期",
)
# 句末标点一出现就是「一句话」，不是字段行。注意别把「；」列进来：
# 「姓名：X；学号：Y」是信息行最常见的写法之一。
_BYLINE_STOP = ("。", "！", "？", ".", "!", "?")


def looks_like_byline(text: str) -> bool:
    """这一行是不是文首的「字段：值」信息行（如「姓名：张三  学号：2024001」）。"""
    line = (text or "").strip()
    if not line or len(line) > 80:
        return False
    if any(mark in line for mark in _BYLINE_STOP):
        return False
    # 至少两组「字段：值」——一个冒号更像正文里的「结论：……」。
    if len(re.findall(r"[：:]", line)) < 2:
        return False
    return sum(1 for key in BYLINE_KEYS if key in line) >= 2



# --------------------------------------------------------------------------- #
# docx 渲染
# --------------------------------------------------------------------------- #
def _set_east_asian(run: Any, cn: str, en: str) -> None:
    """中英文字体：`w:rFonts` 必须是 rPr 的第一个子节点，位置交给 python-docx。

    手写 append 会把字体排到字号、颜色后面——Word 能认，WPS 认不出，
    打开来中文一律退回默认字体（用户说的「字体没保留」）。
    """
    run.font.name = en
    rpr = run._element.get_or_add_rPr()
    fonts = rpr.get_or_add_rFonts()
    fonts.set(qn("w:ascii"), en)
    fonts.set(qn("w:hAnsi"), en)
    fonts.set(qn("w:eastAsia"), cn)


def _shade(cell: Any, fill: str) -> None:
    tcpr = cell._tc.get_or_add_tcPr()
    shd = insert_ordered(tcpr, OxmlElement("w:shd"), _TCPR_ORDER)
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)


def _borders(table: Any, color: str = RULE, size: int = 6) -> None:
    tblpr = table._tbl.tblPr
    borders = insert_ordered(tblpr, OxmlElement("w:tblBorders"), _TBLPR_ORDER)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:val"), "single")
        node.set(qn("w:sz"), str(size))
        node.set(qn("w:color"), color)
        borders.append(node)


def _no_borders(table: Any) -> None:
    tblpr = table._tbl.tblPr
    borders = insert_ordered(tblpr, OxmlElement("w:tblBorders"), _TBLPR_ORDER)
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:val"), "nil")
        borders.append(node)


def _visual_len(text: str) -> int:
    """按「汉字算两个宽度」估一行占多少位置。中文列按字符数算会把短列估宽两倍。"""
    return sum(2 if ord(char) > 0x2E80 else 1 for char in str(text or ""))


def _column_widths(
    header: Sequence[str], rows: Sequence[Sequence[str]], total_cm: float
) -> list[float]:
    """按每列内容的宽窄分宽度。

    均分是省事，但「完成」「材料未提供」这种极短列会白占三分之一版面，
    真正要读的那一列被挤成四条窄行——表格看起来就比正文还难读。
    """
    columns = max(1, len(header))
    weights: list[float] = []
    for index in range(columns):
        cells = [header[index] if index < len(header) else ""]
        cells += [row[index] if index < len(row) else "" for row in rows]
        longest = max((_visual_len(cell) for cell in cells), default=4)
        weights.append(float(max(6, min(longest, 36))))
    scale = total_cm / sum(weights)
    widths = [round(weight * scale, 2) for weight in weights]
    # 再兜一道下限：列宽小于 2cm 时中文只剩两个字，标题会折成两行
    floor = 2.0
    deficit = sum(floor - width for width in widths if width < floor)
    if deficit:
        wide = [index for index, width in enumerate(widths) if width > floor]
        pool = sum(widths[index] - floor for index in wide) or 1.0
        for index in wide:
            widths[index] = round(widths[index] - deficit * (widths[index] - floor) / pool, 2)
        widths = [max(floor, width) for width in widths]
    return widths


def _fixed_layout(table: Any, widths: Sequence[float]) -> None:
    """固定列宽：不写 tblLayout=fixed 的话，Word 会按「自动调整」把宽度重算一遍。

    `table.autofit = False` 就是写 `w:tblLayout type=fixed`，位置由 python-docx 保证
    （tblBorders 之后、tblCellMar / tblLook 之前）。以前这里再手动 append 一个，
    同一份 tblPr 里出现两个 tblLayout，WPS 直接判文档非法、把整张表的框线丢掉。
    """
    table.autofit = False
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            if index < len(widths):
                cell.width = Cm(widths[index])


def _page_number(document: Any, preset: Preset) -> None:
    """页脚居中页码「— 1 —」：交付件有没有页码，是「随手一存」和「成稿」的区别。"""
    with contextlib.suppress(Exception):
        footer = document.sections[0].footer
        paragraph = footer.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for text in ("— ", None, " —"):
            if text is None:
                run = paragraph.add_run()
                begin = OxmlElement("w:fldChar")
                begin.set(qn("w:fldCharType"), "begin")
                field = OxmlElement("w:instrText")
                field.set(qn("xml:space"), "preserve")
                field.text = "PAGE"
                end = OxmlElement("w:fldChar")
                end.set(qn("w:fldCharType"), "end")
                run._r.append(begin)
                run._r.append(field)
                run._r.append(end)
                run.font.size = Pt(preset.note_size)
                _set_east_asian(run, preset.cn_font, preset.en_font)
                continue
            run = paragraph.add_run(text)
            run.font.size = Pt(preset.note_size)
            run.font.color.rgb = MUTED
            _set_east_asian(run, preset.cn_font, preset.en_font)


class DocxRenderer:
    """把 blocks 写成一份排好版的 docx。"""

    def __init__(self, preset: Preset, numbering: str = "cn") -> None:
        self.preset = preset
        self.doc = Document()
        self.numbering = _Numbering(numbering)
        self._configure()

    # ---------- 样式 ----------
    def _configure(self) -> None:
        preset = self.preset
        section = self.doc.sections[0]
        section.top_margin = Cm(preset.margin_top)
        section.bottom_margin = Cm(preset.margin_bottom)
        section.left_margin = Cm(preset.margin_left)
        section.right_margin = Cm(preset.margin_right)

        normal = self.doc.styles["Normal"]
        normal.font.size = Pt(preset.body_size)
        normal.font.color.rgb = BODY
        with contextlib.suppress(Exception):
            # 样式级也要写 eastAsia，否则 Word 会用模板默认的宋体渲染中文。
            # 位置由 python-docx 保证（rFonts 必须是 rPr 第一个子节点），WPS 才认。
            set_rfonts(normal.element.get_or_add_rPr(), preset.cn_font, preset.en_font)
        pf = normal.paragraph_format
        pf.line_spacing = preset.body_line
        pf.space_before = Pt(0)
        pf.space_after = Pt(preset.body_after)
        pf.alignment = _ALIGN_MAP.get(preset.body_align, WD_ALIGN_PARAGRAPH.JUSTIFY)

        heading_sizes = {index: size for index, size in enumerate(preset.heading_sizes, start=1)}
        heading_fonts = {index: name for index, name in enumerate(preset.heading_fonts, start=1)}
        for level, size in heading_sizes.items():
            with contextlib.suppress(KeyError):
                style = self.doc.styles[f"Heading {level}"]
                cn, en = FONTS.get(heading_fonts[level], FONTS["宋体"])
                style.font.size = Pt(size)
                style.font.bold = True
                style.font.italic = False
                style.font.color.rgb = INK
                set_rfonts(style.element.get_or_add_rPr(), cn, en)
                # 默认模板的标题是蓝色 + 带下划线的 Title 风格，逐项清掉
                style.paragraph_format.space_before = Pt(16 if level == 1 else 12)
                style.paragraph_format.space_after = Pt(8 if level == 1 else 6)
                style.paragraph_format.line_spacing = 1.3
                style.paragraph_format.keep_with_next = True
                # 样式级也跟着钉死（不能只改段落）：样式是从 Normal 继承的，而 Normal
                # 是「正文两端对齐」，任何「用了样式但没单独设对齐」的段落又会被拉成
                # 满行。对齐值跟段落同一个来源：默认居中，公文左。
                style.paragraph_format.alignment = _ALIGN_MAP.get(
                    preset.heading_align, WD_ALIGN_PARAGRAPH.CENTER
                )
                style.paragraph_format.first_line_indent = Pt(0)
                # 样式级也要抹掉缩进：预设里若留着上一版的 left indent，
                # 居中的标题会被整体推右。
                style.paragraph_format.left_indent = Pt(0)

        # 文档标题用内置 Title 样式：Word 的导航窗格、mammoth 的 styleMap 都按样式名认标题，
        # 用 Normal 写出来只是「一段比较大的字」，转出来的 HTML 里就丢了 h1。
        # 默认模板的 Title 带蓝色和下边框，逐项清掉；对齐改成居中（大标题居中才像正式稿）。
        with contextlib.suppress(KeyError):
            style = self.doc.styles["Title"]
            cn, en = FONTS.get(preset.title_font, FONTS["宋体"])
            style.font.size = Pt(preset.title_size)
            style.font.bold = True
            style.font.italic = False
            style.font.color.rgb = INK
            set_rfonts(style.element.get_or_add_rPr(), cn, en)
            ppr = style.element.get_or_add_pPr()
            for border in ppr.findall(qn("w:pBdr")):
                ppr.remove(border)
            style.paragraph_format.space_before = Pt(0)
            style.paragraph_format.space_after = Pt(6)
            style.paragraph_format.line_spacing = 1.2
            style.paragraph_format.alignment = _ALIGN_MAP.get(
                preset.title_align, WD_ALIGN_PARAGRAPH.CENTER
            )

        _page_number(self.doc, preset)
        with contextlib.suppress(Exception):
            self.doc.core_properties.author = "Office Agent"
            self.doc.core_properties.comments = "由 Office Agent 生成"

    # ---------- 基础写入 ----------
    def _add_runs(
        self,
        paragraph: Any,
        text: str,
        *,
        size: float,
        bold: bool,
        color: Any,
        italic: bool = False,
        underline: bool = False,
    ) -> None:
        preset = self.preset
        for chunk, is_bold, is_code in _inline_runs(text):
            if not chunk:
                continue
            run = paragraph.add_run(chunk)
            _set_east_asian(
                run,
                "Consolas" if is_code else preset.cn_font,
                "Consolas" if is_code else preset.en_font,
            )
            run.font.size = Pt(size - (0.5 if is_code else 0))
            run.font.bold = bold or is_bold
            run.font.color.rgb = color
            if italic:
                run.font.italic = True
            if underline:
                run.font.underline = True

    def title(self, text: str, subtitle: str = "") -> None:
        preset = self.preset
        align = _ALIGN_MAP.get(preset.title_align, WD_ALIGN_PARAGRAPH.CENTER)
        paragraph = self.doc.add_paragraph(style="Title")
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(6 if subtitle else 14)
        paragraph.paragraph_format.line_spacing = 1.2
        # 大标题居中：文首一行居中的黑字，是「这是标题」最省力的信号
        paragraph.alignment = align
        self._add_runs(paragraph, text, size=preset.title_size, bold=True, color=INK)
        if subtitle:
            # 副标题单独用一个样式名（Subtitle）：预览按样式名把它认成 `.doc-lead`，
            # 免得不缩进的规则把它也当成正文缩两格。样式自带的斜体在下面逐个 run 清掉。
            lead = self.doc.add_paragraph(style="Subtitle")
            lead.paragraph_format.space_before = Pt(0)
            lead.paragraph_format.space_after = Pt(14)
            lead.paragraph_format.line_spacing = 1.3
            # 副标题跟着标题居中，否则居中的标题下面挂一行左对齐的小字，像没对齐
            lead.alignment = align
            # 字号比正文大一档、颜色跟正文一样黑、加粗：样例文档里副标题是
            # 「比正文显眼、比大标题轻」的那一档。取 max 是因为「文档格式」面板
            # 若把正文改成三号，subtitle_size 还停在旧值上，副标题就会比正文还小。
            size = max(preset.subtitle_size, preset.body_size + 2.0)
            self._add_runs(lead, subtitle, size=size, bold=True, color=INK)
            for run in lead.runs:
                run.font.italic = False

    def heading(self, level: int, text: str) -> None:
        preset = self.preset
        # markdown 的 # 是文档标题，## 才是正文里的一级小节
        depth = max(1, min(level - 1, 4))
        label = self.numbering.label(depth, text)
        paragraph = self.doc.add_heading("", level=depth)
        paragraph.paragraph_format.space_before = Pt(16 if depth == 1 else 12)
        paragraph.paragraph_format.space_after = Pt(8 if depth == 1 else 6)
        paragraph.paragraph_format.line_spacing = 1.3
        # 小节标题左对齐、从版心左缘起行。不能不管：Normal 是两端对齐，标题不显式
        # 钉死就会被拉成满行——字号越大，被撑开的字间距越刺眼。
        align = _ALIGN_MAP.get(preset.heading_align, WD_ALIGN_PARAGRAPH.LEFT)
        paragraph.alignment = align
        paragraph.paragraph_format.first_line_indent = Pt(0)
        size = preset.heading_sizes[depth - 1]
        # 逐级缩进只对左对齐有意义：居中的参照系是版心，先缩 1 字符再居中，
        # 整行会往右偏，看着像「没对齐」而不是「有层级」。
        indent = 0.0
        if align == WD_ALIGN_PARAGRAPH.LEFT and preset.heading_indent:
            indent = heading_indents(self.numbering.scheme)[depth - 1]
        # 缩进量从 heading_indents 取（doc_lexicon.NUMBERING_INDENTS 单一来源）：
        # 1. 与 1.1 顶在同一条竖线上，读者只能靠多读一个编号判断层级，缩进之后
        # 左边缘本身就分出了层级。公文与紧凑版式整篇顶格，走 preset 开关。
        # 一级也写 0，不省这一步：样式里可能残留上一版的左缩进，写死才能真顶格。
        set_left_indent_chars(paragraph, indent, size)
        self._add_runs(paragraph, label, size=size, bold=True, color=INK)

    def paragraph(self, text: str) -> None:
        preset = self.preset
        paragraph = self.doc.add_paragraph()
        # 落款（来源 / 注 / 说明）前面留一档空：它和正文不是同一层信息，
        # 紧贴着上一条列表会读成「最后一条的续行」。
        lead_in = text.lstrip().startswith(("来源：", "来源:", "注：", "说明："))
        paragraph.paragraph_format.space_before = Pt(8 if lead_in else 0)
        paragraph.paragraph_format.space_after = Pt(preset.body_after)
        paragraph.paragraph_format.line_spacing = preset.body_line
        paragraph.alignment = _ALIGN_MAP.get(preset.body_align, WD_ALIGN_PARAGRAPH.JUSTIFY)
        if preset.body_indent:
            # 首行缩进按「字符」写（Word 里的「特殊格式 → 首行缩进 2 字符」），
            # 不用 pt：换成四号字体时 24pt 就不再是两格了。
            set_indent_chars(paragraph, preset.body_indent, preset.body_size)
        self._add_runs(
            paragraph,
            text,
            size=preset.body_size,
            bold=preset.body_bold,
            color=BODY,
            italic=preset.body_italic,
            underline=preset.body_underline,
        )

    def byline(self, text: str) -> None:
        """文首信息行（实验名称 / 姓名 学号 专业 日期）：居中、不缩进。

        样例文档的标题块是「大标题 + 副标题 + 两行字段」四行居中排下来的。
        信息行不是标题，模型也不会给它打标记，只能按内容认（见 looks_like_byline）。
        按正文排会多出两格首行缩进，还会跟着两端对齐把字距拉开，一眼就不像落款。
        """
        preset = self.preset
        paragraph = self.doc.add_paragraph()
        pf = paragraph.paragraph_format
        pf.space_before = Pt(0)
        pf.space_after = Pt(4)
        pf.line_spacing = 1.4
        pf.first_line_indent = Pt(0)
        pf.left_indent = Pt(0)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._add_runs(paragraph, text, size=preset.body_size, bold=False, color=BODY)

    def items(self, items: Sequence[str], ordered: bool) -> None:
        """列表条目：一律排成正文段落，不挂任何项目符号。

        中文正式稿里没有「· 」这一层，位置由「首行缩进两格」顶着。有序条目把
        序号写进行首（「1. 打开电源」）——序号本身是信息，不能丢；而无序条目
        干脆不带符号，读起来就是一段段正文。
        """
        for position, item in enumerate(items, start=1):
            text = f"{position}. {item}" if ordered else item
            self.paragraph(text)

    def quote(self, text: str) -> None:
        preset = self.preset
        for line in (text or "").split("\n"):
            if not line.strip():
                continue
            paragraph = self.doc.add_paragraph()
            pf = paragraph.paragraph_format
            pf.left_indent = Cm(0.6)
            pf.space_before = Pt(0)
            pf.space_after = Pt(4)
            paragraph.paragraph_format.line_spacing = preset.body_line
            # 引言是「一段被拎出来的话」，版式上和正文同源，但钉死左对齐：
            # Normal 现在是两端对齐，不钉就会被拉成满行，左侧那条竖线也失去对齐的锚点
            pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
            ppr = paragraph._p.get_or_add_pPr()
            pbdr = insert_ordered(ppr, OxmlElement("w:pBdr"), _PPR_ORDER)
            left = OxmlElement("w:left")
            left.set(qn("w:val"), "single")
            left.set(qn("w:sz"), "18")
            left.set(qn("w:space"), "8")
            left.set(qn("w:color"), "D0D5DD")
            pbdr.append(left)
            self._add_runs(paragraph, line, size=preset.body_size, bold=False, color=MUTED)

    def code(self, text: str) -> None:
        preset = self.preset
        for line in (text or "").split("\n") or [""]:
            paragraph = self.doc.add_paragraph()
            pf = paragraph.paragraph_format
            pf.left_indent = Cm(0.4)
            pf.space_before = Pt(0)
            pf.space_after = Pt(0)
            pf.line_spacing = 1.15
            # 代码是逐行等宽对齐的，两端对齐会把每行字距拉开，缩进层级全乱
            pf.alignment = WD_ALIGN_PARAGRAPH.LEFT
            ppr = paragraph._p.get_or_add_pPr()
            shd = insert_ordered(ppr, OxmlElement("w:shd"), _PPR_ORDER)
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"), "F6F7F9")
            run = paragraph.add_run(line or " ")
            _set_east_asian(run, "Consolas", "Consolas")
            run.font.size = Pt(preset.body_size - 1)
            run.font.color.rgb = BODY
        # 代码块后留一点空，避免下一段贴上去
        self.doc.add_paragraph().paragraph_format.space_after = Pt(0)

    def table(self, header: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
        preset = self.preset
        columns = max(1, len(header))
        table = self.doc.add_table(rows=1, cols=columns)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        _borders(table)
        usable = 21.0 - preset.margin_left - preset.margin_right
        widths = _column_widths(header, rows, usable)

        head = table.rows[0]
        for cell, text in zip(head.cells, header, strict=False):
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_before = Pt(2)
            paragraph.paragraph_format.space_after = Pt(2)
            paragraph.paragraph_format.line_spacing = 1.2
            # 单元格里的字左对齐：正文两端对齐是为了让每行右缘齐边，
            # 但表格一行里各列长短不一，拉齐会让同一列的数字对不齐，反而难比大小
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            self._add_runs(
                paragraph, strip_inline(text), size=preset.table_size, bold=True, color=INK
            )
            _shade(cell, preset.head_fill)
            # 表头跨页重复：一张 20 行的表翻页后没有表头，读者就不知道每列是什么
            trpr = head._tr.get_or_add_trPr()
            trpr.append(OxmlElement("w:tblHeader"))

        for row in rows:
            cells = table.add_row().cells
            for cell, text in zip(cells, row, strict=False):
                cell.text = ""
                paragraph = cell.paragraphs[0]
                paragraph.paragraph_format.space_before = Pt(2)
                paragraph.paragraph_format.space_after = Pt(2)
                paragraph.paragraph_format.line_spacing = 1.2
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                self._add_runs(
                    paragraph, strip_inline(text), size=preset.table_size, bold=False, color=BODY
                )

        _fixed_layout(table, widths)

        # 表格后面补一个空段：Word 里紧贴表格的段落会被吸进去，读起来没有呼吸
        spacer = self.doc.add_paragraph()
        spacer.paragraph_format.space_after = Pt(2)
        spacer.paragraph_format.line_spacing = 1.0

    def figure(self, data: bytes, caption: str = "") -> None:
        preset = self.preset
        try:
            self.doc.add_picture(io.BytesIO(data), width=Cm(14.5))
        except Exception:  # 图坏了不该让整篇文档生成失败
            return
        self.doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        if not caption:
            return
        paragraph = self.doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_before = Pt(2)
        paragraph.paragraph_format.space_after = Pt(10)
        self._add_runs(paragraph, caption, size=preset.note_size, bold=False, color=MUTED)

    def rule(self) -> None:
        paragraph = self.doc.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(4)
        paragraph.paragraph_format.space_after = Pt(8)
        ppr = paragraph._p.get_or_add_pPr()
        pbdr = insert_ordered(ppr, OxmlElement("w:pBdr"), _PPR_ORDER)
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), RULE)
        pbdr.append(bottom)

    def write(self, blocks: Sequence[Block]) -> None:
        # 只有小节标题之前那几段才可能是文首信息行：正文里的「日期：2026-11-11」
        # 是数据，居中就成了排版事故。
        in_heading_block = True
        for block in blocks:
            if block.kind == "heading":
                in_heading_block = False
                self.heading(block.level, block.text)
            elif block.kind == "paragraph":
                if in_heading_block and looks_like_byline(block.text):
                    self.byline(block.text)
                else:
                    self.paragraph(block.text)
            elif block.kind == "bullet":
                self.items(block.items, ordered=False)
            elif block.kind == "number":
                self.items(block.items, ordered=True)
            elif block.kind == "table":
                self.table(block.header, block.rows)
            elif block.kind == "quote":
                self.quote(block.text)
            elif block.kind == "code":
                self.code(block.text)
            elif block.kind == "figure" and block.data:
                self.figure(block.data, block.caption)
            elif block.kind == "rule":
                self.rule()


def render_docx_blocks(
    path: Path,
    *,
    title: str,
    blocks: Sequence[Block],
    subtitle: str = "",
    preset: str = "report",
    line: str | float | Length | None = None,
    numbering: str = "",
    style: dict[str, Any] | None = None,
) -> None:
    """写一份 docx。

    `preset` 认 report / gongwen / compact；
    `line` 单独改正文行距（"单倍" / 1.15 / "1.5" / "双倍" / "固定值28磅"），
    不传就跟着 preset 走——只有整篇要换行距时才用它；
    `style` 是用户在「文档格式」里点的那几项（字体 / 字号 / 字型 / 行距 / 首行缩进 /
    对齐），只覆盖给了值的字段，最后叠加——用户亲手点的优先于版式预设；
    `numbering` 是编号方案（cn / decimal / article / none，或直接给文档类型名
    让它自己挑），空着按 `cn`——「一、（一）1.」在国内办公文档里最不容易出错。
    """
    layout = PRESETS.get(resolve_preset(preset), PRESETS["report"])
    if line not in (None, ""):
        layout = replace(layout, body_line=resolve_line(line))
    layout = preset_with_style(layout, style)
    renderer = DocxRenderer(layout, numbering=resolve_numbering(numbering))
    renderer.title(title, subtitle)
    renderer.write(blocks)
    renderer.doc.save(str(path))
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError("DOCX 保存失败")


# --------------------------------------------------------------------------- #
# HTML 预览：和 docx 共用一份 blocks，保证「看到的」和「下载的」是同一篇
# --------------------------------------------------------------------------- #
def _escape(text: str) -> str:
    return html.escape(text or "", quote=False)


def _inline_html(text: str) -> str:
    escaped = _escape(text)
    escaped = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", escaped)
    return escaped


def blocks_to_html(
    title: str,
    blocks: Sequence[Block],
    subtitle: str = "",
    *,
    preset: str = "report",
    numbering: str = "",
    style: dict[str, Any] | None = None,
) -> str:
    """一份能被 `.prose-docx` 直接渲染的正文（不含外层容器）。

    `preset` 影响两件「版式里看得见」的事：正文要不要首行缩进（紧凑版式不缩，段落
    标 `doc-flat`），小节标题要不要逐级缩进（公文顶格，不加 `doc-hN`），以及整篇要不要
    缩一档（紧凑版式包一层 `.doc-compact`，预览里字更小、行更紧）。
    这几条不能预览里一套、Word 里另一套——用户一眼就看出来了。

    `numbering` 与 `render_docx_blocks` 同一个口径，必须传同一个值：预览里是
    「一、摘要」、下载下来是「1. 摘要」，用户立刻会怀疑是不是拿错了文件。
    """
    numbering_state = _Numbering(resolve_numbering(numbering))
    layout = preset_with_style(PRESETS.get(resolve_preset(preset), PRESETS["report"]), style)
    indent_class = ' class="doc-flat"' if not layout.body_indent else ""
    # 只有这一处是 h1：文档大标题（居中、全文最大）。小节标题一律从 h2 起——
    # `h1` 在预览 CSS 里等于「居中大标题」，小节要是也用 h1，预览就会满屏居中标题。
    parts: list[str] = [f'<h1 class="doc-title">{_escape(title)}</h1>']
    if subtitle:
        parts.append(f'<p class="doc-lead">{_escape(subtitle)}</p>')
    # 文首信息行（实验名称 / 姓名学号…）跟 Word 那边同一套判据：小节标题之前、
    # 带两组以上「字段：值」的短行，居中排、不缩进。
    in_heading_block = True
    for block in blocks:
        if block.kind == "heading":
            in_heading_block = False
            depth = max(1, min(block.level - 1, 4))
            label = numbering_state.label(depth, block.text)
            tag = f"h{min(depth + 1, 5)}"
            # 带上级别类：缩进量取自 `.doc-hN`，和 Word 里 `w:leftChars` 是同一套
            # 「每级 +1 字符」。不带类就只能按标签选，而标签已经被大标题占用。
            # 顶格版式（公文）不加。
            cls = f' class="doc-h{depth}"' if layout.heading_indent else ""
            parts.append(f"<{tag}{cls}>{_inline_html(label)}</{tag}>")
        elif block.kind == "paragraph":
            if in_heading_block and looks_like_byline(block.text):
                parts.append(f'<p class="doc-byline">{_inline_html(block.text)}</p>')
            else:
                parts.append(f"<p{indent_class}>{_inline_html(block.text)}</p>")
        elif block.kind in ("bullet", "number"):
            # 列表条目和 Word 里一样排成正文段落：预览里挂圆点、下载后没有，
            # 用户会以为预览糊弄他。有序条目的序号写进行首，无序条目不带符号。
            ordered = block.kind == "number"
            for position, item in enumerate(block.items, start=1):
                prefix = f"{position}. " if ordered else ""
                parts.append(f"<p{indent_class}>{prefix}{_inline_html(item)}</p>")
        elif block.kind == "table":
            head = "".join(f"<th>{_inline_html(cell)}</th>" for cell in block.header)
            body = "".join(
                "<tr>" + "".join(f"<td>{_inline_html(cell)}</td>" for cell in row) + "</tr>"
                for row in block.rows
            )
            parts.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
        elif block.kind == "quote":
            parts.append(f"<blockquote>{_inline_html(block.text)}</blockquote>")
        elif block.kind == "code":
            parts.append(f"<pre><code>{_escape(block.text)}</code></pre>")
        elif block.kind == "rule":
            parts.append("<hr/>")
        elif block.kind == "figure" and block.data:
            import base64

            encoded = base64.b64encode(block.data).decode("ascii")
            caption = f"<figcaption>{_escape(block.caption)}</figcaption>" if block.caption else ""
            parts.append(
                f'<figure><img src="data:image/jpeg;base64,{encoded}" alt="{_escape(block.caption)}"/>'
                f"{caption}</figure>"
            )
    rendered = "\n".join(parts)
    # 预览要把 Word 里的那几项「看得见」的设置同步过来：
    # - 紧凑版式整篇缩一档（字更小、行更紧）；
    # - 正文缩进字符数、对齐方式、字型（加粗/斜体/下划线）用 CSS 变量 + 类名带上，
    #   否则用户点了「左对齐」「缩进 0 字符」，预览里却还是按默认那套排。
    # - 两端对齐是默认值，不生成类名：`.prose-docx p` 的基础规则本来就是 justify，
    #   只有用户显式改成左/中/右时才需要 doc-align-* 去覆盖它。
    classes = ["doc-body"]
    if layout.dense:
        classes.append("doc-compact")
    if not layout.body_indent:
        classes.append("doc-flat")
    if layout.body_align and layout.body_align != "justify":
        classes.append(f"doc-align-{layout.body_align}")
    if layout.body_bold:
        classes.append("doc-bold")
    if layout.body_italic:
        classes.append("doc-italic")
    if layout.body_underline:
        classes.append("doc-underline")
    return (
        f'<div class="{" ".join(classes)}" '
        f'style="--doc-indent:{layout.body_indent:g}em">\n{rendered}\n</div>'
    )
