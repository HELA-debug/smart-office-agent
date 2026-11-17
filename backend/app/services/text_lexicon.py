"""text_lexicon.py —— 纯文本 / Markdown 的词表（唯一真相）。

纯文本没有字号、没有加粗，只有三样东西能用来分层：**空行、符号、缩进**。
这里的词表就管这三样：章节用什么括起来、条目用什么符号、定宽排版折多少字。

**为什么值得单开一份。** 以前这些字符散在各处：`text_utils.txt_wrap` 默认 40、
`doc.render_text` 手写 `【】`、`normalize_markdown` 自己认 `#`。同一个「一级标题」
在 txt、md、日志三种输出里长得不一样，用户拿同一份稿子导出两次会觉得工具不稳。

**怎么加。**
- 加符号：`BULLETS["方块"] = "■"`，再在 `BULLET_ALIASES` 里补口语名。
- 加布局：`TEXT_LAYOUTS["日志"] = {...}`，四个键都给全（行宽/缩进/条目/分隔）。
- 加章节标记：`SECTION_MARKS` 里补一对左右符号，`render_text` 直接用。

**约定。** 正文**不手动折行**：一段一行，折行交给打开它的程序（记事本 / WPS / 预览都会
自己按窗口宽度折）。这里的宽度只服务定宽排版（ASCII 表格、条形图、逐行对齐的清单）——
中文 38 个汉字（半角 76 宽）是那种场合下的舒服宽度，不是正文该有的换行位置。
"""

from __future__ import annotations

__all__ = [
    "BULLETS",
    "BULLET_ALIASES",
    "LINE_WIDTH",
    "SECTION_MARKS",
    "SEPARATORS",
    "TEXT_LAYOUTS",
    "bullet_char",
    "heading_mark",
    "resolve_text_layout",
    "section_mark",
]

# --------------------------------------------------------------------------- #
# 一、折行宽度
# --------------------------------------------------------------------------- #
# ⚠️ 正文不折行：一段一行，折行交给打开它的程序（记事本 / WPS / 预览自己会折）。
# 手动折的代价是断点吃掉空格、换字号就错位、句子被切在词中间——用户 2026-11-16 否掉过。
# 下面这几个宽度只服务「定宽排版」：ASCII 表格、条形图、要逐行对齐的清单。
#: 一行多少个「半角宽度」。中文算 2、西文算 1，所以 76 宽 ≈ 38 个汉字。
LINE_WIDTH = 76
#: 代码、命令行用更宽的折行（代码折在中间就没法复制了）。
CODE_WIDTH = 100
#: 手机端、聊天窗口里贴的短文本。
NARROW_WIDTH = 50

# --------------------------------------------------------------------------- #
# 二、分隔线：只用三种字符，且整行铺满
# --------------------------------------------------------------------------- #
#: 分隔线名 → 字符。一条分隔线要么 「=」要么「-」，混着用会让读者以为层级不同。
SEPARATORS: dict[str, str] = {
    "major": "=",  # 大分区（章）
    "minor": "-",  # 小节
    "dot": "·",  # 注意：中文排版里「·」也可以当分隔，但一行连排会看成省略号
    "star": "*",
}

# --------------------------------------------------------------------------- #
# 三、条目符号
# --------------------------------------------------------------------------- #
#: 符号名 → 字符。同一个列表里只用一种，混用等于告诉读者「这两组不一样」，
#: 而实际上只是手抖换了个符号。
BULLETS: dict[str, str] = {
    "dot": "·",  # 中文最常用
    "dash": "-",  # Markdown、代码注释
    "circle": "○",  # 二级（空心）
    "square": "■",  # 强调型
    "diamond": "◆",
    "arrow": "→",  # 结论、因果
    "check": "√",  # 已完成事项
    "cross": "×",  # 未通过
}

#: 口语写法 → 上表的键。
BULLET_ALIASES: dict[str, str] = {
    "圆点": "dot",
    "点": "dot",
    "·": "dot",
    "横线": "dash",
    "-": "dash",
    "空心": "circle",
    "圈": "circle",
    "方框": "square",
    "方块": "square",
    "菱形": "diamond",
    "箭头": "arrow",
    "勾": "check",
    "对勾": "check",
    "叉": "cross",
}


def bullet_char(name: str | None = "dot") -> str:
    """符号名 → 字符。认不出给「·」——中文列表的默认。"""
    key = str(name or "dot").strip()
    key = BULLET_ALIASES.get(key, key)
    return BULLETS.get(key, BULLETS["dot"])


# --------------------------------------------------------------------------- #
# 四、章节标记
# --------------------------------------------------------------------------- #
#: 章节名 → (左, 右)。纯文本没法加粗，只能靠标记把标题从正文里挑出来。
#: `【一、进展】` 是最常见的写法，也是最不容易和正文撞的写法（正文很少用【】开句）。
SECTION_MARKS: dict[str, tuple[str, str]] = {
    "bold": ("【", "】"),
    "square": ("［", "］"),
    "angle": ("《", "》"),
    "hash": ("## ", ""),
    "line": ("--- ", " ---"),
}

#: 章节标记的口语写法。
_MARK_ALIASES: dict[str, str] = {
    "方括号": "bold",
    "中括号": "bold",
    "【": "bold",
    "markdown": "hash",
    "md": "hash",
}


def section_mark(name: str | None = "bold") -> tuple[str, str]:
    """章节标记名 → (左, 右)。"""
    key = str(name or "bold").strip()
    key = _MARK_ALIASES.get(key, key)
    return SECTION_MARKS.get(key, SECTION_MARKS["bold"])


def heading_mark(level: int) -> str:
    """层级 → 前缀。1 → `一、`，2 → `（一）`，3 → `1.`，4 → `（1）`。

    纯文本的编号只能手写（没有样式系统），所以这里给一套固定的四级编号，
    脚本和模板都从这里取，免得一份稿子里「一、」和「1、」混着出现。
    """
    depth = max(1, min(int(level), 4))
    return {1: "一、", 2: "（一）", 3: "1. ", 4: "（1）"}[depth]


# --------------------------------------------------------------------------- #
# 五、文本布局
# --------------------------------------------------------------------------- #
#: 布局名 → 行宽 / 是否缩进 / 条目符号 / 分隔线。
#:
#: - `plain`：广义的正文，折行 76、不缩进（纯文本里缩进靠空格，改字号就废）；
#: - `outline`：大纲、纪要，条目优先，折行窄一点；
#: - `log`：日志、工单，一行一条，不折行（折了就没法按行 grep）；
#: - `dialogue`：访谈、会议逐字稿，「姓名：」开头，不折行；
#: - `checklist`：清单、待办，用 √ / ×。
TEXT_LAYOUTS: dict[str, dict[str, object]] = {
    "plain": {"width": LINE_WIDTH, "indent": 0, "bullet": "dot", "rule": "minor"},
    "outline": {"width": NARROW_WIDTH, "indent": 2, "bullet": "dot", "rule": "major"},
    "log": {"width": 0, "indent": 0, "bullet": "dash", "rule": "minor"},
    "dialogue": {"width": 0, "indent": 0, "bullet": "dot", "rule": "minor"},
    "checklist": {"width": NARROW_WIDTH, "indent": 0, "bullet": "check", "rule": "minor"},
}

#: 布局的口语写法。
_LAYOUT_ALIASES: dict[str, str] = {
    "正文": "plain",
    "默认": "plain",
    "大纲": "outline",
    "纪要": "outline",
    "日志": "log",
    "工单": "log",
    "逐字稿": "dialogue",
    "访谈": "dialogue",
    "清单": "checklist",
    "待办": "checklist",
    "todo": "checklist",
    # 「就直接给我文字」「不要排版」也是同一件事
    "纯文本": "plain",
    "平铺": "plain",
    "不要排版": "plain",
    "提纲": "outline",
    "框架": "outline",
    "结构": "outline",
    "工作日志": "log",
    "记录": "log",
    "对话": "dialogue",
    "采访": "dialogue",
    "问答": "dialogue",
    "待办清单": "checklist",
    "检查表": "checklist",
    "checklist": "checklist",
}


def resolve_text_layout(name: str | None) -> dict[str, object]:
    """布局名 → 参数。认不出给 plain（正文）。"""
    key = str(name or "plain").strip().lower()
    key = _LAYOUT_ALIASES.get(key, key)
    return dict(TEXT_LAYOUTS.get(key, TEXT_LAYOUTS["plain"]))
