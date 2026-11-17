"""sheet_render.py —— Excel 版式引擎：一张表 → 排好版的 .xlsx。

**为什么要有这一层。** Word / PDF 那边已经有 `doc_render` / `pdf_utils` 统一版式，
表格却一直是「模型自己拼 openpyxl 样式」：表头有没有底纹、数据区有没有框线、
数字右不右对齐、行高给多少，全看那一轮模型的心情。结果是同一个产品里，
Word 是排过版的，Excel 像随手另存的——`sheet_lexicon.py` 里已经写过这件事，
这里补上落地的那一半。

分工与 doc_render 一致：

    sheet_lexicon  —— 只管「词」：字号多大、线型哪档、行高多少、预设叫什么
    sheet_render   —— 只管「怎么落」：把词翻译成 openpyxl 的 Font / Border / Alignment

**两条入口。**

- `write_grid(...)`：二维网格。**每个格子由调用方指明位置**，不给它「按顺序流下去」
  的机会。课表、排班、值班表、评分表这类「行列都是标签」的表必须走这条——
  一旦按顺序流，中间空一格，后面整行就左移一位（线上真出过：周五的课跑到周一）。
- `render_table(...)`：带表头的记录表（台账 / 明细 / 汇总）。表头 + 数据行，
  数字格式与列宽按表头自动推断。

`xlsx_utils.write_table` 现在也走 `render_table`：样式只有一份实现，
换版式改 `sheet_lexicon.SHEET_PRESETS`，不用逐个函数追。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.page import PageMargins
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

try:  # 脚本工作目录里 *_utils.py 是平铺复制的，没有包结构，只能绝对导入
    from .sheet_lexicon import (
        BORDERS,
        NUMBER_FORMATS,
        ROW_HEIGHTS,
        SHEET_FONTS,
        SHEET_SIZES,
        guess_formats,
        guess_widths,
        looks_like_id,
        resolve_preset,
        resolve_sheet_type,
    )
except ImportError:  # pragma: no cover - 沙箱里平铺运行时走这条
    from sheet_lexicon import (  # type: ignore[no-redef]
        BORDERS,
        NUMBER_FORMATS,
        ROW_HEIGHTS,
        SHEET_FONTS,
        SHEET_SIZES,
        guess_formats,
        guess_widths,
        looks_like_id,
        resolve_preset,
        resolve_sheet_type,
    )

__all__ = [
    "SheetPreset",
    "preset_of",
    "render_table",
    "style_sheet",
    "write_grid",
]

#: 数字右对齐、文本左对齐。判断依据是「值本身是不是数」而不是「列名叫什么」：
#: 列名写成「备注」但填了 12 的，右对齐也不难看；反过来「金额」列里塞了
#: 「12 万元」这种文本，左对齐才对得上。
_NUMERIC = (int, float)

#: 列宽下限。6 是「序号」那种窄列，比这更窄就看不见内容了。
_MIN_WIDTH = 6.0
_MAX_WIDTH = 42.0

#: 编号按文本写的格式串（`00123` 不能变成 123）。
TEXT_FORMAT = NUMBER_FORMATS.get("文本", "@")


@dataclass(frozen=True)
class SheetPreset:
    """一套表格版式，数值都从 `sheet_lexicon` 取（这里不出现裸数字）。"""

    name: str
    font: str
    title_font: str
    title_size: float
    header_size: float
    body_size: float
    border: str
    header_fill: str
    header_color: str
    header_align: str
    body_align: str
    number_align: str
    wrap: bool
    freeze: str
    filter: bool
    title_height: float
    header_height: float
    row_height: float
    landscape: bool
    fit_width: bool
    max_width: float

    @property
    def box(self) -> Border | None:
        """数据区的框线。`BORDERS` 里没有这档线型就返回 None（不画）。"""
        style, color = BORDERS.get(self.border, ("", ""))
        if not style:
            return None
        side = Side(style=style, color=color)
        return Border(left=side, right=side, top=side, bottom=side)


def preset_of(name: str | None = "default") -> SheetPreset:
    """版式名（含「课表」「排班表」这类口语）→ 一套参数。"""
    raw = resolve_preset(name)
    return SheetPreset(
        name=str(name or "default"),
        font=SHEET_FONTS.get(str(raw["font"]), "宋体"),
        title_font=SHEET_FONTS["标题"],
        title_size=_size(raw["title_size"]),
        header_size=_size(raw["header_size"]),
        body_size=_size(raw["body_size"]),
        border=str(raw["border"]),
        header_fill=str(raw["header_fill"]),
        header_color=str(raw["header_color"]),
        header_align=str(raw["header_align"]),
        body_align=str(raw["body_align"]),
        number_align=str(raw["number_align"]),
        wrap=bool(raw["wrap"]),
        freeze=str(raw["freeze"]),
        filter=bool(raw["filter"]),
        title_height=_height(raw["title_height"]),
        header_height=_height(raw["header_height"]),
        row_height=_height(raw["row_height"]),
        landscape=bool(raw["landscape"]),
        fit_width=bool(raw["fit_width"]),
        max_width=float(raw.get("max_width") or _MAX_WIDTH),
    )


def _size(token: object) -> float:
    """语义名（"表头"）→ pt；已经是数字就原样返回。"""
    if isinstance(token, (int, float)):
        return float(token)
    return float(SHEET_SIZES.get(str(token), SHEET_SIZES["正文"]))


def _height(token: object) -> float:
    if isinstance(token, (int, float)):
        return float(token)
    return float(ROW_HEIGHTS.get(str(token), ROW_HEIGHTS["数据"]))


# --------------------------------------------------------------------------- #
# 落样式
# --------------------------------------------------------------------------- #
def _alignment(preset: SheetPreset, *, header: bool, value: Any) -> Alignment:
    if header:
        horizontal = preset.header_align
    elif isinstance(value, _NUMERIC):
        horizontal = preset.number_align
    else:
        horizontal = preset.body_align
    return Alignment(horizontal=horizontal, vertical="center", wrap_text=preset.wrap)


def style_sheet(
    worksheet: Worksheet,
    preset: SheetPreset,
    *,
    header_rows: Sequence[int] = (),
    first_row: int = 1,
    last_row: int | None = None,
    first_col: int = 1,
    last_col: int | None = None,
) -> None:
    """给整块区域上样式：框线、字体、对齐。

    `header_rows` 是表头的行号（1 起）：这些行加粗、浅灰底、居中。
    行高不在这里设——它按行号给，跟「哪一行是表头」是两件事，见 `_apply_heights`。

    **要在合并之前整块刷**：openpyxl 合并后只有左上角那一格能被样式命中，
    其余几个格子在 Excel 里仍按「无框线」渲染，合并出来的大格子会缺一两根边。
    """
    last_row = last_row or worksheet.max_row
    last_col = last_col or worksheet.max_column
    heads = set(header_rows)
    box = preset.box
    for row in worksheet.iter_rows(
        min_row=first_row, max_row=last_row, min_col=first_col, max_col=last_col
    ):
        for cell in row:
            is_head = cell.row in heads
            cell.font = Font(
                name=preset.font,
                size=preset.header_size if is_head else preset.body_size,
                bold=is_head,
                color=preset.header_color if is_head else "000000",
            )
            cell.alignment = _alignment(preset, header=is_head, value=cell.value)
            if box is not None:
                cell.border = box
            if is_head:
                cell.fill = PatternFill("solid", fgColor=preset.header_fill)


def _apply_heights(
    worksheet: Worksheet,
    preset: SheetPreset,
    *,
    title_row: int | None,
    header_rows: Sequence[int],
    first_data_row: int,
    last_row: int,
) -> None:
    """行高：标题一行最高，表头次之，数据行统一。

    数据行给死一个值而不是逐行自适应：自适应遇到自动换行的长备注会算成一个很矮
    的行，Excel 打开是「字压在一起」。宁可略松，也不要挤。
    """
    if title_row:
        worksheet.row_dimensions[title_row].height = preset.title_height
    for row in header_rows:
        worksheet.row_dimensions[row].height = preset.header_height
    for row in range(first_data_row, last_row + 1):
        if not worksheet.row_dimensions[row].height:
            worksheet.row_dimensions[row].height = preset.row_height


def _display_width(text: str) -> float:
    """一行文字的显示宽度（中文算 2 格）。"""
    return sum(2.0 if ord(char) > 127 else 1.0 for char in text)


def _apply_widths(
    worksheet: Worksheet,
    widths: dict[str, float] | None,
    last_col: int,
    *,
    max_width: float = _MAX_WIDTH,
) -> None:
    """列宽：给了就用给的，没给就按内容估（取最宽的那一行，多行按最长一行算）。"""
    measured: dict[str, float] = {}
    for index in range(1, last_col + 1):
        letter = get_column_letter(index)
        widest = 0.0
        for row in worksheet.iter_rows(min_col=index, max_col=index):
            for cell in row:
                if cell.value in (None, ""):
                    continue
                lines = str(cell.value).splitlines() or [str(cell.value)]
                widest = max(widest, max(_display_width(line) for line in lines))
        if widest:
            measured[letter] = widest + 2
    for index in range(1, last_col + 1):
        letter = get_column_letter(index)
        explicit = (widths or {}).get(letter)
        if explicit:
            # 调用方点名的宽度照办，不套上限：一份「整段文字放在一列里」的报告
            # 就要 90 宽，被截到 42 会把每段压成四行。
            worksheet.column_dimensions[letter].width = float(explicit)
            continue
        width = measured.get(letter, _MIN_WIDTH)
        worksheet.column_dimensions[letter].width = max(_MIN_WIDTH, min(width, max_width))


def _page_setup(
    worksheet: Worksheet, preset: SheetPreset, *, title_rows: tuple[int, int] | None
) -> None:
    """打印设置：A4、按宽度缩到一页、每页重复表头。

    不设这三条，一张 8 列的表打印出来右边两列落单页；十几页的长表只有第一页有
    表头——用户拿去开会时最常抱怨的就是这两件事。
    """
    worksheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=preset.fit_width)
    worksheet.page_setup.orientation = "landscape" if preset.landscape else "portrait"
    worksheet.page_setup.paperSize = worksheet.PAPERSIZE_A4
    if preset.fit_width:
        worksheet.page_setup.fitToWidth = 1
        worksheet.page_setup.fitToHeight = 0
    worksheet.page_margins = PageMargins(left=0.6, right=0.6, top=0.7, bottom=0.7)
    if title_rows:
        first, last = title_rows
        worksheet.print_title_rows = f"{first}:{last}"


def _freeze(
    worksheet: Worksheet,
    *,
    freeze: str,
    header_rows: int,
    title_row: int | None,
    freeze_cols: int,
) -> None:
    """冻结：`header` 冻表头行，`corner` 再冻左边几列，`first_col` 只冻左列。"""
    top = (title_row or 0) + header_rows
    if freeze == "corner":
        worksheet.freeze_panes = f"{get_column_letter(max(1, freeze_cols) + 1)}{top + 1}"
    elif freeze == "header":
        worksheet.freeze_panes = f"A{top + 1}"
    elif freeze == "first_col":
        worksheet.freeze_panes = f"B{top + 1}"


# --------------------------------------------------------------------------- #
# 入口一：二维网格
# --------------------------------------------------------------------------- #
def write_grid(
    path: str | Path,
    rows: Sequence[Sequence[Any]],
    *,
    sheet: str = "Sheet1",
    title: str = "",
    preset: str = "grid",
    header_rows: int = 1,
    merges: Sequence[str] = (),
    widths: dict[str, float] | None = None,
    freeze_cols: int = 1,
    number_formats: dict[str, str] | None = None,
    freeze: str | None = None,
    filter_: bool | None = None,
) -> dict[str, Any]:
    """按 (行, 列) 摆好的二维网格 → .xlsx。

    `rows` 必须**每行等长**：空格子写 `None`，但位置要占住。这不是形式主义——
    课表里周三没课，如果那一段直接省掉，后面周四、周五的课就整体左移一格，
    看起来是「内容填错了位置」，其实是列被吃掉了。所以这里宁可给整行补齐、
    再把短了的行长报回去，也不按顺序流下去。

    `merges` 用 Excel 记法（`["A2:A3", "B1:B2"]`）：时段列「上午」跨两行、
    表头「成绩」跨两列，都靠它。合并之后整块补框线，否则合并区只剩左上角有边。
    """
    style = preset_of(preset)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = sheet or "Sheet1"

    grid = [list(row) for row in rows]
    if not grid:
        raise ValueError("表格至少要有一行：给了 rows 却是空的")
    columns = max(len(row) for row in grid) or 1
    short = [index + 1 for index, row in enumerate(grid) if len(row) < columns]
    for row in grid:
        row.extend([None] * (columns - len(row)))

    title_row: int | None = None
    start = 1
    if title:
        worksheet.cell(row=1, column=1, value=title)
        title_row = 1
        start = 2

    for offset, row in enumerate(grid):
        for index, value in enumerate(row, start=1):
            cell = worksheet.cell(row=start + offset, column=index, value=value)
            # 带前导零的编号（00123）不点明就是文本，Excel 会当成 123。
            # 这不是内容错，是格式错——改回来的人得对着原始文件一比才知道差在哪。
            if isinstance(value, str) and looks_like_id(value):
                cell.number_format = TEXT_FORMAT

    last_row = start + len(grid) - 1
    heads = tuple(range(start, start + max(0, header_rows)))

    _paint_title(worksheet, style, title_row, columns)
    style_sheet(
        worksheet,
        style,
        header_rows=heads,
        first_row=start,
        last_row=last_row,
        first_col=1,
        last_col=columns,
    )
    for spec in merges:
        _merge_safely(worksheet, spec, style)

    for column, fmt in (number_formats or {}).items():
        for row in range(start + max(0, header_rows), last_row + 1):
            worksheet[f"{column}{row}"].number_format = str(fmt)

    _apply_widths(worksheet, widths, columns, max_width=style.max_width)
    _apply_heights(
        worksheet,
        style,
        title_row=title_row,
        header_rows=heads,
        first_data_row=start + max(0, header_rows),
        last_row=last_row,
    )
    _freeze(
        worksheet,
        freeze=freeze or style.freeze,
        header_rows=max(0, header_rows),
        title_row=title_row,
        freeze_cols=freeze_cols,
    )
    use_filter = style.filter if filter_ is None else filter_
    if use_filter and heads:
        worksheet.auto_filter.ref = f"A{heads[0]}:{get_column_letter(columns)}{last_row}"
    _page_setup(worksheet, style, title_rows=(heads[0], heads[-1]) if heads else None)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(str(out))
    result: dict[str, Any] = {
        "out": str(out),
        "rows": len(grid),
        "cols": columns,
        "preset": style.name,
    }
    if short:
        # 报回去而不是抛错：少一两格多半是模型漏了空位，补齐后能直接用
        result["short_rows"] = short
    return result


def _paint_title(
    worksheet: Worksheet, style: SheetPreset, title_row: int | None, columns: int
) -> None:
    """标题行：合并整行、黑体、居中、比正文大一档。"""
    if not title_row:
        return
    box = style.box
    cell = worksheet.cell(row=title_row, column=1)
    cell.font = Font(name=style.title_font, size=style.title_size, bold=True, color="1F2328")
    cell.alignment = Alignment(horizontal="center", vertical="center")
    for index in range(1, columns + 1):
        target = worksheet.cell(row=title_row, column=index)
        if box is not None:
            target.border = box
        if index > 1:
            target.fill = PatternFill("solid", fgColor=style.header_fill)
    if columns > 1:
        worksheet.merge_cells(
            start_row=title_row, start_column=1, end_row=title_row, end_column=columns
        )


def _merge_safely(worksheet: Worksheet, spec: str, style: SheetPreset) -> None:
    """按 `A2:A3` 合并，并把合并区里每个格子都补上框线。"""
    text = str(spec or "").strip().upper().replace("$", "")
    if not text or ":" not in text:
        return
    try:
        worksheet.merge_cells(text)
    except (ValueError, AttributeError, TypeError):  # 记法写错不该让整份产物报废
        return
    box = style.box
    if box is None:
        return
    for row in worksheet[text]:
        for cell in row:
            cell.border = box


# --------------------------------------------------------------------------- #
# 入口二：带表头的记录表
# --------------------------------------------------------------------------- #
def render_table(
    path: str | Path,
    rows: Sequence[Sequence[Any]],
    headers: Sequence[Any] | None = None,
    *,
    sheet: str = "Sheet1",
    title: str = "",
    preset: str = "default",
    sheet_type: str = "",
    number_formats: dict[str, str] | None = None,
    widths: dict[str, float] | None = None,
    total_row: bool = False,
) -> dict[str, Any]:
    """表头 + 数据行 → .xlsx（台账 / 明细 / 汇总这类记录表的通用入口）。

    `preset` 决定长相（default / grid / compact），`sheet_type` 决定行为
    （冻哪边、要不要筛选）。两者分开，是因为同一张「排班表」既可能想要网格版式，
    也可能只是普通记录表——长相和行为不是一回事。
    """
    style = preset_of(preset)
    kind = resolve_sheet_type(sheet_type) if sheet_type else {}
    grid: list[list[Any]] = []
    if headers:
        grid.append(list(headers))
    grid.extend([list(row) for row in rows])
    if not grid:
        raise ValueError("表格至少要有一行：表头和数据行都是空的")

    if headers and number_formats is None:
        number_formats = guess_formats(list(headers))
    if headers and widths is None:
        widths = guess_widths(list(headers))

    freeze = str(kind.get("freeze") or style.freeze)
    if not headers and freeze != "first_col":
        freeze = "none"
    use_filter = bool(kind["filter"]) if kind else style.filter

    result = write_grid(
        path,
        grid,
        sheet=sheet,
        title=title,
        preset=preset,
        header_rows=1 if headers else 0,
        widths=widths,
        freeze_cols=1 if freeze == "first_col" else 0,
        number_formats=number_formats,
        freeze=freeze,
        filter_=use_filter,
    )
    if total_row and headers and not title:
        _append_total(path, result, len(headers))
    return result


def _append_total(path: str | Path, result: dict[str, Any], columns: int) -> None:
    """在末尾补一行合计（SUM 公式，保留可复算性）。

    只给「整列都是数字」的列放 SUM：文本列求和会得到一串 0，看着像数据坏了。
    """
    from openpyxl import load_workbook

    workbook = load_workbook(str(path))
    worksheet = workbook.active
    last = worksheet.max_row
    target = last + 1
    worksheet.cell(row=target, column=1, value="合计")
    for index in range(2, columns + 1):
        letter = get_column_letter(index)
        values = [worksheet[f"{letter}{row}"].value for row in range(2, last + 1)]
        if values and all(isinstance(value, _NUMERIC) for value in values):
            worksheet[f"{letter}{target}"] = f"=SUM({letter}2:{letter}{last})"
    for cell in worksheet[target]:
        cell.font = Font(bold=True)
    workbook.save(str(path))
    result["total_row"] = target
