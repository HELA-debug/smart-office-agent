"""doc_lexicon.py —— 文档格式的词表（唯一真相）。

**为什么要单独一个文件。** 字号、字体、行距、缩进这些「词」以前散在两处：
`docx_utils` 的常量（给脚本用）和 `doc_render` 的 `Preset`（给产品文档用）。
一处写「正文 10.5pt」、另一处写「正文 12pt」，改一处忘一处——同一份稿子在预览里
是一个字号、下载下来是另一个，用户一眼就看出来「这不是一份正式文档」。
现在**数字只写在这里**，其它地方按名字取：

    docx_utils  —— 模型写脚本时用（`FONT_BODY` / `DOC_TYPES` / `set_para` 的默认值）
    doc_render  —— 产品文档用（`PRESETS` 每一档的标题/小节/正文字号与行距都从这里取）

**怎么加（维护指南，改这一张表就够）。**

- 加字号：`FONT_SIZES["小四"] = 12`。中文名要与 Word「字号」下拉里一字不差；
  数字一定用 pt（小四=12、五号=10.5），不要写 px 或「四号=14pt 但正文用 13」这种自创刻度。
- 加字体：`FONTS["方正小标宋"] = ("方正小标宋", "Times New Roman")`。两个都要写：
  只写中文名时，数字和英文会掉回模板默认字体，正文里的「2026」看起来就不对。
- 加行距：`LINE_SPACINGS["1.25"] = 1.25`；固定值用 `Pt(...)`（见 `LINE_FIXED_28`），
  固定值和倍数在 Word 里是两回事，别混着写。
- 加缩进：`FIRST_LINE_INDENTS["2"] = 2.0`（单位是「字符」，不是 pt——2 字符 ≈ 24pt，
  但字号一改就不等值了，所以这里按字符存）。
- 加文档类型：在 `DOC_TYPES` 里补一行，六项都给（page / scale / line / table / indent / align）。

**约定。** 中文正文默认宋体小四、首行缩进 2 字符、1.5 倍行距；标题用黑体，正文用宋体，
这是国内办公文档的通行写法（GB/T 9704 的公文是另一种：仿宋三号，见 `gongwen`）。
"""

from __future__ import annotations

from typing import Any

from docx.shared import Cm, Length, Pt

__all__ = [
    "ALIGNMENTS",
    "DOC_TYPES",
    "DOC_TYPE_ALIASES",
    "FIRST_LINE_INDENTS",
    "FONTS",
    "FONT_ROLES",
    "FONT_SIZES",
    "HEADING_SCALES",
    "LINE_DOUBLE",
    "LINE_FIXED_20",
    "LINE_FIXED_22",
    "LINE_FIXED_24",
    "LINE_FIXED_26",
    "LINE_FIXED_28",
    "LINE_FIXED_32",
    "LINE_LOOSE",
    "LINE_ONE_HALF",
    "LINE_SINGLE",
    "LINE_SPACINGS",
    "LINE_TIGHT",
    "NUMBERING_ALIASES",
    "NUMBERING_INDENTS",
    "NUMBERING_SCHEMES",
    "PAGES",
    "TABLE_STYLES",
    "font_of",
    "guess_doc_type",
    "heading_indents",
    "heading_specs",
    "page_spec",
    "resolve_align",
    "resolve_doc_type",
    "resolve_font",
    "resolve_indent",
    "resolve_line",
    "resolve_numbering",
    "resolve_size",
]

# --------------------------------------------------------------------------- #
# 一、字号：中文习惯用「号」，Word 的磅值是固定的
# --------------------------------------------------------------------------- #
#: 中文号数 → pt。顺序照 Word 下拉：初号最大，八号最小。
FONT_SIZES: dict[str, float] = {
    "初号": 42.0,
    "小初": 36.0,
    "一号": 26.0,
    "小一": 24.0,
    "二号": 22.0,
    "小二": 18.0,
    "三号": 16.0,
    "小三": 15.0,
    "四号": 14.0,
    "小四": 12.0,
    "五号": 10.5,
    "小五": 9.0,
    "六号": 7.5,
    "小六": 6.5,
    "七号": 5.5,
    "八号": 5.0,
}

#: 常见的变体写法（模型和用户都会写）。只在解析时用，不影响上面的正表。
_SIZE_ALIASES: dict[str, str] = {
    "小4": "小四",
    "4号": "四号",
    "小3": "小三",
    "3号": "三号",
    "2号": "二号",
    "1号": "一号",
}


def resolve_size(value: float | str) -> float:
    """`12` / `"12pt"` / `"12磅"` / `"小四"` / `"小四号"` → 12.0。

    模型十个里有八个直接给数字，给中文名的又会漏一个「号」字（"小四号"）。
    这两种都认，认不出时报一句能照着改的话，而不是 `KeyError: '12pt'`。
    """
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().replace(" ", "")
    if not text:
        raise ValueError("字号不能为空：用 pt 数字（12）或中文号数（小四）")
    if text in FONT_SIZES:
        return FONT_SIZES[text]
    if text in _SIZE_ALIASES:
        return FONT_SIZES[_SIZE_ALIASES[text]]
    # 「小四号」「四号」多一个「号」字：只去掉一个，别把「小四」也削成「小」
    text = text.removesuffix("号")
    if text in FONT_SIZES:
        return FONT_SIZES[text]
    if text in _SIZE_ALIASES:
        return FONT_SIZES[_SIZE_ALIASES[text]]
    digits = text.removesuffix("pt").removesuffix("磅").removesuffix("点")
    try:
        return float(digits)
    except ValueError:
        raise KeyError(
            f"认不出字号：{value}；用 pt 数字（10.5 / 12）或中文号数（{'、'.join(FONT_SIZES)}）"
        ) from None


# --------------------------------------------------------------------------- #
# 二、字体：中文名 + 西文名一起，缺一个就会「数字跳字体」
# --------------------------------------------------------------------------- #
#: (中文字体, 西文/数字字体)
#:
#: 铺得宽不是「什么字体都要用」，而是模型和用户写下的字体名十次有八次不在
#: 前几个里——「楷体」「楷体_GB2312」「华文楷体」「方正楷体」是同一族，
#: 认不出就只能退回宋体，正文看起来像换了个人排的。认不出时给一次近似替换，
#: 比悄悄掉回默认字体好。
FONTS: dict[str, tuple[str, str]] = {
    # ---- 宋体族（正文、表格、公文要件） ----
    "宋体": ("宋体", "Times New Roman"),
    "中宋": ("华文中宋", "Times New Roman"),
    "华文中宋": ("华文中宋", "Times New Roman"),
    "新宋体": ("新宋体", "Times New Roman"),
    "思源宋体": ("Source Han Serif SC", "Times New Roman"),
    "方正书宋": ("方正书宋简体", "Times New Roman"),
    "方正小标宋": ("方正小标宋简体", "Times New Roman"),
    "小标宋": ("方正小标宋简体", "Times New Roman"),
    # ---- 仿宋族（公文正文） ----
    "仿宋": ("仿宋", "Times New Roman"),
    "仿宋_GB2312": ("仿宋_GB2312", "Times New Roman"),
    "方正仿宋": ("方正仿宋_GBK", "Times New Roman"),
    # ---- 楷体族（引文、批示、摘要） ----
    "楷体": ("楷体", "Times New Roman"),
    "楷体_GB2312": ("楷体_GB2312", "Times New Roman"),
    "华文楷体": ("华文楷体", "Times New Roman"),
    "方正楷体": ("方正楷体_GBK", "Times New Roman"),
    # ---- 黑体族（标题） ----
    "黑体": ("黑体", "Arial"),
    "思源黑体": ("Source Han Sans SC", "Arial"),
    "微软雅黑": ("微软雅黑", "Segoe UI"),
    "雅黑": ("微软雅黑", "Segoe UI"),
    "等线": ("等线", "Calibri"),
    "苹方": ("PingFang SC", "Helvetica Neue"),
    "方正黑体": ("方正黑体_GBK", "Arial"),
    # ---- 装饰 / 特殊场合（聘任书、请柬、奖状才用） ----
    "隶书": ("隶书", "Times New Roman"),
    "幼圆": ("幼圆", "Arial"),
    "华文行楷": ("华文行楷", "Times New Roman"),
    # ---- 等宽（代码、命令、字段名） ----
    "Consolas": ("Consolas", "Consolas"),
    "等宽": ("Consolas", "Consolas"),
    "Cascadia": ("Cascadia Mono", "Cascadia Mono"),
    "JetBrains Mono": ("JetBrains Mono", "JetBrains Mono"),
}

#: 字体名的近似替换：写了个系统里可能没装的字体时，退回同族的常见版本。
#: 一次都没命中就退回正文（宋体），不让一个笔误毁掉整篇。
_FONT_FALLBACK: dict[str, str] = {
    "华文中宋": "宋体",
    "新宋体": "宋体",
    "思源宋体": "宋体",
    "方正书宋": "宋体",
    "方正小标宋": "宋体",
    "小标宋": "宋体",
    "方正仿宋": "仿宋",
    "仿宋_GB2312": "仿宋",
    "楷体_GB2312": "楷体",
    "华文楷体": "楷体",
    "方正楷体": "楷体",
    "思源黑体": "黑体",
    "方正黑体": "黑体",
    "雅黑": "微软雅黑",
    "苹方": "微软雅黑",
    "等线": "微软雅黑",
    "幼圆": "微软雅黑",
    "隶书": "楷体",
    "华文行楷": "楷体",
    "等宽": "Consolas",
    "Cascadia": "Consolas",
    "JetBrains Mono": "Consolas",
}

#: 语义角色 → 字体名。改「正文用什么字体」只改这里，全篇跟着变。
#: 国内通行写法：标题黑体（醒目）、正文宋体（耐读）、引文楷体、代码等宽。
FONT_ROLES: dict[str, str] = {
    "title": "宋体",  # 大标题：居中 + 加粗 + 全文最大，用宋体才像正式稿
    "body": "宋体",
    "h1": "黑体",
    "h2": "黑体",
    "h3": "宋体",
    "h4": "宋体",
    "table": "宋体",
    "note": "宋体",
    "quote": "楷体",
    "code": "Consolas",
}


def font_of(role: str) -> tuple[str, str]:
    """角色名 → (中文, 西文)。取不到就退回正文，不让一个笔误毁掉整篇。"""
    return FONTS.get(FONT_ROLES.get(role, "宋体"), FONTS["宋体"])


def resolve_font(name: str | None, default: str = "宋体") -> tuple[str, str]:
    """字体名 → (中文, 西文)。认不出的字体退回同族的常见版本，再退正文。"""
    key = str(name or "").strip()
    if not key:
        return FONTS[default]
    if key in FONTS:
        return FONTS[key]
    fallback = _FONT_FALLBACK.get(key)
    if fallback:
        return FONTS.get(fallback, FONTS[default])
    # 「微软雅黑 Light」「思源黑体 CN」这类带后缀的写法：取第一个能认出来的词
    for known, pair in FONTS.items():
        if known in key:
            return pair
    return FONTS[default]


# --------------------------------------------------------------------------- #
# 三、行距：倍数与固定值是两套东西
# --------------------------------------------------------------------------- #
LINE_SINGLE = 1.0
LINE_TIGHT = 1.15  # 表格、清单、附录
LINE_ONE_HALF = 1.5  # 通用正文（默认）
LINE_LOOSE = 1.75  # 讲稿、需要批注的稿子
LINE_DOUBLE = 2.0
LINE_FIXED_20 = Pt(20)  # 小四字排紧凑版（表格多的资料）
LINE_FIXED_22 = Pt(22)  # 简历这类「一行占多少磅」要写死的
LINE_FIXED_24 = Pt(24)
LINE_FIXED_26 = Pt(26)
LINE_FIXED_28 = Pt(28)  # 公文正文（GB/T 9704 的 28 磅）
LINE_FIXED_32 = Pt(32)  # 讲稿（要留手写批注）

#: 倍数行距：字面值就是倍数，`"2"` 与 `"double"` 等价。
#: Word「多倍行距」的下拉里就是这几档，再多也只是 0.1 的微调。
LINE_SPACINGS: dict[str, float] = {
    "1": LINE_SINGLE,
    "single": LINE_SINGLE,
    "1.08": 1.08,
    "1.1": 1.1,
    "1.15": LINE_TIGHT,
    "1.2": 1.2,
    "1.25": 1.25,
    "1.3": 1.3,
    "1.4": 1.4,
    "1.5": LINE_ONE_HALF,
    "1.6": 1.6,
    "1.7": 1.7,
    "1.75": LINE_LOOSE,
    "1.8": 1.8,
    "2": LINE_DOUBLE,
    "double": LINE_DOUBLE,
    "2.5": 2.5,
    "3": 3.0,
}

#: 中文口语写法 → 上表的键（"一倍" 和 "1.5 倍" 是人话，"1.5" 是表里的键）
_LINE_ALIASES: dict[str, str] = {
    "单倍": "1",
    "单倍行距": "1",
    "一倍": "1",
    "1倍": "1",
    "一倍行距": "1",
    "紧凑": "1.15",
    "紧一点": "1.15",
    "1.5倍": "1.5",
    "一点五倍": "1.5",
    "1.5倍行距": "1.5",
    "15倍": "1.5",
    "一倍半": "1.5",
    "1.25倍": "1.25",
    "1.75倍": "1.75",
    "双倍": "2",
    "两倍": "2",
    "2倍": "2",
    "双倍行距": "2",
    "多倍": "1.5",  # 「多倍行距」在 Word 里是「设成几倍」，默认给 1.5
    "固定值": "固定值28磅",
    "单倍间距": "1",
    "两倍间距": "2",
}


def resolve_line(value: float | Length | str | None) -> float | Length:
    """行距解析：`1.5` / `"1.5"` / `"一点五倍"` / `"固定值 28 磅"` / `Pt(28)`。

    返回浮点（倍数）或 Length（固定值）——python-docx 的 `line_spacing` 两种都收，
    正好对上 Word 里「多倍行距」和「固定值」两项。
    """
    if value is None:
        return LINE_ONE_HALF
    if isinstance(value, Length):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "").lower()
    if not text:
        return LINE_ONE_HALF
    # 固定值：固定值28磅 / fixed28 / 固定28
    if text.startswith(("固定", "fixed")):
        digits = text.removeprefix("固定值").removeprefix("固定").removeprefix("fixed")
        number = digits.removesuffix("磅").removesuffix("pt")
        try:
            return Pt(float(number))
        except ValueError:
            raise KeyError(f"认不出固定行距：{value}；写成「固定值28磅」或传 Pt(28)") from None
    # 「一点五倍」「1.5 倍行距」这类口语写法：原样、去掉「行距」、去掉「倍」各试一遍
    candidates = [text, text.removesuffix("行距"), text.removesuffix("倍")]
    for candidate in candidates:
        if candidate in _LINE_ALIASES:
            return resolve_line(_LINE_ALIASES[candidate])
        if candidate in LINE_SPACINGS:
            return LINE_SPACINGS[candidate]
    try:
        return float(text.removesuffix("倍"))
    except ValueError:
        raise KeyError(
            f"认不出行距：{value}；用倍数（1 / 1.15 / 1.5 / 2）或「固定值28磅」"
        ) from None


# --------------------------------------------------------------------------- #
# 四、首行缩进：按「字符」存，不按 pt
# --------------------------------------------------------------------------- #
#: 字符数 → 缩进字符数。2 是中文正文的默认（空两格）。
FIRST_LINE_INDENTS: dict[str, float] = {
    "0": 0.0,
    "none": 0.0,
    "1": 1.0,
    "2": 2.0,
    "3": 3.0,
    "4": 4.0,
    "5": 5.0,
    "6": 6.0,
    "8": 8.0,
}

_INDENT_ALIASES: dict[str, str] = {
    "不缩进": "0",
    "顶格": "0",
    "无": "0",
    "无缩进": "0",
    "0字符": "0",
    "一": "1",
    "一字符": "1",
    "空一格": "1",
    "两": "2",
    "二": "2",
    "两字符": "2",
    "2字符": "2",
    "首行缩进": "2",
    "首行缩进两字符": "2",
    "首行缩进2字符": "2",
    "空两格": "2",
    "三": "3",
    "三字符": "3",
    "四": "4",
    "四字符": "4",
}


def resolve_indent(value: float | str | None) -> float:
    """首行缩进解析：`2` / `"2"` / `"两字符"` / `"首行缩进2字符"` → 2.0（字符数）。

    为什么存字符数：2 字符在小四下是 24pt，换成四号就是 28pt。存 pt 的话，
    改一次字号就得把所有缩进值重算一遍，迟早漏一处。
    """
    if value is None:
        return 2.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    # 「首行缩进2字符」——去掉说明性的前缀，只留数字与单位
    text = text.removeprefix("首行缩进").removeprefix("首行").removeprefix("缩进")
    candidates = [text]
    for suffix in ("字符", "个字", "字", "格"):
        candidates.append(text.removesuffix(suffix))
    for candidate in candidates:
        key = _INDENT_ALIASES.get(candidate, candidate)
        if key in FIRST_LINE_INDENTS:
            return FIRST_LINE_INDENTS[key]
    try:
        return float(candidates[-1])
    except ValueError:
        raise KeyError(f"认不出首行缩进：{value}；用字符数（0 / 1 / 2）") from None


# --------------------------------------------------------------------------- #
# 五、对齐
# --------------------------------------------------------------------------- #
ALIGNMENTS: dict[str, str] = {
    "left": "left",
    "左": "left",
    "左对齐": "left",
    "靠左": "left",
    "顶格": "left",
    "center": "center",
    "centre": "center",
    "居中": "center",
    "居中显示": "center",
    "中间": "center",
    "middle": "center",
    "right": "right",
    "右": "right",
    "右对齐": "right",
    "靠右": "right",
    "justify": "justify",
    "两端对齐": "justify",
    "两端": "justify",
    "both": "justify",
    "distribute": "distribute",
    "分散对齐": "distribute",
    "分散": "distribute",
}


def resolve_align(value: str | None, default: str = "justify") -> str:
    """对齐方式解析成 left / center / right / justify / distribute。"""
    key = str(value or "").strip().lower()
    return ALIGNMENTS.get(key, default)


# --------------------------------------------------------------------------- #
# 六、标题刻度：一套文档只用一套
# --------------------------------------------------------------------------- #
#: 标题刻度名 → 四级标题的 (字体, 字号名)。
#: 同一篇里 h1 用 16、h2 用 15 是层级看不出差别的典型写法，所以这里成对给。
HEADING_SCALES: dict[str, tuple[tuple[str, str], ...]] = {
    # 商务报告 / 周报 / 方案：三号 / 四号 / 小四 / 小四
    "report": (("黑体", "三号"), ("黑体", "四号"), ("宋体", "小四"), ("宋体", "小四")),
    # 党政公文：正文仿宋三号，标题也三号，靠字体与加粗分层（GB/T 9704）
    "gongwen": (("黑体", "三号"), ("楷体", "三号"), ("宋体", "三号"), ("宋体", "三号")),
    # 论文 / 期刊：小二 / 小三 / 四号 / 小四
    "thesis": (("黑体", "小二"), ("黑体", "小三"), ("宋体", "四号"), ("宋体", "小四")),
    # 资料 / 说明书：以信息密度为先，整体小一档
    "compact": (("黑体", "四号"), ("黑体", "小四"), ("宋体", "小四"), ("宋体", "五号")),
    # 书籍 / 长篇：层级拉得更开，正文五号（印出来是书的字号）
    "book": (("黑体", "小三"), ("黑体", "四号"), ("黑体", "小四"), ("宋体", "小四")),
    # 合同 / 协议：条款靠编号分层，标题不加粗到刺眼，正文小四
    "contract": (("黑体", "四号"), ("宋体", "小四"), ("宋体", "小四"), ("宋体", "小四")),
    # 通知 / 公告：一级黑体三号，二级楷体三号，正文仿宋三号
    "notice": (("黑体", "三号"), ("楷体", "三号"), ("仿宋", "三号"), ("仿宋", "三号")),
    # 简历：层级紧、字号小，靠留白与加粗分层
    "resume": (
        ("微软雅黑", "四号"),
        ("微软雅黑", "小四"),
        ("微软雅黑", "小四"),
        ("微软雅黑", "五号"),
    ),
    # 讲稿 / 培训材料：字号大（台上看得清），层级少
    "lecture": (("黑体", "小二"), ("黑体", "三号"), ("黑体", "四号"), ("宋体", "四号")),
    # 操作手册：步骤多，层级细致
    "manual": (("黑体", "四号"), ("黑体", "小四"), ("宋体", "小四"), ("宋体", "五号")),
    # 简报 / 一页纸：一级四号就够，再大装不下一页
    "brief": (("黑体", "四号"), ("黑体", "小四"), ("宋体", "小四"), ("宋体", "五号")),
    # 白皮书 / 研究报告：标题与正文差两档
    "whitepaper": (("黑体", "小三"), ("黑体", "四号"), ("黑体", "小四"), ("宋体", "小四")),
}


def heading_specs(scale: str | None) -> list[tuple[str, str, float, bool]]:
    """刻度名 → 四级标题的 (中文字体, 西文字体, pt, 加粗)。默认 report。"""
    rows = HEADING_SCALES.get(str(scale or "report").strip().lower())
    if rows is None:
        raise KeyError(f"未知标题刻度：{scale}；可用：{'、'.join(HEADING_SCALES)}")
    specs: list[tuple[str, str, float, bool]] = []
    for font_name, size_name in rows:
        cn, en = FONTS.get(font_name, FONTS["宋体"])
        specs.append((cn, en, resolve_size(size_name), True))
    return specs


# --------------------------------------------------------------------------- #
# 七、页面：纸型与页边距（单位 cm，docx_utils 负责转成 Length）
# --------------------------------------------------------------------------- #
PAGES: dict[str, dict[str, float]] = {
    # Word 中文默认：A4、上下 2.54、左右 3.18
    "default": {
        "width": 21.0,
        "height": 29.7,
        "top": 2.54,
        "bottom": 2.54,
        "left": 3.18,
        "right": 3.18,
    },
    # 简报：一页讲完一件事，边距紧
    "brief": {
        "width": 21.0,
        "height": 29.7,
        "top": 1.8,
        "bottom": 1.8,
        "left": 2.2,
        "right": 2.2,
    },
    # 备忘 / 内部通知：上下略宽，留手写批注
    "memo": {
        "width": 21.0,
        "height": 29.7,
        "top": 2.4,
        "bottom": 2.4,
        "left": 2.6,
        "right": 2.6,
    },
    "compact": {
        "width": 21.0,
        "height": 29.7,
        "top": 2.0,
        "bottom": 2.0,
        "left": 2.0,
        "right": 2.0,
    },
    # 公文：GB/T 9704 上 3.7 / 下 3.5 / 左 2.8 / 右 2.6
    "gongwen": {
        "width": 21.0,
        "height": 29.7,
        "top": 3.7,
        "bottom": 3.5,
        "left": 2.8,
        "right": 2.6,
    },
    "thesis": {
        "width": 21.0,
        "height": 29.7,
        "top": 2.5,
        "bottom": 2.5,
        "left": 3.0,
        "right": 3.0,
    },
    "resume": {
        "width": 21.0,
        "height": 29.7,
        "top": 1.5,
        "bottom": 1.5,
        "left": 2.0,
        "right": 2.0,
    },
    "letter": {
        "width": 21.0,
        "height": 29.7,
        "top": 2.54,
        "bottom": 2.54,
        "left": 3.0,
        "right": 3.0,
    },
    # 横向 A4：宽表、甘特图、看板这类「一行放不下」的东西
    "landscape": {
        "width": 29.7,
        "height": 21.0,
        "top": 2.0,
        "bottom": 2.0,
        "left": 2.2,
        "right": 2.2,
    },
    # 大幅面：A3 折页、图纸、海报式单页
    "a3": {
        "width": 29.7,
        "height": 42.0,
        "top": 2.5,
        "bottom": 2.5,
        "left": 3.0,
        "right": 3.0,
    },
    # 小册子 / 便笺：A5
    "a5": {
        "width": 14.8,
        "height": 21.0,
        "top": 1.8,
        "bottom": 1.8,
        "left": 1.8,
        "right": 1.8,
    },
    # 书籍 / 期刊：B5（国内多数期刊的成品尺寸）
    "b5": {
        "width": 17.6,
        "height": 25.0,
        "top": 2.5,
        "bottom": 2.5,
        "left": 2.2,
        "right": 2.0,
    },
    # 16 开（教材、手册）：比 A4 略窄
    "16k": {
        "width": 18.4,
        "height": 26.0,
        "top": 2.5,
        "bottom": 2.5,
        "left": 2.2,
        "right": 2.0,
    },
    # 大 32 开（口袋本、说明书）
    "32k": {
        "width": 14.0,
        "height": 20.3,
        "top": 1.6,
        "bottom": 1.6,
        "left": 1.6,
        "right": 1.6,
    },
}


#: 纸型的口语写法 → PAGES 的键。「A4 横版」「16 开」「大 32 开」都会被这么写。
_PAGE_ALIASES: dict[str, str] = {
    "a4": "default",
    "a4纸": "default",
    "a4竖向": "default",
    "a4横版": "landscape",
    "a4横向": "landscape",
    "横版": "landscape",
    "横向": "landscape",
    "横排": "landscape",
    "a3纸": "a3",
    "a5纸": "a5",
    "b5纸": "b5",
    "16开": "16k",
    "十六开": "16k",
    "大32开": "32k",
    "32开": "32k",
    "三十二开": "32k",
    "公文纸": "gongwen",
    "简报": "brief",
    "备忘": "memo",
}


def page_spec(name: str) -> dict[str, Length]:
    """页面预设名 → 带 Length 的字典（直接喂给 `set_page`）。"""
    key = str(name or "default").strip().lower()
    key = _PAGE_ALIASES.get(key, key)
    rows = PAGES.get(key)
    if rows is None:
        raise KeyError(f"未知页面预设：{name}；可用：{'、'.join(PAGES)}")
    return {field: Cm(value) for field, value in rows.items()}


# --------------------------------------------------------------------------- #
# 八、表格样式名
# --------------------------------------------------------------------------- #
#: 模型十次有八次写成同义词（"three_line" / "全部框线" / "无边框"），收成一张对照表。
#: 四档正名：triple 三线表（学术/报表）、grid 全框线（台账/对照）、
#: zebra 隔行浅底（宽表，眼睛不会串行）、plain 无框线（简历/版式稿）。
TABLE_STYLES: dict[str, str] = {
    # ---- 三线表：上下粗线 + 表头下细线，学术与财报的标准 ----
    "triple": "triple",
    "three_line": "triple",
    "threeline": "triple",
    "three-line": "triple",
    "三线": "triple",
    "三线表": "triple",
    "学术表": "triple",
    "论文表": "triple",
    "报表": "triple",
    "booktabs": "triple",
    # ---- 全框线：国内办公最常用的那种「每格都画线」 ----
    "grid": "grid",
    "all": "grid",
    "full": "grid",
    "box": "grid",
    "全框线": "grid",
    "全部框线": "grid",
    "所有框线": "grid",
    "全边框": "grid",
    "网格": "grid",
    "框线": "grid",
    "有线": "grid",
    "带框线": "grid",
    "表格线": "grid",
    # ---- 隔行浅底：列多的宽表用它，眼睛不容易串行 ----
    "zebra": "zebra",
    "stripe": "zebra",
    "striped": "zebra",
    "banded": "zebra",
    "隔行": "zebra",
    "隔行变色": "zebra",
    "斑马线": "zebra",
    "斑马纹": "zebra",
    "交替底色": "zebra",
    # ---- 无框线：简历、版式稿、需要自己画边框的场合 ----
    "plain": "plain",
    "none": "plain",
    "no_border": "plain",
    "borderless": "plain",
    "无框线": "plain",
    "无边框": "plain",
    "不要框线": "plain",
    "无线": "plain",
    "空表": "plain",
}


# --------------------------------------------------------------------------- #
# 九、标题编号方案
# --------------------------------------------------------------------------- #
#: 编号方案，四个层级各一个模板。`{cn}` 是中文数字、`{n}` 是阿拉伯数字、
#: `{dot}` 是「到这一级为止用点连起来的序号」（1 / 1.1 / 1.1.1）。
#:
#: **一套方案里不许混用两种数字体系。** 「一、→（一）→1.→（1）」把汉字和阿拉伯
#: 数字串在同一条线上，读者扫标题时编号的字形一直在跳，看着像两个人拼的稿子。
#: 中文方案就一路中文（到中文能干净表达的层级为止），阿拉伯方案就一路阿拉伯。
#: 所以中文方案的三、四级留空——中文没有通行的第三级纯中文序号，硬凑只能借
#: 「1.」「①」这些外来的，就又混回去了。空模板 = 不编号，层级靠字号、加粗与
#: 缩进区分，这在中文报告里本来就是常态。
#:
#: `gb` 是唯一的例外：GB/T 9704《党政机关公文格式》明文规定层次序数为
#: 「一、→（一）→1.→（1）」，公文不这么写属于格式不合规。只有公文类文档取它。
#:
#: 为什么不统一一套：中文体系是业务汇报体，「1.1.1」是技术与学术体，
#: 「第一条」是合同体。编号是文体的一部分——论文用「一、」，看一眼就知道
#: 不是按论文规矩写的；公文用「1.1」，收文的人会觉得不像正式文件。
NUMBERING_SCHEMES: dict[str, tuple[str, str, str, str]] = {
    #           一级          二级          三级          四级
    "cn": ("{cn}、", "（{cn}）", "", ""),
    "decimal": ("{dot}. ", "{dot} ", "{dot} ", "{dot} "),
    "article": ("第{cn}条 ", "（{cn}）", "", ""),
    "none": ("", "", "", ""),
    "gb": ("{cn}、", "（{cn}）", "{n}. ", "（{n}）"),
}

#: 各级标题的左缩进，单位「字符」（1 字符 = 当前标题字号的一个字宽）。
#:
#: 一级顶格，往下每级缩 1 字符。缩 2 字符会过头：正文首行本来就空两格，
#: 标题也缩两格的话，标题左边缘和正文段首撞在同一条线上，正文的续行反而
#: 回到最左边——读起来像正文比标题还宽。一格刚好「看得出是下一层」而不越界。
#:
#: 为什么必须缩：1. 与 1.1 顶在同一条竖线上，读者只能靠「多看一个编号」判断
#: 谁是谁的下一层，扫标题时视线一直在重新对齐。缩进让层级在左边缘上就分得开。
#:
#: 四套方案现在同值。分开存是为了给某一套单独调留口子（比如合同想「（一）」跟
#: 「第一条」平齐，只改 article 这一行）；公文与紧凑版式由 `Preset.heading_indent`
#: 整篇关掉（GB/T 9704 规定各级标题顶格），不在这张表里表示。
NUMBERING_INDENTS: dict[str, tuple[float, float, float, float]] = {
    "cn": (0.0, 1.0, 2.0, 3.0),
    "decimal": (0.0, 1.0, 2.0, 3.0),
    "article": (0.0, 1.0, 2.0, 3.0),
    "none": (0.0, 1.0, 2.0, 3.0),
    "gb": (0.0, 1.0, 2.0, 3.0),
}

#: 口语说法 → 方案键。用户说「用 1.1.1 那种」，模型传「层级小数」也能落地。
NUMBERING_ALIASES: dict[str, str] = {
    "中文": "cn",
    "中文序号": "cn",
    "中文数字": "cn",
    "汉字": "cn",
    "chinese": "cn",
    # 公文的层次序数是国标规定的混排，单独一套；用户说「公文式」时按公文走
    "公文式": "gb",
    "公文": "gb",
    "国标": "gb",
    "gb": "gb",
    "gb9704": "gb",
    "层级小数": "decimal",
    "小数": "decimal",
    "技术": "decimal",
    "decimal": "decimal",
    "numeric": "decimal",
    "条": "article",
    "条款": "article",
    "第一条": "article",
    "article": "article",
    "无": "none",
    "不编号": "none",
    "none": "none",
    "plain": "none",
}


# --------------------------------------------------------------------------- #
# 十、文档类型 → 一整套版式参数
# --------------------------------------------------------------------------- #
#: 模型不用背「公文该多大字号」，认出「这是一份公文」就能取到整套。
#:
#: 各键：page 页面预设、scale 标题刻度、line 正文行距、table 表格样式、
#: indent 正文是否首行缩进（True = 缩进 2 字符）、align 正文对齐、number 编号方案。
#:
#: 铺到五十多类的理由和 `_HEADING_KEYS` 一样：模型判类型只判一次，判错了整套版式
#: 全歪——「述职报告」按「论文」排出来的样子，用户一眼就看出不是自己要的东西。
#: 表里没有的类型别硬套，默认那套（report）比套错一套强。
def _type(
    page: str = "default",
    scale: str = "report",
    line: float | Length = LINE_ONE_HALF,
    table: str = "grid",
    indent: bool = True,
    align: str = "justify",
    number: str = "cn",
) -> dict[str, Any]:
    """一行的版式组合。写全七项太占地方，这里给个具名简写。"""
    return {
        "page": page,
        "scale": scale,
        "line": line,
        "table": table,
        "indent": indent,
        "align": align,
        "number": number,
    }


DOC_TYPES: dict[str, dict[str, Any]] = {
    # 不写 number 的一律是 cn（一、/（一），三级以下不编号）——业务汇报用它，
    # 是默认值，写出来只会让表变长。下面只标出「不一样的那几类」。
    # ---- 例行汇报：结论先行、正文缩进、表格用全框线 ----
    "周报": _type(),
    "日报": _type(scale="compact", line=LINE_TIGHT, indent=False, align="left"),
    "月报": _type(),
    "季报": _type(),
    "半年报": _type(),
    "年报": _type(),
    "工作汇报": _type(),
    "项目汇报": _type(table="triple"),
    "述职报告": _type(table="triple"),
    "工作总结": _type(),
    "工作计划": _type(table="triple"),
    "工作要点": _type(scale="compact", line=LINE_TIGHT),
    # ---- 会议：左对齐不缩进（人名与时间要对齐，缩进反而乱）；也没有编号，
    #      纪要是按议题顺序记，不按 1.2.3 排 ----
    "会议纪要": _type(page="memo", indent=False, align="left", number="none"),
    "纪要": _type(page="memo", indent=False, align="left", number="none"),
    "会议记录": _type(
        page="memo", scale="compact", line=LINE_TIGHT, indent=False, align="left", number="none"
    ),
    "会议通知": _type(page="gongwen", scale="notice", line=LINE_FIXED_28, number="gb"),
    # ---- 方案 / 需求：取舍与代价是重点，三线表更清爽，编号走层级小数（1.1.1） ----
    "方案": _type(table="triple", number="decimal"),
    "技术方案": _type(table="triple", number="decimal"),
    "产品方案": _type(table="triple", number="decimal"),
    "产品需求": _type(table="triple", number="decimal"),
    "需求文档": _type(table="triple", number="decimal"),
    "可行性研究": _type(table="triple", number="decimal"),
    "立项报告": _type(table="triple", number="decimal"),
    # ---- 研究 / 报告：读者会顺着「3.2.1」去引用某一节，中文序号指代不了 ----
    "报告": _type(table="triple", number="decimal"),
    "调研报告": _type(table="triple", number="decimal"),
    "分析报告": _type(table="triple", number="decimal"),
    "实验报告": _type(page="thesis", scale="thesis", table="triple", number="decimal"),
    "研究报告": _type(page="thesis", scale="whitepaper", table="triple", number="decimal"),
    "白皮书": _type(page="thesis", scale="whitepaper", table="triple", number="decimal"),
    # ---- 公文：GB/T 9704 那一套，正文仿宋三号、固定 28 磅，「一、（一）1.」是规定 ----
    #      注意这里的 number 是 gb 而不是 cn：cn 只到「（一）」，三级起不编号。
    #      公文不能这么省——国标把四层序数写死了，少一层就是格式不合规。
    "公文": _type(page="gongwen", scale="gongwen", line=LINE_FIXED_28, number="gb"),
    "通知": _type(page="gongwen", scale="gongwen", line=LINE_FIXED_28, number="gb"),
    "通报": _type(page="gongwen", scale="gongwen", line=LINE_FIXED_28, number="gb"),
    "公告": _type(page="gongwen", scale="notice", line=LINE_FIXED_28, number="gb"),
    "请示": _type(page="gongwen", scale="gongwen", line=LINE_FIXED_28, number="gb"),
    "批复": _type(page="gongwen", scale="gongwen", line=LINE_FIXED_28, number="gb"),
    "函": _type(page="gongwen", scale="gongwen", line=LINE_FIXED_28, table="plain", number="gb"),
    "意见": _type(page="gongwen", scale="gongwen", line=LINE_FIXED_28, number="gb"),
    "决定": _type(page="gongwen", scale="gongwen", line=LINE_FIXED_28, number="gb"),
    "简报": _type(
        page="brief", scale="brief", line=LINE_TIGHT, indent=False, align="left", number="none"
    ),
    # ---- 学术：1. / 1.1 / 1.1.1，和引用格式（GB/T 7714）对得上 ----
    "论文": _type(page="thesis", scale="thesis", table="triple", number="decimal"),
    "开题报告": _type(page="thesis", scale="thesis", table="triple", number="decimal"),
    "文献综述": _type(page="thesis", scale="thesis", table="triple", number="decimal"),
    "课程作业": _type(page="thesis", table="triple", number="decimal"),
    # ---- 说明 / 手册：信息密度优先，顶格排，条目靠加粗与缩进区分，不编号 ----
    "说明书": _type(
        page="compact", scale="manual", line=LINE_TIGHT, indent=False, align="left", number="none"
    ),
    "操作手册": _type(
        page="compact", scale="manual", line=LINE_TIGHT, indent=False, align="left", number="none"
    ),
    "用户手册": _type(
        page="compact", scale="manual", line=LINE_TIGHT, indent=False, align="left", number="none"
    ),
    "培训材料": _type(scale="lecture", line=LINE_LOOSE, indent=False, align="left", number="none"),
    "常见问题": _type(
        page="compact", scale="manual", line=LINE_TIGHT, indent=False, align="left", number="none"
    ),
    # ---- 事务 / 商务 ----
    "简历": _type(
        page="resume",
        scale="resume",
        line=LINE_FIXED_22,
        table="plain",
        indent=False,
        align="left",
        number="none",
    ),
    "信函": _type(page="letter", scale="notice", table="plain", number="none"),
    # 合同按「第一条」数，不是「一、」——条款要能被指着念
    "合同": _type(scale="contract", indent=False, number="article"),
    "协议": _type(scale="contract", indent=False, number="article"),
    "标书": _type(scale="whitepaper", number="decimal"),
    "讲话稿": _type(scale="lecture", line=LINE_FIXED_32, table="plain", number="none"),
    "演讲稿": _type(scale="lecture", line=LINE_FIXED_32, table="plain", number="none"),
    "新闻稿": _type(scale="brief", table="plain", indent=False, align="left", number="none"),
    "证明": _type(page="letter", scale="notice", table="plain", number="none"),
    "申请书": _type(page="letter", scale="notice", table="plain", number="none"),
}

#: 类型名的口语写法 → DOC_TYPES 的键。「周工作报告」「weekly」「工作周报」都会出现。
#:
#: 收词口径：**用户不会按我们表里的类型名说话**。他说「给领导汇报用的那个」、
#: 说「这周的周报」、说「投标文件」，都可能落到同一个键上；也有直接甩英文的
#: （weekly / prd / minutes）。少收一条的代价不是「判错」，而是判不出来——
#: `guess_doc_type` 认不出就落回默认那套，编号款式跟着不对，用户只会觉得
#: 「它没听懂我说的是周报」。所以这张表按「同义说法」铺厚，不按「类型名单」铺。
DOC_TYPE_ALIASES: dict[str, str] = {
    # ---- 例行汇报 ----
    "周工作报告": "周报",
    "工作周报": "周报",
    "本周周报": "周报",
    "周汇报": "周报",
    "周报稿": "周报",
    "weekly": "周报",
    "weeklyreport": "周报",
    "日报表": "日报",
    "日汇报": "日报",
    "每日汇报": "日报",
    "daily": "日报",
    "工作月报": "月报",
    "月度报告": "月报",
    "月度汇报": "月报",
    "monthly": "月报",
    "季度报告": "季报",
    "季度汇报": "季报",
    "quarterly": "季报",
    "年度报告": "年报",
    "年度汇报": "年报",
    "annual": "年报",
    "汇报材料": "工作汇报",
    "汇报稿": "工作汇报",
    "项目进展汇报": "项目汇报",
    "项目汇报材料": "项目汇报",
    "述职": "述职报告",
    "述职汇报": "述职报告",
    "述职材料": "述职报告",
    "年度总结": "工作总结",
    "工作总结稿": "工作总结",
    "工作计划表": "工作计划",
    "工作要点清单": "工作要点",
    # ---- 会议 ----
    "会议记录整理": "会议纪要",
    "会议纪录": "会议纪要",
    "纪要稿": "会议纪要",
    "会议摘要": "会议纪要",
    "minutes": "会议纪要",
    "meetingnotes": "会议纪要",
    "会议记录稿": "会议记录",
    # ---- 方案 / 需求 ----
    "方案文档": "方案",
    "方案稿": "方案",
    "实施方案": "方案",
    "解决方案": "方案",
    "项目方案": "方案",
    "product": "产品需求",
    "需求说明书": "需求文档",
    "需求规格": "需求文档",
    "prd": "需求文档",
    "可行性分析": "可行性研究",
    "立项申请": "立项报告",
    # ---- 研究 / 报告 ----
    "复盘报告": "分析报告",
    "总结报告": "报告",
    "情况报告": "报告",
    "评估报告": "报告",
    "验收报告": "报告",
    "测试报告": "报告",
    "研究报告书": "研究报告",
    "调研": "调研报告",
    # ---- 公文 ----
    "党政公文": "公文",
    "官方公文": "公文",
    "红头文件": "公文",
    "正式通知": "通知",
    "notice": "通知",
    "工作简报": "简报",
    "情况简报": "简报",
    # ---- 学术 ----
    "期刊论文": "论文",
    "学位论文": "论文",
    "毕业设计": "论文",
    "毕业论文": "论文",
    "小论文": "论文",
    "课程论文": "论文",
    "thesis": "论文",
    "paper": "论文",
    "开题": "开题报告",
    "文献回顾": "文献综述",
    # ---- 说明 / 手册 ----
    "产品说明书": "说明书",
    "使用说明": "说明书",
    "操作指南": "操作手册",
    "用户指南": "用户手册",
    "使用手册": "用户手册",
    "手册": "操作手册",
    "handbook": "操作手册",
    "manual": "操作手册",
    "faq": "常见问题",
    "答疑": "常见问题",
    "培训讲义": "培训材料",
    "课件": "培训材料",
    # ---- 事务 / 商务 ----
    "个人简历": "简历",
    "求职简历": "简历",
    "resume": "简历",
    "cv": "简历",
    "letter": "信函",
    "信件": "信函",
    "contract": "合同",
    "协议书": "协议",
    "框架协议": "协议",
    "投标文件": "标书",
    "投标书": "标书",
}


def resolve_doc_type(name: str | None) -> dict[str, Any]:
    """文档类型名 → 整套版式参数；认不出就返回默认那套，不抛异常。

    这里和 `heading_specs` / `page_spec` 的取向相反：那两个认不出要报错（写错了
    脚本就白跑，得让人看见），这里认不出要能继续——「这是一份述职报告」判错一个
    词，不该让整份文档生成失败。
    """
    key = str(name or "").strip()
    key = DOC_TYPE_ALIASES.get(key, key)
    rows = DOC_TYPES.get(key)
    if rows is not None:
        return dict(rows)
    # 「工作周报（第 46 周）」这类带括号说明的写法：取括号前那段再试一次
    head = key.split("（", 1)[0].split("(", 1)[0].strip()
    rows = DOC_TYPES.get(head) or DOC_TYPES.get(DOC_TYPE_ALIASES.get(head, head))
    return dict(rows) if rows else _type()


def resolve_numbering(name: str | None) -> str:
    """编号方案名（或文档类型名）→ `NUMBERING_SCHEMES` 的键之一。

    两种入参都收：`resolve_numbering("decimal")` 是直接点方案，
    `resolve_numbering("论文")` 是给类型让它自己挑。认不出落回 `cn`——
    中文序号在国内办公文档里最不容易出错，即使挑错了也只是编号款式不对，
    不会让整份文档读不通。
    """
    key = str(name or "").strip()
    lowered = key.lower()
    if key in NUMBERING_SCHEMES:
        return key
    if lowered in NUMBERING_SCHEMES:
        return lowered
    alias = NUMBERING_ALIASES.get(key) or NUMBERING_ALIASES.get(lowered)
    if alias:
        return alias
    scheme = resolve_doc_type(key).get("number", "cn")
    return scheme if scheme in NUMBERING_SCHEMES else "cn"


def heading_indents(name: str | None) -> tuple[float, float, float, float]:
    """编号方案（或文档类型）→ 四级标题的左缩进（字符）。

    认不出就按 `cn` 那套，和 `resolve_numbering` 的落点保持一致——编号用哪套、
    缩进就得跟哪套，两者分开算会出现「编号是一、而缩进按 decimal」的错位。
    """
    return NUMBERING_INDENTS.get(resolve_numbering(name), NUMBERING_INDENTS["cn"])


#: 类型键与别名放在一张表里按长度倒序匹配——「述职报告」必须排在「报告」前面，
#: 否则一句「本周述职报告」会被判成普通的「报告」，编号也跟着从 cn 变 decimal。
#:
#: 两类词要一起排，不能「先找类型键、找不到再找别名」：那样「年度报告」会先命中
#: 类型键「报告」（2 个字），别名「年度报告」（4 个字）根本没机会——用户明明说的是
#: 年报，判出来却是普通报告。长词优先才符合「谁更具体信谁」。
_GUESS_CANDIDATES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        [(key, key) for key in DOC_TYPES] + list(DOC_TYPE_ALIASES.items()),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def guess_doc_type(*texts: str | None) -> str:
    """从一句话里认出这是什么文档（「W46 周报」「第三章 论文初稿」）。

    给的是「猜」不是「判」：认不出返回空串，让调用方落回默认，不抛异常。
    用途是让模型不必显式传 doc_type 也能拿到对的那套编号——标题里写着「周报」，
    就按周报排，而不是按默认那套。
    """
    haystack = " ".join(str(text or "") for text in texts).strip()
    if not haystack:
        return ""
    for word, target in _GUESS_CANDIDATES:
        if word in haystack:
            return target
    return ""
