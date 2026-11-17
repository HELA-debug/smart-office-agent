"""表格辅助（xlsx）：解析与汇总的纯函数实现，B3 接入上传与工具注册。

当前不单独注册工具（表格加工由 code.run_python 调 xlsx_utils 完成），仅保留可复用的实现。
"""

from __future__ import annotations

import io
from typing import Any


def summarize_workbook(data: bytes, max_rows: int = 100) -> dict[str, Any]:
    """读取第一个工作表的前若干行，返回列名与行数据（供 B3 的工具使用）。"""
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    rows: list[list[Any]] = []
    for index, row in enumerate(sheet.iter_rows(values_only=True)):
        if index >= max_rows:
            break
        rows.append([value for value in row])
    header = [str(value) if value is not None else "" for value in (rows[0] if rows else [])]
    return {
        "sheet": sheet.title,
        "columns": header,
        "rows": rows[1:],
        "row_count": max(0, len(rows) - 1),
        "truncated": sheet.max_row > len(rows),
    }
