"""slide_lexicon.py —— PPT 的词表（唯一真相）。

`doc_lexicon` 管 Word 的字号字体，这里管幻灯片的那一套：画幅、版式、每页装多少、
字号多大、用什么配色。为什么要单开一份——幻灯片的「大」和文档的「大」不是一个量级：
文档正文 12pt 是常态，幻灯片正文 12pt 投影到墙上等于没写。两套刻度塞一张表里，
迟早有人照着文档的字号去排 PPT。

**怎么加。**
- 加画幅：`SLIDE_SIZES["16:10"] = (12192000, 7620000)`（EMU，1 英寸 = 914400）。
- 加版式：`SLIDE_LAYOUTS["timeline"] = {...}`，再把口语名塞进 `SLIDE_TYPES`。
- 加配色：`THEMES["党政红"] = {...}` 四个色值都给（底/标题/正文/强调），少给一个就花。
- 加规则：`MAX_*` 那几行是硬约束，`pptx_utils` 生成时按它们截断。

**约定。** 一页六条要点、一条不超过 42 个字符、标题不超过 22 个字符。
超了就拆页——投影出来没人读得完十二条，那不是信息多，那是没想清楚要说什么。
"""

from __future__ import annotations

__all__ = [
    "FONT_SIZES",
    "MAX_BULLETS_PER_SLIDE",
    "MAX_BULLET_CHARS",
    "MAX_TITLE_CHARS",
    "SLIDE_LAYOUTS",
    "SLIDE_SIZES",
    "SLIDE_TYPES",
    "THEMES",
    "THEME_NAMES",
    "layout_spec",
    "resolve_layout",
    "resolve_theme",
    "slide_size",
]

# --------------------------------------------------------------------------- #
# 一、画幅（EMU）
# --------------------------------------------------------------------------- #
#: 画幅名 → (宽, 高)。EMU 是 PowerPoint 的原生单位，别换算成 cm 再换回来，
#: 来回一除就有几百 EMU 的误差，页边距会一页一个样。
SLIDE_SIZES: dict[str, tuple[int, int]] = {
    "16:9": (12192000, 6858000),  # 默认：投影、线上分享都是这个
    "4:3": (9144000, 6858000),  # 老会议室、打印讲义
    "16:10": (12192000, 7620000),  # 笔记本全屏演示
    "a4横": (11203200, 7930025),  # 要打印成 A4 讲义时用（21×29.7cm 横放）
    "竖版": (6858000, 12192000),  # 手机端阅读、信息长图
}

#: 画幅的口语写法 → 上表的键。
_SIZE_ALIASES: dict[str, str] = {
    "宽屏": "16:9",
    "宽屏16:9": "16:9",
    "169": "16:9",
    "default": "16:9",
    "标准": "4:3",
    "43": "4:3",
    "a4": "a4横",
    "a4横向": "a4横",
    "手机": "竖版",
    "长图": "竖版",
    "vertical": "竖版",
}


def slide_size(name: str | None) -> tuple[int, int]:
    """画幅名 → (宽, 高) EMU。认不出给 16:9——这是投影仪的事实标准。"""
    key = str(name or "16:9").strip().lower().replace(" ", "")
    key = _SIZE_ALIASES.get(key, key)
    return SLIDE_SIZES.get(key, SLIDE_SIZES["16:9"])


# --------------------------------------------------------------------------- #
# 二、版式：一页只干一件事
# --------------------------------------------------------------------------- #
#: 版式名 → 这一页装什么、几条要点、什么对齐。
#: `bullets` 是这一页能装几条，`align` 是正文对齐，`hero` 表示「大字版」（少字大字号）。
SLIDE_LAYOUTS: dict[str, dict[str, object]] = {
    # 封面：标题 + 一行副标题（谁、什么时候、给谁看）。不要放要点。
    "cover": {"bullets": 0, "align": "center", "hero": True},
    # 目录：三到六条，一条一个词，不要句子
    "toc": {"bullets": 6, "align": "left", "hero": False},
    # 章节页：整页只写「一、进展」这种，用来换气
    "section": {"bullets": 0, "align": "left", "hero": True},
    # 标准要点页：这是绝大多数页的形态
    "bullets": {"bullets": 6, "align": "left", "hero": False},
    # 两栏对照：现状 / 目标、方案 A / 方案 B
    "two_col": {"bullets": 4, "align": "left", "hero": False},
    # 数据页：三到五个大数字 + 口径，别放表
    "data": {"bullets": 5, "align": "center", "hero": True},
    # 表格页：最多 5 列 × 6 行，超了就拆
    "table": {"bullets": 6, "align": "left", "hero": False},
    # 引用页：一句原话 + 出处
    "quote": {"bullets": 1, "align": "center", "hero": True},
    # 结论 / 收尾：一行结论 + 要他做的一件事
    "closing": {"bullets": 3, "align": "left", "hero": True},
}

#: 版式的口语写法。模型和用户会写「封面页」「目录页」「分节页」「对比页」。
SLIDE_TYPES: dict[str, str] = {
    "cover": "cover",
    "封面": "cover",
    "封面页": "cover",
    "首页": "cover",
    "标题页": "cover",
    "toc": "toc",
    "目录": "toc",
    "目录页": "toc",
    "大纲": "toc",
    "agenda": "toc",
    "section": "section",
    "章节页": "section",
    "分节页": "section",
    "过渡页": "section",
    "bullets": "bullets",
    "要点": "bullets",
    "要点页": "bullets",
    "正文页": "bullets",
    "列表": "bullets",
    "two_col": "two_col",
    "两栏": "two_col",
    "对比": "two_col",
    "对照": "two_col",
    "data": "data",
    "数据": "data",
    "数据页": "data",
    "数字": "data",
    "table": "table",
    "表格": "table",
    "表格页": "table",
    "quote": "quote",
    "引用": "quote",
    "引语": "quote",
    "closing": "closing",
    "结尾": "closing",
    "收尾": "closing",
    "谢谢": "closing",
    "结论": "closing",
    # 同一页在不同人嘴里叫法不同：写 PPT 的人说「扉页 / 转场 / 金句页」，
    # 汇报的人说「封底 / 问答」，产品的人说「KPI 页」
    "title": "cover",
    "titlepage": "cover",
    "扉页": "cover",
    "封面图": "cover",
    "大标题页": "cover",
    "contents": "toc",
    "outline": "toc",
    "提纲": "toc",
    "议程": "toc",
    "chapter": "section",
    "章节": "section",
    "转场": "section",
    "分节": "section",
    "content": "bullets",
    "内容页": "bullets",
    "文字页": "bullets",
    "要点列表": "bullets",
    "双栏": "two_col",
    "并列": "two_col",
    "对比页": "two_col",
    "左图右文": "two_col",
    "comparison": "two_col",
    "指标": "data",
    "指标页": "data",
    "kpi": "data",
    "metrics": "data",
    "图表页": "data",
    "数据表": "table",
    "明细表": "table",
    "金句": "quote",
    "名言": "quote",
    "语录": "quote",
    "致谢": "closing",
    "封底": "closing",
    "结束页": "closing",
    "问答": "closing",
    "q&a": "closing",
    "thanks": "closing",
    "thankyou": "closing",
}


def resolve_layout(name: str | None) -> str:
    """版式名 → 正名；认不出按要点页处理（大多数页本来就是要点页）。"""
    key = str(name or "bullets").strip().lower()
    return SLIDE_TYPES.get(key, "bullets")


def layout_spec(name: str | None) -> dict[str, object]:
    """版式名 → 这一页的参数（几条、怎么对齐、是不是大字版）。"""
    return SLIDE_LAYOUTS[resolve_layout(name)]


# --------------------------------------------------------------------------- #
# 三、字号（pt，随画幅与版式走）
# --------------------------------------------------------------------------- #
#: 角色 → pt。幻灯片字号比文档大一档是常识：投影出来再看，18pt 只相当于文档的 10pt。
#: 括号里是 `pptx_utils` 写进 XML 的 `sz` 值（1/100 pt）。
FONT_SIZES: dict[str, float] = {
    "cover_title": 40.0,  # 封面主标题：一页只有它，可以很大
    "cover_sub": 20.0,  # 封面副标题：谁/何时/给谁看
    "section": 36.0,  # 章节页的「一、进展」（和封面标题同档，换气用）
    "title": 36.0,  # 内页标题：投影时后排也能一眼扫到
    "subtitle": 20.0,  # 标题下的一句结论
    "body": 20.0,  # 正文与要点：一页六条时 20pt 正好
    "bullet": 20.0,
    "data": 40.0,  # 数据页的大数字
    "table": 14.0,  # 表格：再大就装不下
    "note": 12.0,  # 图注、口径、来源
    "page_no": 10.0,
}

#: 一页最多几条要点。超过六条，后排就不看了。
MAX_BULLETS_PER_SLIDE = 6
#: 一条要点最多多少字符（中文按字算）。一行放不下就要读两行，读两行就不叫要点了。
MAX_BULLET_CHARS = 42
#: 页标题最多多少字符。标题一长，字号只能缩，缩到正文大小就没了层级。
MAX_TITLE_CHARS = 22

# --------------------------------------------------------------------------- #
# 四、配色
# --------------------------------------------------------------------------- #
#: 主题名 → 底/标题/正文/强调四个色值。四个都给全：只给强调色，其它三处就会
#: 掉回 PowerPoint 默认的黑白，看着像没做。
#:
#: 选色原则：背景只用白/极浅灰/深色三种，标题与正文同色系但差一档亮度，
#: 强调色全篇只表达一件事（通常是「结论」或「要他拍板」）。
THEMES: dict[str, dict[str, str]] = {
    # 商务蓝：最稳，不需要选的时候用它
    "商务蓝": {"bg": "FFFFFF", "title": "1F3A5F", "body": "33383F", "accent": "2F80ED"},
    # 极简黑白：报告、评审，不想让颜色抢话
    "极简": {"bg": "FFFFFF", "title": "111418", "body": "3F444B", "accent": "6B7280"},
    # 科技深色：产品发布、技术分享
    "深色": {"bg": "111827", "title": "F3F4F6", "body": "D1D5DB", "accent": "22D3EE"},
    # 党政红：党建、政务汇报
    "党政红": {"bg": "FFFFFF", "title": "9B1B1B", "body": "33383F", "accent": "C12B2B"},
    # 学术灰绿：论文答辩、研究报告
    "学术": {"bg": "FCFCFA", "title": "1F2933", "body": "3E4C59", "accent": "2F6F5E"},
}

#: 主题的口语写法。
_THEME_ALIASES: dict[str, str] = {
    "blue": "商务蓝",
    "business": "商务蓝",
    "默认": "商务蓝",
    "简约": "极简",
    "minimal": "极简",
    "dark": "深色",
    "科技": "深色",
    "红": "党政红",
    "党建": "党政红",
    "政务": "党政红",
    "学术": "学术",
    "绿色": "学术",
    # 「蓝色」「蓝白」「稳重一点」都是指同一套配色，不必让用户猜正名
    "蓝": "商务蓝",
    "蓝色": "商务蓝",
    "蓝白": "商务蓝",
    "商务": "商务蓝",
    "稳重": "商务蓝",
    "黑白": "极简",
    "浅色": "极简",
    "干净": "极简",
    "light": "极简",
    "简洁": "极简",
    "深色系": "深色",
    "暗色": "深色",
    "tech": "深色",
    "红色": "党政红",
    "党政风": "党政红",
    "红金": "党政红",
    "学术风": "学术",
    "绿": "学术",
    "青色": "学术",
}


def resolve_theme(name: str | None) -> dict[str, str]:
    """主题名 → 四个色值。认不出给商务蓝（最不容易出错的一套）。"""
    key = str(name or "商务蓝").strip()
    key = _THEME_ALIASES.get(key, key)
    return dict(THEMES.get(key, THEMES["商务蓝"]))


#: 配色方案的名字清单，给提示词用。
THEME_NAMES: tuple[str, ...] = tuple(THEMES)
