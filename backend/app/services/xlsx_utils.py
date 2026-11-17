"""xlsx_utils.py —— Agent 操作 .xlsx / .csv 的通用函数库。

设计要点（对应 docs/xlsx-knowledge-base-2026-10-25.md）：
- 打开既有表一律 `data_only=False`（拿公式原文），统计值另用 `data_only=True` 读一次；
- 表头/列宽/冻结/筛选/千分位这些「格式活」全部走这里，脚本不现场拼 Style 对象；
- 读写的中间结构统一是「list[dict]」，方便清洗、汇总、再去写回；
- 任何覆盖式修改都必须先 `backup`，产物另存新文件。

不引入 pandas：项目依赖里没有，装它只为几行汇总不划算；分组汇总用 dict 足够。
"""

from __future__ import annotations

import csv
import re
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

try:  # 脚本工作目录里 *_utils.py 是平铺复制的，没有包结构，只能绝对导入
    from .sheet_lexicon import (
        HEADER_FILL,
        NUMBER_FORMATS,
        resolve_sheet_type,
    )
    from .sheet_render import preset_of, render_table, style_sheet, write_grid
except ImportError:  # pragma: no cover - 沙箱里平铺运行时走这条
    from sheet_lexicon import (  # type: ignore[no-redef]
        HEADER_FILL,
        NUMBER_FORMATS,
        resolve_sheet_type,
    )
    from sheet_render import (  # type: ignore[no-redef]
        preset_of,
        render_table,
        style_sheet,
        write_grid,
    )

#: 表头底色、线型、字号的**数值**只在 `sheet_lexicon` 里有；这里重导 `HEADER_FILL`
#: 只是让老脚本 `from xlsx_utils import HEADER_FILL` 还能用。
__all__ = [
    "HEADER_FILL",
    "NUMBER_FORMATS",
    "add_autofilter",
    "add_total_row",
    "append_records",
    "autofit_columns",
    "backup",
    "freeze_header",
    "group_sum",
    "load_workbook_safe",
    "preset_of",
    "read_csv_records",
    "read_report",
    "records_to_rows",
    "render_table",
    "resolve_sheet_type",
    "sheet_records",
    "strip_proof_sheets",
    "style_header",
    "write_csv",
    "write_grid",
    "write_table",
]


# --------------------------------------------------------------------------- #
# 打开与体检
# --------------------------------------------------------------------------- #


def load_workbook_safe(path: str | Path, data_only: bool = False):
    """统一入口：路径不存在 / 不是 xlsx 时给一句能转述给用户的错误。"""
    target = Path(path)
    if not target.is_file():
        raise FileNotFoundError(f"找不到表格文件：{target}")
    try:
        return load_workbook(str(target), data_only=data_only)
    except Exception as exc:
        raise ValueError(f"打不开这个表格（可能不是 .xlsx 或已损坏）：{exc}") from exc


def read_report(path: str | Path, max_rows: int = 200_000) -> dict[str, Any]:
    """先报告再动手：每个 sheet 的行列数、表头、空值、公式、合并单元格。

    和 docx_utils.read_report 一样兜住两种写法：传路径，或直接传已打开的 workbook。
    """
    if hasattr(path, "worksheets"):  # openpyxl.Workbook
        workbook = path
        label = "<已打开的 workbook>"
    else:
        workbook = load_workbook_safe(path)
        label = Path(path).name
    sheets: list[dict[str, Any]] = []
    for worksheet in workbook.worksheets:
        rows = min(worksheet.max_row, max_rows)
        cols = worksheet.max_column
        headers = [
            str(worksheet.cell(row=1, column=index).value or "")
            for index in range(1, min(cols, 40) + 1)
        ]
        blanks = 0
        formulas = 0
        scanned = 0
        for row in worksheet.iter_rows(min_row=2, max_row=rows, max_col=cols):
            for cell in row:
                scanned += 1
                if cell.value in (None, ""):
                    blanks += 1
                elif isinstance(cell.value, str) and cell.value.startswith("="):
                    formulas += 1
        sheets.append(
            {
                "name": worksheet.title,
                "rows": max(worksheet.max_row - 1, 0),
                "cols": cols,
                "headers": headers,
                "blank_ratio": round(blanks / scanned, 3) if scanned else 0.0,
                "formulas": formulas,
                "merged": [str(item) for item in worksheet.merged_cells.ranges][:20],
            }
        )
    return {"file": label, "sheets": sheets, "active": workbook.active.title}


# --------------------------------------------------------------------------- #
# 读成记录
# --------------------------------------------------------------------------- #


def sheet_records(
    worksheet: Worksheet | str | Path,
    sheet: str | None = None,
    header_row: int = 1,
    fill_blank_header: bool = True,
) -> list[dict[str, Any]]:
    """把一张表读成 list[dict]；空表头补成「列N」，重复表头加后缀避免互相覆盖。"""
    if isinstance(worksheet, (str, Path)):
        workbook = load_workbook_safe(worksheet, data_only=True)
        target = workbook[sheet] if sheet else workbook.active
    else:
        target = worksheet

    headers: list[str] = []
    for index in range(1, target.max_column + 1):
        raw = target.cell(row=header_row, column=index).value
        name = str(raw).strip() if raw not in (None, "") else ""
        if not name:
            name = f"列{index}" if fill_blank_header else ""
        if name in headers:
            suffix = 2
            while f"{name}_{suffix}" in headers:
                suffix += 1
            name = f"{name}_{suffix}"
        headers.append(name)

    records: list[dict[str, Any]] = []
    for row in target.iter_rows(min_row=header_row + 1, max_col=len(headers)):
        values = [cell.value for cell in row]
        if all(value in (None, "") for value in values):
            continue  # 整行空白直接跳过，汇总时不该被算成一条
        records.append(dict(zip(headers, values, strict=False)))
    return records


def read_csv_records(path: str | Path, encoding: str | None = None) -> list[dict[str, Any]]:
    """读 CSV：默认先试 utf-8-sig，再退 gbk（Windows 上导出的表常是 GBK）。"""
    target = Path(path)
    candidates = [encoding] if encoding else ["utf-8-sig", "gb18030"]
    last_error: Exception | None = None
    for codec in candidates:
        try:
            with target.open("r", encoding=codec, newline="") as handle:
                return list(csv.DictReader(handle))
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"CSV 编码识别失败：{last_error}")


# --------------------------------------------------------------------------- #
# 写
# --------------------------------------------------------------------------- #


def records_to_rows(records: Sequence[dict[str, Any]], headers: Sequence[str] | None = None):
    """list[dict] → (表头, 数据行)；表头缺省取并集，保持首次出现顺序。"""
    if headers is None:
        seen: list[str] = []
        for record in records:
            for key in record:
                if key not in seen:
                    seen.append(key)
        headers = seen
    rows = [[record.get(header) for header in headers] for record in records]
    return list(headers), rows


def write_table(
    path: str | Path,
    rows: Sequence[Sequence[Any]],
    headers: Sequence[Any] | None = None,
    sheet: str = "Sheet1",
    number_formats: dict[str, str] | None = None,
    widths: dict[str, float] | None = None,
    sheet_type: str = "",
) -> dict[str, Any]:
    """新建一个工作簿写一张表（表头加粗、冻结首行、可选列格式）。

    `number_formats` / `widths` 不传时**按表头自动推断**：看到「金额」给货币格式，
    看到「占比」给百分比，看到「备注」给 40 宽。表格里最常见的错不是内容错，
    是格式错——金额存成文本求和为 0、占比存 12.5 再加 `%` 变成 1250%。
    推断只在认得出时生效，认不出就不设（宁可常规格式，也别乱套）。

    `sheet_type` 选表类型（台账 / 汇总 / 明细 / 对比 / 排班 / 库存…）：决定了要不要
    冻结首列、要不要筛选。传了就在自动推断之外再套一层，传空只按首行冻结。

    **样式不在这里拼**：走 `sheet_render.render_table`，跟产品文档、跟
    `write_grid` 用同一份版式（`sheet_lexicon.SHEET_PRESETS`）。以前这个函数自己
    设字体边框，另一处又设一套，同一份产品里表格长得不一样。
    """
    result = render_table(
        path,
        rows,
        headers,
        sheet=sheet,
        number_formats=number_formats,
        widths=widths,
        sheet_type=sheet_type,
    )
    return {
        "out": result["out"],
        "rows": len(rows),
        "cols": result["cols"],
    }


def append_records(
    path: str | Path,
    records: Sequence[dict[str, Any]],
    sheet: str | None = None,
) -> dict[str, Any]:
    """向既有表追加记录（按表头名对齐，缺列留空；不认识的列直接忽略并报告）。"""
    workbook = load_workbook_safe(path)
    worksheet = workbook[sheet] if sheet else workbook.active
    headers = [
        str(worksheet.cell(row=1, column=index).value or "").strip()
        for index in range(1, worksheet.max_column + 1)
    ]
    appended = 0
    ignored: set[str] = set()
    for record in records:
        values: list[Any] = []
        for header in headers:
            values.append(record.get(header))
        for key in record:
            if key not in headers:
                ignored.add(str(key))
        worksheet.append(values)
        appended += 1
    workbook.save(str(path))
    return {"appended": appended, "ignored_columns": sorted(ignored)}


def write_csv(
    path: str | Path, records: Sequence[dict[str, Any]], encoding: str = "utf-8-sig"
) -> str:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    headers, rows = records_to_rows(records)
    with out.open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)
    return str(out)


# --------------------------------------------------------------------------- #
# 格式化
# --------------------------------------------------------------------------- #


def style_header(worksheet: Worksheet, row: int = 1, fill: str = HEADER_FILL) -> None:
    """把某一行刷成表头（加粗 + 浅灰底 + 居中 + 框线）。

    样式本身来自 `sheet_render.style_sheet`，这里只是「指定哪一行」的便捷写法——
    老脚本 `style_header(ws)` 还能用，不用为了换个版式改一堆脚本。
    """
    preset = preset_of("default")
    if fill != HEADER_FILL:
        # 单独指定底色（少数表要按公司色做表头）：只改这一项，其余仍走版式
        preset = replace(preset, header_fill=fill)
    style_sheet(
        worksheet,
        preset,
        header_rows=(row,),
        first_row=row,
        last_row=row,
        first_col=1,
        last_col=worksheet.max_column,
    )


def autofit_columns(worksheet: Worksheet, min_width: float = 8, max_width: float = 40) -> None:
    """按内容估宽：中文算 2 个字符宽，避免「序号」列被撑成 20 格。"""
    widths: dict[int, float] = {}
    for row in worksheet.iter_rows():
        for cell in row:
            if cell.value is None:
                continue
            if hasattr(cell, "column"):
                column = cell.column
            else:  # pragma: no cover - 合并单元格代理
                continue
            text = str(cell.value)
            width = sum(2 if ord(char) > 127 else 1 for char in text) + 2
            widths[column] = max(widths.get(column, 0), width)
    for column, width in widths.items():
        worksheet.column_dimensions[get_column_letter(column)].width = max(
            min_width, min(float(width), max_width)
        )


def freeze_header(worksheet: Worksheet, row: int = 2) -> None:
    worksheet.freeze_panes = f"A{row}"


def add_autofilter(worksheet: Worksheet, columns: int, last_row: int) -> None:
    if columns <= 0 or last_row < 1:
        return
    worksheet.auto_filter.ref = f"A1:{get_column_letter(columns)}{last_row}"


def apply_number_format(worksheet: Worksheet, column: str, fmt: str, min_row: int = 2) -> None:
    """整列设数字格式：金额 '¥#,##0.00'、百分比 '0.0%'、日期 'yyyy-mm-dd'。"""
    for row in worksheet.iter_rows(min_row=min_row):
        for cell in row:
            if cell.column_letter == column.upper():
                cell.number_format = fmt


def add_total_row(
    worksheet: Worksheet,
    columns: Sequence[str],
    label: str = "合计",
    label_column: str = "A",
    first_row: int = 2,
) -> int:
    """在最后一行加合计（SUM 公式，保留可复算性）。返回写入的行号。"""
    last_row = worksheet.max_row
    target = last_row + 1
    worksheet[f"{label_column}{target}"] = label
    for column in columns:
        worksheet[f"{column}{target}"] = f"=SUM({column}{first_row}:{column}{last_row})"
    for cell in worksheet[target]:
        cell.font = Font(bold=True)
    return target


def group_sum(
    records: Sequence[dict[str, Any]],
    group_by: str | Sequence[str],
    value_field: str,
) -> list[dict[str, Any]]:
    """按一列或多列分组求和，返回按合计倒序的记录（含「笔数」）。"""
    keys = [group_by] if isinstance(group_by, str) else list(group_by)
    buckets: dict[tuple[Any, ...], dict[str, Any]] = {}
    for record in records:
        key = tuple(record.get(item) for item in keys)
        bucket = buckets.setdefault(
            key, {**{item: record.get(item) for item in keys}, "笔数": 0, value_field: 0.0}
        )
        raw = record.get(value_field)
        number = float(raw) if isinstance(raw, (int, float)) else 0.0
        bucket[value_field] += number
        bucket["笔数"] += 1
    return sorted(buckets.values(), key=lambda item: item[value_field], reverse=True)


# --------------------------------------------------------------------------- #
# 交付前清理：把「识别原文」这类对照附录摘掉
# --------------------------------------------------------------------------- #
#: 「识别原文 / OCR 原文 / 图片识别结果」这类附录的标题。
#:
#: 它们本来是给写稿人自己核对用的：OCR 出来的那串流水文字行列是错位的，
#: 摆进产物里读者只会盯着它怀疑数据——用户 2026-11-10 明确要求删掉。
#: 「核对说明」不在此列：那是**结论**（哪一格不确定、按什么规则复原的），
#: 读者需要，保留。
_PROOF_TITLE = re.compile(
    r"识别原文|图片识别|OCR\s*原文|原文对照|识别文字|识别结果原文|原始识别结果",
    re.IGNORECASE,
)

#: 附录里那一整段辨认不出结构的文字（往往是一格管一大段），用来判断「这一段是内容」。
#: 它不是标题：内容行不会是一个人能拿来当小节名的短词。
_SECTION_LIKE = 24


def strip_proof_sheets(path: str | Path) -> list[str]:
    """删掉「识别原文」这类对照附录，返回删掉的东西（给日志/说明用）。

    两种形态都处理，因为模型两种都写过：

    - 单开一张 sheet（最常见）——整张删；
    - 塞在同一张表末尾的一节——从标题行删到该节结束。

    只认标题，不猜内容：正文里顺带提到「识别」二字的表格不动。删完一张不剩时
    不删（工作簿至少要有一张表），交给调用方判断。
    """
    target = Path(path)
    if not target.is_file():
        return []
    try:
        workbook = load_workbook(str(target))
    except Exception:  # 打不开就原样返回：这不是清理该负责的事
        return []
    if _has_graphics(workbook):
        # openpyxl 存回去会丢掉图表、图片、条件格式这类它不建模的东西。
        # 为了删一节附录赔掉一张图表不划算——宁可不清理，让提示词去拦。
        return []

    removed: list[str] = []
    for worksheet in list(workbook.worksheets):
        if _PROOF_TITLE.search(worksheet.title or ""):
            if len(workbook.worksheets) > 1:
                workbook.remove(worksheet)
                removed.append(worksheet.title)
            continue
        last = _last_proof_row(worksheet)
        if last is not None:
            start, stop = last
            worksheet.delete_rows(start, stop - start + 1)
            removed.append(f"{worksheet.title}!{start}:{stop}")

    if removed:
        workbook.save(str(target))
    return removed


def _has_graphics(workbook: Any) -> bool:
    """表里有没有 openpyxl 存不住的图形（图表 / 图片）。有就不动这个文件。"""
    for worksheet in workbook.worksheets:
        if getattr(worksheet, "_charts", None) or getattr(worksheet, "_images", None):
            return True
    return False


def _last_proof_row(worksheet: Worksheet) -> tuple[int, int] | None:
    """在同张表里找「识别原文」那一节，返回 (起, 止) 行号；没有就 None。"""
    for row in range(1, worksheet.max_row + 1):
        cell = worksheet.cell(row=row, column=1)
        if not isinstance(cell.value, str) or not _PROOF_TITLE.search(cell.value):
            continue
        # 标题行本身可能带「（行列错位，仅作对照）」这种括注，不影响判定
        stop = worksheet.max_row
        for index in range(row + 2, worksheet.max_row + 1):
            values = [item.value for item in worksheet[index] if item.value not in (None, "")]
            # 下一节的标题：只有一个短词，且不在第一列以外——附录内容是长字符串，
            # 撞上这条的概率很低，撞上也不会误删（宁可少删一点）
            if len(values) == 1 and isinstance(values[0], str) and len(values[0]) <= _SECTION_LIKE:
                stop = index - 1
                break
        return row, stop
    return None


def backup(src: str | Path, out_dir: str | Path) -> str:
    source = Path(src)
    target_dir = Path(out_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{source.stem}.bak{source.suffix}"
    shutil.copy2(source, target)
    return str(target)


def iter_sheets(path: str | Path) -> Iterable[str]:
    return load_workbook_safe(path).sheetnames
