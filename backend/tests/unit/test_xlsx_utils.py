"""xlsx_utils 单测：写→读→追加→合计→分组汇总，断言落在 openpyxl 的真实对象上。

重点不是「函数跑通」，而是格式真的写进去了（表头加粗/冻结/筛选/数字格式），
以及清洗类函数不会把整行空白的记录算成一条数据。
"""

from __future__ import annotations

from pathlib import Path

from app.services import xlsx_utils
from openpyxl import load_workbook


def test_write_table_formats_header_and_freezes(tmp_path: Path) -> None:
    out = tmp_path / "销售.xlsx"
    result = xlsx_utils.write_table(
        out,
        [["华东", 1200.5], ["华南", 800]],
        headers=["区域", "金额"],
        number_formats={"B": "¥#,##0.00"},
    )
    assert result["rows"] == 2 and result["cols"] == 2

    workbook = load_workbook(str(out))
    sheet = workbook.active
    assert sheet["A1"].value == "区域"
    assert sheet["A1"].font.bold is True
    assert sheet.freeze_panes == "A2"
    assert sheet.auto_filter.ref == "A1:B3"
    assert sheet["B2"].number_format == "¥#,##0.00"
    assert sheet.column_dimensions["A"].width >= 8


def test_read_report_and_records_skip_blank_rows(tmp_path: Path) -> None:
    out = tmp_path / "表.xlsx"
    xlsx_utils.write_table(out, [["A", 1], [None, None], ["B", 2]], headers=["名", "值"])
    report = xlsx_utils.read_report(out)
    sheet = report["sheets"][0]
    assert sheet["headers"][:2] == ["名", "值"]
    assert sheet["rows"] == 3

    records = xlsx_utils.sheet_records(out)
    assert records == [{"名": "A", "值": 1}, {"名": "B", "值": 2}]


def test_sheet_records_fill_and_dedupe_headers() -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["名", "", "名", "列4"])
    sheet.append(["甲", "x", "y", "z"])
    records = xlsx_utils.sheet_records(sheet)
    assert list(records[0].keys()) == ["名", "列2", "名_2", "列4"]
    assert records[0]["列2"] == "x"


def test_append_records_reports_ignored_columns(tmp_path: Path) -> None:
    out = tmp_path / "表.xlsx"
    xlsx_utils.write_table(out, [["A", 1]], headers=["名", "值"])
    result = xlsx_utils.append_records(out, [{"名": "B", "值": 2, "多出来": 9}])
    assert result == {"appended": 1, "ignored_columns": ["多出来"]}

    records = xlsx_utils.sheet_records(out)
    assert records[-1] == {"名": "B", "值": 2}


def test_add_total_row_writes_sum_formula(tmp_path: Path) -> None:
    out = tmp_path / "表.xlsx"
    xlsx_utils.write_table(out, [["A", 10], ["B", 20]], headers=["名", "值"])
    workbook = load_workbook(str(out))
    sheet = workbook.active
    row = xlsx_utils.add_total_row(sheet, ["B"])
    workbook.save(str(out))
    assert row == 4
    assert sheet[f"A{row}"].value == "合计"
    assert sheet[f"B{row}"].value == "=SUM(B2:B3)"


def test_group_sum_aggregates_and_sorts() -> None:
    records = [
        {"区域": "华东", "金额": 10},
        {"区域": "华南", "金额": 30},
        {"区域": "华东", "金额": 5},
        {"区域": "华南", "金额": "坏值"},
    ]
    grouped = xlsx_utils.group_sum(records, "区域", "金额")
    assert grouped[0]["区域"] == "华南"
    assert grouped[0]["金额"] == 30.0
    assert grouped[1] == {"区域": "华东", "笔数": 2, "金额": 15.0}


def test_csv_roundtrip_with_gbk(tmp_path: Path) -> None:
    rows = [{"姓名": "张三", "部门": "财务"}, {"姓名": "李四", "部门": "研发"}]
    out = xlsx_utils.write_csv(tmp_path / "名单.csv", rows, encoding="gb18030")
    assert xlsx_utils.read_csv_records(out) == [
        {"姓名": "张三", "部门": "财务"},
        {"姓名": "李四", "部门": "研发"},
    ]


def test_autofit_uses_cjk_width(tmp_path: Path) -> None:
    out = tmp_path / "宽.xlsx"
    xlsx_utils.write_table(out, [["很长的中文内容" * 3]], headers=["说明"])
    sheet = load_workbook(str(out)).active
    assert sheet.column_dimensions["A"].width >= 20
