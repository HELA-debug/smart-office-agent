"""sheet_render 单测：网格表按 (行, 列) 落格、版式落到单元格、附录被摘干净。

重点不是「函数跑通」，而是三件线上真出过的事：
1. 空格子省掉会让后面整行左移（周五的课填到周一）；
2. 表头/正文的字体框线以前各写一套，同一份产物两种观感；
3. 「识别原文」这种对照附录被摆进交付件，读者盯着错位的文字怀疑整份数据。
"""

from __future__ import annotations

from pathlib import Path

from app.services import sheet_lexicon, sheet_render, xlsx_utils
from openpyxl import Workbook, load_workbook


def _grid() -> list[list[object]]:
    return [
        ["节次", "时间", "周一", "周三", "周五"],
        ["1–2", "8:00–8:45", "语文\n张老师 301", None, None],
        ["3–4", "10:10–10:55", None, "物理\n王老师 105", None],
    ]


def test_write_grid_keeps_every_cell_in_its_own_column(tmp_path: Path) -> None:
    """空格子必须占位：周三有课、周五没课，不能被挤到前一列。"""
    out = tmp_path / "课表.xlsx"
    result = sheet_render.write_grid(out, _grid(), sheet="课表", preset="课表")
    assert result["rows"] == 3 and result["cols"] == 5
    assert "short_rows" not in result

    sheet = load_workbook(str(out)).active
    assert sheet["A1"].value == "节次"
    assert sheet["C2"].value == "语文\n张老师 301"
    assert sheet["D2"].value is None  # 周三 1-2 节没课：这一格是空的，但不能被吃掉
    assert sheet["E2"].value is None
    assert sheet["D3"].value == "物理\n王老师 105"
    assert sheet["C3"].value is None


def test_write_grid_applies_grid_preset_style(tmp_path: Path) -> None:
    """版式来自词表：居中、自动换行、全框线、冻结首行首列。"""
    out = tmp_path / "课表.xlsx"
    sheet_render.write_grid(out, _grid(), sheet="课表", preset="课表", freeze_cols=2)
    sheet = load_workbook(str(out)).active
    preset = sheet_render.preset_of("课表")

    assert sheet.freeze_panes == "C2"
    assert sheet.auto_filter.ref is None  # 网格表不加筛选：一筛就散了
    cell = sheet["C2"]
    assert cell.alignment.horizontal == preset.body_align == "center"
    assert cell.alignment.wrap_text is True
    assert cell.border.left.style == "thin"
    assert cell.font.name == sheet_lexicon.SHEET_FONTS["正文"]
    assert cell.font.sz == sheet_lexicon.SHEET_SIZES["正文"]
    assert sheet["A1"].font.bold is True
    assert sheet["A1"].fill.fgColor.rgb.endswith(sheet_lexicon.HEADER_FILL)
    assert sheet.row_dimensions[1].height == sheet_lexicon.ROW_HEIGHTS["表头"]


def test_write_grid_merges_and_borders_the_whole_block(tmp_path: Path) -> None:
    """合并区里每一格都要有框线：openpyxl 合并后只有左上角吃样式，边上会缺根线。

    合并格内部的横线（A3 的上边）本来就该没有——那是两格之间的分隔线。
    """
    out = tmp_path / "课表.xlsx"
    rows = [
        ["时段", "节次", "周一"],
        ["上午", "1–2", "语文"],
        [None, "3–4", "数学"],
    ]
    sheet_render.write_grid(out, rows, sheet="课表", preset="课表", merges=["A2:A3"])
    sheet = load_workbook(str(out)).active
    assert "A2:A3" in {str(item) for item in sheet.merged_cells.ranges}
    assert sheet["A2"].border.bottom.style == "thin"
    # 合并块的下边框还在（少了它，Excel 里这一格下面是敞口的）
    assert sheet["A3"].border.bottom.style == "thin"
    assert sheet["A3"].border.left.style == "thin"
    assert sheet["A3"].border.top.style is None


def test_write_grid_reports_ragged_rows_instead_of_raising(tmp_path: Path) -> None:
    """少一两格多半是漏了空位：补齐后照样出文件，但把行号报回去。"""
    out = tmp_path / "表.xlsx"
    result = sheet_render.write_grid(out, [["A", "B", "C"], ["1", "2"]], preset="default")
    assert result["short_rows"] == [2]
    sheet = load_workbook(str(out)).active
    assert sheet["C2"].value is None
    assert result["cols"] == 3


def test_write_grid_rejects_empty_grid(tmp_path: Path) -> None:
    try:
        sheet_render.write_grid(tmp_path / "空.xlsx", [])
    except ValueError as exc:
        assert "至少要有一行" in str(exc)
    else:  # pragma: no cover - 没抛错就是回归
        raise AssertionError("空表应当报错，而不是写出一份空文件")


def test_render_table_keeps_sheet_type_behaviour(tmp_path: Path) -> None:
    """表类型决定「冻哪边、要不要筛选」，长相仍由 preset 决定。"""
    out = tmp_path / "排班.xlsx"
    sheet_render.render_table(
        out,
        [["张三", "早班"], ["李四", "晚班"]],
        headers=["姓名", "班次"],
        sheet_type="排班",
        preset="default",
    )
    sheet = load_workbook(str(out)).active
    assert sheet.freeze_panes == "B2"
    assert sheet.auto_filter.ref is None


def test_strip_proof_sheets_drops_appendix_but_keeps_check_notes(tmp_path: Path) -> None:
    """删「识别原文」整张表，留「核对说明」——那是结论，不是流水账。"""
    out = tmp_path / "课表.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "课表"
    sheet.append(["节次", "周一"])
    sheet.append(["1–2", "语文"])

    notes = workbook.create_sheet("核对说明")
    notes.append(["事项", "说明"])
    notes.append(["8:00–8:45", "原图识别为 8:00-3:45，按两节 45 分推回 8:45"])

    raw = workbook.create_sheet("识别原文")
    raw.append(["图片识别原文（行列错位，仅作对照）"])
    raw.append(["时间周一 | 周二 | 周三 1 | 8:00-3:45 | 移动应用服务器编"])
    workbook.save(str(out))

    removed = xlsx_utils.strip_proof_sheets(out)
    assert removed == ["识别原文"]

    names = load_workbook(str(out)).sheetnames
    assert "识别原文" not in names
    assert "核对说明" in names and "课表" in names


def test_strip_proof_sheets_removes_a_section_inside_the_same_sheet(tmp_path: Path) -> None:
    """同一张表末尾挂的附录也要摘掉，正文和它前面的小节不动。"""
    out = tmp_path / "表.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "数据"
    sheet.append(["区域", "金额"])
    sheet.append(["华东", 1200])
    sheet.append([None, None])
    sheet.append(["识别原文（仅作对照）"])
    sheet.append(["华东 | 1200 | 华南 | 800"])
    sheet.append(["核对说明"])
    workbook.save(str(out))

    removed = xlsx_utils.strip_proof_sheets(out)
    assert removed == ["数据!4:5"]

    sheet = load_workbook(str(out)).active
    kept = [row[0].value for row in sheet.iter_rows(min_row=1, max_row=sheet.max_row)]
    assert "华东" in kept
    assert not any(value and "识别原文" in str(value) for value in kept)
    # 它后面那节标题与内容都还在：只删附录这一段
    assert "核对说明" in kept


def test_strip_proof_sheets_leaves_clean_workbook_untouched(tmp_path: Path) -> None:
    out = tmp_path / "干净.xlsx"
    xlsx_utils.write_table(out, [["华东", 1200]], headers=["区域", "金额"])
    assert xlsx_utils.strip_proof_sheets(out) == []
