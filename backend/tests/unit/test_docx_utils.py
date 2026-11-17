"""docx_utils 回归测试（对应 docs/docx-knowledge-base-2026-10-25.md 第五节 smoke 用例）。

这些断言都落在 **XML 层**，而不是「函数没抛异常」：
中文字体要真写进 `w:rFonts/@w:eastAsia`，三线表要真把 insideH 置 nil，
跨 run 的替换要真的替换掉——这几点恰是手写脚本最容易踩的坑。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from app.services import docx_utils as d
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Pt


@pytest.fixture()
def sample(tmp_path: Path) -> Path:
    """一份「有正文、有标题、有一句话被拆成两个 run」的样例文档。"""
    doc = Document()
    doc.add_heading("2026 年 10 月周报", level=0)
    doc.add_heading("本周进展", level=1)
    doc.add_paragraph("本周完成了文档能力梳理。")
    doc.add_paragraph("下周重点是补齐风格预设。")
    # 人为拆 run：Word 里「关键词」常被拆开，替换逻辑必须能跨 run 命中
    split = doc.add_paragraph()
    split.add_run("这段里有个")
    split.add_run("关键词")
    split.add_run("需要替换。")
    path = tmp_path / "sample.docx"
    doc.save(path)
    return path


def test_apply_body_sets_font_size_spacing_and_east_asia(sample: Path) -> None:
    doc = Document(sample)
    touched = d.apply_body(doc, line=d.LINE_ONE_HALF)

    assert touched >= 3
    body = next(p for p in doc.paragraphs if p.text.startswith("本周完成"))
    run = body.runs[0]
    assert run.font.size == Pt(12)  # 小四
    assert body.paragraph_format.line_spacing == 1.5
    assert body.paragraph_format.first_line_indent == Pt(24)  # 2 字符
    # 中文字体必须写 eastAsia，只写 font.name 在 Word 里不生效
    rFonts = run._element.find(qn("w:rPr")).find(qn("w:rFonts"))
    assert rFonts.get(qn("w:eastAsia")) == "宋体"
    assert rFonts.get(qn("w:ascii")) == "Times New Roman"


def test_apply_body_leaves_headings_alone(sample: Path) -> None:
    doc = Document(sample)
    d.apply_body(doc)
    heading = next(p for p in doc.paragraphs if p.style.name in {"Heading 1", "Title"})
    # 标题不应被正文格式覆盖成 12pt
    assert heading.runs and heading.runs[0].font.size in (None, Pt(16), Pt(22), Pt(26))


def test_apply_headings_writes_style_fonts(sample: Path) -> None:
    doc = Document(sample)
    # 四级标题也一起设：三级标题下面的细分项不能退回正文大小
    assert d.apply_headings(doc) == 4
    style = doc.styles["Heading 1"]
    assert style.font.size == Pt(16)
    assert style.font.bold is True
    rFonts = style.element.get_or_add_rPr().find(qn("w:rFonts"))
    assert rFonts.get(qn("w:eastAsia")) == "黑体"


def test_set_page_applies_gongwen_margins(sample: Path) -> None:
    doc = Document(sample)
    assert d.set_page(doc, d.PAGE_GONGWEN) == 1
    section = doc.sections[0]
    # Word 的页边距单位是 twip，3.7cm 存盘后会四舍五入，这里按 cm 比到 0.01
    assert section.top_margin.cm == pytest.approx(3.7, abs=0.01)
    assert section.bottom_margin.cm == pytest.approx(3.5, abs=0.01)
    assert section.left_margin.cm == pytest.approx(2.8, abs=0.01)
    assert section.right_margin.cm == pytest.approx(2.6, abs=0.01)


def test_triple_table_zeroes_inside_borders_and_bolds_header(tmp_path: Path) -> None:
    doc = Document()
    table = d.add_table_simple(doc, ["项目", "金额"], [["差旅", "1200"], ["餐费", "300"]])

    header_run = table.rows[0].cells[0].paragraphs[0].runs[0]
    assert header_run.font.bold is True
    assert header_run.font.size == Pt(10.5)  # 五号

    borders = table._tbl.tblPr.find(qn("w:tblBorders"))
    assert borders.find(qn("w:insideH")).get(qn("w:val")) == "nil"
    assert borders.find(qn("w:top")).get(qn("w:sz")) == "12"
    assert borders.find(qn("w:top")).get(qn("w:val")) == "single"
    # 表头跨页重复
    assert table.rows[0]._tr.get_or_add_trPr().find(qn("w:tblHeader")) is not None


def test_grid_table_keeps_all_borders(tmp_path: Path) -> None:
    doc = Document()
    table = d.add_table_simple(doc, ["姓名"], [["张三"]], style="grid", header_fill="EEF1F6")
    borders = table._tbl.tblPr.find(qn("w:tblBorders"))
    assert borders.find(qn("w:insideV")).get(qn("w:val")) == "single"
    shd = table.rows[0].cells[0]._tc.get_or_add_tcPr().find(qn("w:shd"))
    assert shd.get(qn("w:fill")) == "EEF1F6"


def test_replace_text_counts_runs_and_cross_run(sample: Path) -> None:
    doc = Document(sample)

    # 单 run 命中 1 次 + 跨两个 run 的组合命中 1 次
    assert d.replace_text(doc, "下周", "下阶段") == 1
    assert d.replace_text(doc, "关键词", "关键指标") == 1
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "下阶段重点" in text
    assert "关键指标需要替换" in text


def test_replace_text_ignores_empty_old(sample: Path) -> None:
    doc = Document(sample)
    assert d.replace_text(doc, "", "x") == 0


def test_replace_text_reaches_tables_and_footer(tmp_path: Path) -> None:
    doc = Document()
    doc.add_paragraph("正文含旧词")
    table = doc.add_table(rows=1, cols=1)
    table.cell(0, 0).text = "表格旧词"
    doc.sections[0].footer.paragraphs[0].text = "页脚旧词"

    assert d.replace_text(doc, "旧词", "新词") == 3


def test_add_page_number_inserts_page_field(sample: Path) -> None:
    doc = Document(sample)
    d.add_page_number(doc.sections[0], align="center")
    footer = doc.sections[0].footer.paragraphs[0]
    instr = footer._p.findall(".//" + qn("w:instrText"))
    assert any(node.text == "PAGE" for node in instr)


def test_read_report_counts_structure(sample: Path) -> None:
    report = d.read_report(Document(sample))
    assert report["paragraphs"] >= 5
    assert report["chars"] > 0
    assert report["tables"] == 0
    assert "Normal" in report["styles"]


def test_read_report_accepts_path_directly(sample: Path) -> None:
    """模型最常写的 `read_report(src)`（src 是路径）不能报
    `'str' object has no attribute 'paragraphs'`——这是工具报错的头号来源。"""
    by_path = d.read_report(str(sample))
    by_document = d.read_report(Document(sample))
    assert by_path == by_document


def test_ensure_doc_explains_missing_input() -> None:
    with pytest.raises(ValueError, match="OA_INPUT_DIR"):
        d.ensure_doc(None)
    with pytest.raises(FileNotFoundError, match="找不到 docx"):
        d.ensure_doc("不存在的.docx")


def test_set_page_accepts_preset_name_and_kwarg(sample: Path) -> None:
    """`set_page(doc, "gongwen")` 和 `set_page(doc, preset="gongwen")` 都要能用，
    等价于 `set_page(doc, PAGE_PRESETS["gongwen"])`。"""
    by_dict = Document(sample)
    d.set_page(by_dict, d.PAGE_PRESETS["gongwen"])

    by_name = Document(sample)
    d.set_page(by_name, "gongwen")

    by_kwarg = Document(sample)
    d.set_page(by_kwarg, preset="gongwen")

    assert by_name.sections[0].top_margin == by_dict.sections[0].top_margin
    assert by_kwarg.sections[0].left_margin == by_dict.sections[0].left_margin
    with pytest.raises(KeyError, match="未知页面预设"):
        d.set_page(Document(sample), preset="不存在")


def test_backup_copies_into_output_dir_without_touching_source(
    sample: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    out.mkdir()
    before = sample.read_bytes()

    backup = Path(d.backup(str(sample), str(out)))

    assert backup.exists()
    assert backup.parent == out
    assert "_备份_" in backup.name
    assert sample.read_bytes() == before  # 原件一个字节都没动
    assert backup.read_bytes() == before


def test_set_para_hanging_indent_for_lists(sample: Path) -> None:
    doc = Document(sample)
    paragraph = doc.add_paragraph("列表项")
    d.set_para(
        paragraph,
        line=d.LINE_SINGLE,
        indent_pt=18,
        hanging=True,
        align=WD_ALIGN_PARAGRAPH.LEFT,
    )
    fmt = paragraph.paragraph_format
    assert fmt.first_line_indent == Pt(-18)
    assert fmt.left_indent == Pt(18)
    assert fmt.alignment == WD_ALIGN_PARAGRAPH.LEFT


def test_utils_files_are_shipped_into_code_workspace(tmp_path: Path) -> None:
    """code.run_python 的工作目录里必须能找到工具库，脚本才能直接 import。"""
    from app.tools.builtin import code as code_tool

    root = tmp_path / "workspace"
    root.mkdir()
    code_tool._install_utils(root)
    for name in ("docx_utils", "pdf_utils", "xlsx_utils", "text_utils"):
        target = root / f"{name}.py"
        assert target.is_file(), f"{name}.py 没有预置进工作目录"
    # 词表模块不进提示词清单，但每个 *_utils 都直接 import 自己那份，缺了脚本一跑就 ImportError
    for name in ("doc_lexicon", "slide_lexicon", "sheet_lexicon", "text_lexicon"):
        assert (root / f"{name}.py").is_file(), f"词表模块 {name} 没有跟着复制"
    assert "def apply_body" in (root / "docx_utils.py").read_text(encoding="utf-8")
    assert "FONT_SIZES" in (root / "doc_lexicon.py").read_text(encoding="utf-8")
    assert "MAX_BULLETS_PER_SLIDE" in (root / "slide_lexicon.py").read_text(encoding="utf-8")
    assert "NUMBER_FORMATS" in (root / "sheet_lexicon.py").read_text(encoding="utf-8")
    assert "SECTION_MARKS" in (root / "text_lexicon.py").read_text(encoding="utf-8")
    assert "def make_pdf" in (root / "pdf_utils.py").read_text(encoding="utf-8")
    assert "def group_sum" in (root / "xlsx_utils.py").read_text(encoding="utf-8")
    assert "def md_to_docx" in (root / "text_utils.py").read_text(encoding="utf-8")


def test_generated_script_runs_with_utils_end_to_end(sample: Path, tmp_path: Path) -> None:
    """按知识库里的典型脚本骨架真跑一次：读素材 → 套样式 → 存产物。"""
    import subprocess
    import sys

    work = tmp_path / "work"
    work.mkdir()
    shutil.copy2(sample, work / "in.docx")
    from app.tools.builtin import code as code_tool

    code_tool._install_utils(work)

    script = """
from docx import Document
from docx_utils import *

doc = Document("in.docx")
set_page(doc, PAGE_DEFAULT)
apply_body(doc, line=1.5)
apply_headings(doc)
replace_text(doc, "下周", "下阶段")
doc.save("out.docx")
print("ok")
"""
    (work / "main.py").write_text(script, encoding="utf-8")
    completed = subprocess.run(  # noqa: S603 - 固定解释器 + 固定脚本
        [sys.executable, str(work / "main.py")],
        cwd=str(work),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert (work / "out.docx").is_file()

    out = Document(work / "out.docx")
    body = next(p for p in out.paragraphs if p.text.startswith("下阶段重点"))
    assert body.runs[0].font.size == Pt(12)


def test_set_page_accepts_constant_name_as_preset(sample: Path) -> None:
    """模型常把常量名当字符串传：`set_page(doc, preset="PAGE_DEFAULT")`。

    以前直接抛 KeyError「未知页面预设」，看起来像模板不支持，其实只是写法差异。
    """
    by_default = Document(sample)
    d.set_page(by_default, d.PAGE_DEFAULT)

    for name in ("PAGE_DEFAULT", "page_default", "page-default", " Default "):
        doc = Document(sample)
        assert d.set_page(doc, preset=name) == 1
        assert doc.sections[0].top_margin == by_default.sections[0].top_margin


def test_add_page_number_accepts_whole_document(sample: Path) -> None:
    """页码该收 Document：模型写 doc.footer 会直接 AttributeError。"""
    doc = Document(sample)
    assert d.add_page_number(doc) == len(doc.sections)

    footer_xml = doc.sections[0].footer.paragraphs[0]._p.xml
    assert "w:instrText" in footer_xml and "PAGE" in footer_xml

    # 老写法（传单个 section）保持不变
    one = Document(sample)
    assert d.add_page_number(one.sections[0], align="右") == 1


def test_set_para_accepts_paragraph_level_font_aliases() -> None:
    """`set_para(p, size=16, bold=True, align='center', space_after=10)` 要能用。

    这是模型最常写的形状（段落 + 字体一把设）。旧版只认 indent_pt/before/after，
    一次误写就整段脚本失败，用户看到的是「排版又没做」。
    """
    doc = Document()
    p = doc.add_paragraph("标题文字")

    d.set_para(p, size=16, bold=True, align="center", space_after=10)

    assert p.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert p.paragraph_format.space_after == Pt(10)
    run = p.runs[0]
    assert run.font.size == Pt(16)
    assert run.font.bold is True


def test_set_para_styles_empty_paragraph_instead_of_dropping_it() -> None:
    """空段落没有 run：别名不能静默丢掉，否则「设了 16pt 却还是正文大小」。"""
    doc = Document()
    p = doc.add_paragraph("")

    d.set_para(p, size=22, bold=True, align="center")

    assert p.runs, "空段落应补一个 run 承载字体设置"
    assert p.runs[0].font.size == Pt(22)
    assert p.alignment == WD_ALIGN_PARAGRAPH.CENTER


def test_set_font_accepts_single_font_keyword() -> None:
    """`set_font(run, font='Consolas')` 等价于中英文都设成 Consolas。"""
    doc = Document()
    run = doc.add_paragraph("code").runs[0]

    d.set_font(run, font="Consolas", size=10)

    rFonts = run._element.get_or_add_rPr().find(qn("w:rFonts"))
    assert rFonts.get(qn("w:eastAsia")) == "Consolas"
    assert rFonts.get(qn("w:ascii")) == "Consolas"
    assert run.font.size == Pt(10)
