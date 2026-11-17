"""sheet_lexicon.py —— Excel 的词表（唯一真相）。

`doc_lexicon` 管「字号多大」，这里管「这一列该长什么样」：金额带不带千分位、
占比存 0.12 还是 12%、日期写成 2026-11-08 还是 2026/11/8、列宽给多少。

**为什么要有这一份。** 表格里最容易出错的不是内容，是格式：

- 金额写成文本，右键求和是 0；
- 占比存成 12.5 再加个 `%` 号，等于 1250%，看着像涨了两百倍；
- 日期列宽 8 个字符，格子显示成 `####`；
- 编号列被 Excel 自动转成科学计数，`00123` 变成 `123`。

这几种错都不是模型「不知道」，而是没人告诉它「看到这种列名该怎么设」。所以这里把
「列名 → 格式」写成对照表，`xlsx_utils.write_table` 落盘时自动套一遍。

**怎么加。**
- 加格式：`NUMBER_FORMATS["工时"] = "0.0"`，值是 Excel 的自定义格式串。
- 加列名：`COLUMN_KEYWORDS["回款"] = "金额"`，只用来归类，不写新格式。
- 加表类型：`SHEET_TYPES["考勤"] = {...}`，五件事都给全（冻结/筛选/合计/表头/列宽）。
- 加版式：`SHEET_PRESETS["发票"] = {...}`，字号/字体/框线/行高都写**语义名**
  （`"正文"` / `"细"` / `"网格"`），真实数值在上面那几张子表里——一张表只有一个数字版本。
"""

from __future__ import annotations

import re

__all__ = [
    "BORDERS",
    "COLUMN_KEYWORDS",
    "COLUMN_WIDTHS",
    "HEADER_COLOR",
    "HEADER_FILL",
    "MAX_COLS_HINT",
    "MAX_ROWS_HINT",
    "NUMBER_FORMATS",
    "ROW_HEIGHTS",
    "SHEET_FONTS",
    "SHEET_PRESETS",
    "SHEET_PRESET_ALIASES",
    "SHEET_SIZES",
    "SHEET_TYPES",
    "format_for",
    "guess_formats",
    "guess_widths",
    "resolve_preset",
    "resolve_sheet_type",
    "width_for",
]

# --------------------------------------------------------------------------- #
# 一、数字格式：值存数值，格式管显示
# --------------------------------------------------------------------------- #
#: 语义名 → Excel 自定义格式串。用语义名而不是直接写格式串，是为了让「这一列
#: 该是什么格式」用一个词就能表达，不必每次拼 `#,##0.00`。
NUMBER_FORMATS: dict[str, str] = {
    "金额": "¥#,##0.00",
    "金额整": "¥#,##0",
    "千分位": "#,##0",
    "两位小数": "0.00",
    "一位小数": "0.0",
    "整数": "0",
    "百分比": "0.0%",
    "百分比整": "0%",
    "日期": "yyyy-mm-dd",
    "月": "yyyy-mm",
    "日期时间": "yyyy-mm-dd hh:mm",
    "时间": "hh:mm",
    "文本": "@",
    "科学计数": "0.00E+00",
    "工时": "0.0",
    "里程": "0.0",
}

# --------------------------------------------------------------------------- #
# 二、列名 → 类型：看到「金额」就别当文本
# --------------------------------------------------------------------------- #
#: 列名关键词 → 语义类型（NUMBER_FORMATS 的键）。
#:
#: 顺序有意义：`_FORMAT_RULES` 从上往下匹配，先命中的赢。所以「数量占比」要先
#: 判百分比再判数量，否则会被当成整数。
COLUMN_KEYWORDS: dict[str, str] = {
    # 金额类：带货币符号、两位小数
    "金额": "金额",
    "单价": "金额",
    "总价": "金额",
    "合计": "金额",
    "小计": "金额",
    "费用": "金额",
    "成本": "金额",
    "收入": "金额",
    "支出": "金额",
    "利润": "金额",
    "毛利": "金额",
    "预算": "金额",
    "工资": "金额",
    "薪酬": "金额",
    "报销": "金额",
    "回款": "金额",
    "付款": "金额",
    "余额": "金额",
    # 比率类
    "占比": "百分比",
    "比例": "百分比",
    "百分比": "百分比",
    "增长率": "百分比",
    "完成率": "百分比",
    "达成率": "百分比",
    "转化率": "百分比",
    "毛利率": "百分比",
    "同比": "百分比",
    "环比": "百分比",
    # 计数类
    "数量": "千分位",
    "件数": "千分位",
    "人数": "千分位",
    "次数": "千分位",
    "台数": "千分位",
    "库存": "千分位",
    "销量": "千分位",
    "客数": "千分位",
    "行数": "千分位",
    # 时间类
    "日期": "日期",
    "时间": "日期时间",
    "月份": "月",
    "创建于": "日期时间",
    "更新于": "日期时间",
    "截止": "日期",
    "开始": "日期",
    "结束": "日期",
    # 编号类：必须当文本，否则 00123 会变成 123
    "编号": "文本",
    "工号": "文本",
    "学号": "文本",
    "订单号": "文本",
    "手机": "文本",
    "电话": "文本",
    "身份证": "文本",
    "批次": "文本",
    "单号": "文本",
}

#: 判定时按这个顺序过：先比率、再时间、再金额、最后计数。
#: 「完成率」同时含「完成」与「率」，靠顺序保证它落到百分比。
_FORMAT_RULES: tuple[tuple[str, str], ...] = (
    ("率", "百分比"),
    ("占比", "百分比"),
    ("比例", "百分比"),
    ("日期", "日期"),
    ("时间", "日期时间"),
    ("号", "文本"),
    ("ID", "文本"),
    ("id", "文本"),
    ("金额", "金额"),
    ("费用", "金额"),
    ("金额合计", "金额"),
    ("数量", "千分位"),
    ("人数", "千分位"),
)

# --------------------------------------------------------------------------- #
# 三、列宽：按「这一列装什么」给，不按字数猜
# --------------------------------------------------------------------------- #
#: 语义名 → 列宽（Excel 的「字符宽度」单位）。
#: 12 是常规、20 是名称、40 是备注——备注放不下会被截断，而截断的备注等于没有。
COLUMN_WIDTHS: dict[str, float] = {
    "序号": 6.0,
    "编号": 12.0,
    "日期": 12.0,
    "日期时间": 18.0,
    "时间": 8.0,
    "名称": 22.0,
    "标题": 26.0,
    "负责人": 10.0,
    "部门": 12.0,
    "状态": 10.0,
    "金额": 14.0,
    "百分比": 10.0,
    "数量": 10.0,
    "备注": 40.0,
    "描述": 40.0,
    "说明": 36.0,
    "链接": 30.0,
    "常规": 14.0,
}

#: 列名关键词 → 列宽语义。
_WIDTH_KEYWORDS: dict[str, str] = {
    "序号": "序号",
    "编号": "编号",
    "工号": "编号",
    "日期": "日期",
    "时间": "日期时间",
    "名称": "名称",
    "项目": "名称",
    "标题": "标题",
    "事项": "名称",
    "负责人": "负责人",
    "责任人": "负责人",
    "经办": "负责人",
    "部门": "部门",
    "状态": "状态",
    "进度": "状态",
    "金额": "金额",
    "费用": "金额",
    "单价": "金额",
    "合计": "金额",
    "率": "百分比",
    "占比": "百分比",
    "数量": "数量",
    "人数": "数量",
    "件数": "数量",
    "备注": "备注",
    "说明": "备注",
    "描述": "描述",
    "链接": "链接",
}

#: 表头底纹（浅灰）与默认字体。表头不填色，打印出来和正文混成一片。
HEADER_FILL = "EEF1F6"

#: 建议的规模上限：超过就别再单表硬塞，拆 sheet 或拆文件。
MAX_ROWS_HINT = 200_000
MAX_COLS_HINT = 30

# --------------------------------------------------------------------------- #
# 四、表类型：一套不打架的参数
# --------------------------------------------------------------------------- #
#: 表类型名 → 冻结/筛选/合计/表头/列宽策略。`total` 是合计行放哪几列（语义名）。
SHEET_TYPES: dict[str, dict[str, object]] = {
    # 台账：一行一条记录，冻结首行 + 筛选，不自动加合计（台账的合计意义不大）
    "台账": {"freeze": True, "filter": True, "total": (), "header": True},
    # 明细：同台账，但不筛选（明细通常按整段读，筛了反而看不到全貌）
    "明细": {"freeze": True, "filter": False, "total": (), "header": True},
    # 汇总：要合计，列少，字号可以大一点
    "汇总": {"freeze": True, "filter": False, "total": ("金额", "数量"), "header": True},
    # 对比：两列并排，不合计
    "对比": {"freeze": True, "filter": False, "total": (), "header": True},
    # 排班 / 考勤：按日期铺开，冻结首列（人名）比冻结首行更重要
    "排班": {"freeze": "first_col", "filter": False, "total": (), "header": True},
    "考勤": {"freeze": "first_col", "filter": True, "total": ("数量",), "header": True},
    # 课表：左边是时段/节次、上边是星期，两个方向都要冻住（否则往右翻就不知道
    # 是哪一列、往下翻就不知道是第几节）。这张表没有可筛的东西。
    "课表": {"freeze": "corner", "filter": False, "total": (), "header": True},
    # 预算 / 报销：要合计，且金额列必须带货币符号
    "预算": {"freeze": True, "filter": True, "total": ("金额",), "header": True},
    "报销": {"freeze": True, "filter": True, "total": ("金额",), "header": True},
    # 库存：要合计，数量列要千分位
    "库存": {"freeze": True, "filter": True, "total": ("数量", "金额"), "header": True},
    # 项目计划：甘特式，日期列多，冻结首列
    "项目计划": {"freeze": "first_col", "filter": True, "total": (), "header": True},
    # 通讯录 / 名单：文本为主，不合计
    "名单": {"freeze": True, "filter": True, "total": (), "header": True},
}

#: 表类型的口语写法。
_TYPE_ALIASES: dict[str, str] = {
    "流水账": "台账",
    "记录": "台账",
    "登记": "台账",
    "清单": "明细",
    "列表": "明细",
    "统计": "汇总",
    "汇总表": "汇总",
    "对照": "对比",
    "对比表": "对比",
    "值班": "排班",
    "出勤": "考勤",
    "费用": "报销",
    "开票": "报销",
    "存货": "库存",
    "计划": "项目计划",
    "通讯录": "名单",
    "人员": "名单",
    # 口语里很少说「台账」「明细」这种行话，多是说「那个表」
    "流水": "台账",
    "流水记录": "台账",
    "记账": "台账",
    "台账表": "台账",
    "明细表": "明细",
    "统计表": "汇总",
    "合计表": "汇总",
    "预算表": "预算",
    "报销单": "报销",
    "费用报销": "报销",
    "库存表": "库存",
    "进销存": "库存",
    "排班表": "排班",
    "考勤表": "考勤",
    "值班表": "排班",
    # 课表 / 值班表这类「左时段 + 上日期」的二维表，别落回台账（台账会加筛选，
    # 一筛就把整张课表拆成一条条记录，看着像坏了）
    "课表": "课表",
    "课程表": "课表",
    "上课表": "课表",
    "作息表": "课表",
    "时间表": "课表",
    "人员名单": "名单",
    "联系人": "名单",
}


def resolve_sheet_type(name: str | None) -> dict[str, object]:
    """表类型名 → 参数；认不出按「台账」处理（最通用的一种）。"""
    key = str(name or "台账").strip()
    key = _TYPE_ALIASES.get(key, key)
    return dict(SHEET_TYPES.get(key, SHEET_TYPES["台账"]))


# --------------------------------------------------------------------------- #
# 五、按列名推断
# --------------------------------------------------------------------------- #
def _column_letter(index: int) -> str:
    """0 → A、25 → Z、26 → AA。只用于把列号换成 Excel 的列名。"""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def format_for(header: str) -> str | None:
    """列名 → 数字格式串。认不出返回 None（不设格式，别乱猜）。"""
    text = str(header or "").strip()
    if not text:
        return None
    for keyword, kind in _FORMAT_RULES:
        if keyword in text:
            return NUMBER_FORMATS.get(kind)
    for keyword, kind in COLUMN_KEYWORDS.items():
        if keyword in text:
            return NUMBER_FORMATS.get(kind)
    return None


def guess_formats(headers: list[object] | tuple[object, ...]) -> dict[str, str]:
    """表头 → `{"C": "¥#,##0.00"}`（键是列字母）。给 `write_table` 直接用。

    只给认得出的列：宁可这列保持常规格式，也不要给「状态」列套个百分比。
    """
    formats: dict[str, str] = {}
    for index, header in enumerate(headers):
        fmt = format_for(str(header or ""))
        if fmt:
            formats[_column_letter(index)] = fmt
    return formats


def width_for(header: str) -> float:
    """列名 → 列宽。备注/描述给宽，编号/日期给窄。"""
    text = str(header or "").strip()
    for keyword, kind in _WIDTH_KEYWORDS.items():
        if keyword in text:
            return COLUMN_WIDTHS.get(kind, COLUMN_WIDTHS["常规"])
    # 认不出就看长度：中文标题一般 4-8 个字，给 14 够用
    return COLUMN_WIDTHS["常规"] if len(text) <= 8 else COLUMN_WIDTHS["名称"]


def guess_widths(headers: list[object] | tuple[object, ...]) -> dict[str, float]:
    """表头 → `{"A": 6.0, "B": 22.0}`。"""
    return {
        _column_letter(index): width_for(str(header or "")) for index, header in enumerate(headers)
    }


#: 纯数字串（含前导零）看起来像编号：`00123` 一进 Excel 就变 123。
_NUMERIC_ID = re.compile(r"^0\d+$")


def looks_like_id(value: object) -> bool:
    """判断一个值是不是「带前导零的编号」——这种值必须按文本写。"""
    return bool(_NUMERIC_ID.match(str(value or "").strip()))


# --------------------------------------------------------------------------- #
# 六、版式：一张表长什么样（字体 / 字号 / 框线 / 行高 / 打印）
# --------------------------------------------------------------------------- #
# 为什么版式也要进词表：Word 那边（doc_lexicon + doc_render）已经这么干了，
# 同一个「表头 10.5pt 浅灰底」以前在 xlsx_utils 里写一遍、在产品文档里再写一遍，
# 改一处忘一处，预览和下载就是两种观感。表格尤其明显——它是**拿来比对的**，
# 字号差半个号、框线少一圈，看着就不像同一个系统出的东西。
#
# 这里只放「词」，样式怎么落到单元格由 `sheet_render.py` 决定（跟 doc_render 一个分工）。

#: 字体角色 → 字体名。Excel 的 Font 只有一个 name，中英文共用同一个，
#: 所以不像 Word 那样分 eastAsia / ascii 两栏。
SHEET_FONTS: dict[str, str] = {
    "标题": "黑体",  # 表头上的大标题：黑体比宋体「起眼」，一眼分出层级
    "表头": "宋体",
    "正文": "宋体",
}

#: 字号（pt）。表格比正文小一档是通行写法：Word 正文小四 12，表内五号 10.5，
#: 表格在同一版心内本来就该更密——字号与正文齐平，行数一多就翻不完。
SHEET_SIZES: dict[str, float] = {
    "标题": 14.0,
    "表头": 10.5,
    "正文": 10.5,
    "密排": 9.0,
}

#: 框线：语义名 → (线型, 颜色)。`""` 表示不画。
#: 只画表头下压线（三线表）那档没单列：Excel 里没有横向表格线，读者滚动时
#: 会串行，所以正式表格一律给全框线细线。
BORDERS: dict[str, tuple[str, str]] = {
    "细": ("thin", "B9C0CC"),
    "中": ("medium", "8C96A5"),
    "无": ("", ""),
}

#: 行高（pt）。None 交给 Excel 自适应——但自适应对自动换行的长备注是「压成一行」，
#: 所以默认给个明确值，宁可略松。
ROW_HEIGHTS: dict[str, float] = {
    "标题": 30.0,
    "表头": 24.0,
    "数据": 20.0,
    "网格": 32.0,
    "密排": 16.0,
}

#: 表头文字颜色（比纯黑浅一档，屏幕上不刺眼、打印仍然是黑的）。
HEADER_COLOR = "1F2937"

# --------------------------------------------------------------------------- #
# 七、版式预设：三档，跟 Word 的 report / gongwen / compact 一一对应
# --------------------------------------------------------------------------- #
#: 预设名 → 版式参数。值写语义名，不写数字：`"表头"` 指的是 SHEET_SIZES 里那一档，
#: 想整体调大就改 SHEET_SIZES，不用在这里逐个替换。
#:
#: - `default`：通用数据表（台账 / 明细 / 汇总）。表头浅灰加粗居中，数据区分行靠
#:   框线不靠斑马纹（斑马纹一打印就是一片灰），文本左对齐、数字右对齐——数字不右
#:   对齐就没法按位数比大小，这是表格最基本的一条。
#: - `grid`：二维网格（课表 / 排班 / 值班表）。行和列都是「标签 + 格子」，
#:   内容居中、自动换行、行高给足；左右两边都冻住，否则往右翻不知道是哪一天。
#: - `compact`：密排（几百行的核对清单、日志类）。字小、行矮、不筛选。
SHEET_PRESETS: dict[str, dict[str, object]] = {
    "default": {
        "font": "正文",
        "title_size": "标题",
        "header_size": "表头",
        "body_size": "正文",
        "border": "细",
        "header_fill": HEADER_FILL,
        "header_color": HEADER_COLOR,
        "header_align": "center",
        "body_align": "left",
        "number_align": "right",
        "wrap": False,
        "freeze": "header",
        "filter": True,
        "title_height": "标题",
        "header_height": "表头",
        "row_height": "数据",
        "landscape": False,
        "fit_width": True,
        "max_width": 42.0,
    },
    "grid": {
        "font": "正文",
        "title_size": "标题",
        "header_size": "表头",
        "body_size": "正文",
        "border": "细",
        "header_fill": HEADER_FILL,
        "header_color": HEADER_COLOR,
        "header_align": "center",
        "body_align": "center",
        "number_align": "center",
        "wrap": True,
        "freeze": "corner",
        "filter": False,
        "title_height": "标题",
        "header_height": "表头",
        "row_height": "网格",
        "landscape": True,
        "fit_width": True,
        # 网格表的格子会自动换行，列宽给太宽整张表就横着散开了：18 大约
        # 「九个汉字」，课程名两行放得下，五个工作日并排还在一个屏幕上。
        "max_width": 18.0,
    },
    "compact": {
        "font": "正文",
        "title_size": "表头",
        "header_size": "正文",
        "body_size": "密排",
        "border": "细",
        "header_fill": HEADER_FILL,
        "header_color": HEADER_COLOR,
        "header_align": "center",
        "body_align": "left",
        "number_align": "right",
        "wrap": False,
        "freeze": "header",
        "filter": False,
        "title_height": "表头",
        "header_height": "数据",
        "row_height": "密排",
        "landscape": False,
        "fit_width": True,
        "max_width": 42.0,
    },
}

#: 版式的口语写法 → 预设名。用户说的是「课表」「值班表」，不是「grid」。
SHEET_PRESET_ALIASES: dict[str, str] = {
    "默认": "default",
    "通用": "default",
    "报表": "default",
    "台账": "default",
    "课表": "grid",
    "课程表": "grid",
    "排班": "grid",
    "排班表": "grid",
    "值班表": "grid",
    "值班": "grid",
    "网格": "grid",
    "紧凑": "compact",
    "密排": "compact",
}


def resolve_preset(name: str | None) -> dict[str, object]:
    """版式名 → 参数；认不出按 `default` 处理（最通用的那一档）。

    别名先过一遍：用户和模型说的都是「课表」「排班表」这种业务词。
    """
    key = str(name or "default").strip()
    key = SHEET_PRESET_ALIASES.get(key, key)
    return dict(SHEET_PRESETS.get(key, SHEET_PRESETS["default"]))
