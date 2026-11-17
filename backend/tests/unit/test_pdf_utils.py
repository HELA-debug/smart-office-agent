"""pdf_utils 单测：生成 → 读回 → 合并/拆分/旋转/水印，全部走真实 pypdf。

为什么用真实文件而不是 mock：PDF 的坑几乎都在「写出来的东西读不回来」，
mock 掉 pypdf 就等于什么都不验。这里只用 pypdf 能可靠回答的元信息（页数、旋转角、
是否有文本层），不校验中文文本内容 —— CID 字体提取出来是 CID 码，不是汉字。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from app.services import pdf_utils
from pypdf import PdfReader
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT


def _make(tmp_path: Path, pages: int = 2) -> Path:
    blocks: list[dict] = []
    for index in range(pages):
        if index:
            blocks.append({"type": "pagebreak"})
        blocks.append({"type": "h1", "text": f"第 {index + 1} 节"})
        blocks.append({"type": "p", "text": "正文一段，含 & < > 等需要转义的字符。"})
        blocks.append({"type": "table", "rows": [["项目", "值"], ["A", "1"]]})
    out = tmp_path / "demo.pdf"
    pdf_utils.make_pdf(out, "季度报告", blocks, footer_text="内部资料")
    return out


def test_make_pdf_writes_pages_and_footer(tmp_path: Path) -> None:
    out = _make(tmp_path, pages=2)
    assert out.read_bytes().startswith(b"%PDF")
    reader = PdfReader(str(out))
    assert len(reader.pages) == 2
    text = reader.pages[0].extract_text() or ""
    # 页码与页脚是 reportlab 直接画的西文/数字，能稳定读出来
    assert "1" in text


def test_pdf_body_is_justified_and_headings_left(tmp_path: Path) -> None:
    """正文两端对齐要真的落到 PDF 上，不能只是样式里写了个 TA_JUSTIFY。

    reportlab 的 TA_JUSTIFY 只设 Tw（词间距），而 Tw 只作用于半角空格——中文段落
    里没有空格，一个字都拉不开，画出来还是左对齐。所以这里直接读内容流：只要出现
    非零的 Tc（字符间距），才说明每行是按字摊开、铺满版心的。

    标题反过来：各级小节标题左对齐、从左边距起行，不能吃这套按字铺开的排法。
    居中的只有文首标题块（大标题 / 副标题 / 信息行）——那是「这是题目、这是谁的
    材料」的信号，每节标题都居中，读者扫目录时视线得来回跳。
    """
    out = tmp_path / "justify.pdf"
    pdf_utils.make_pdf(
        out,
        "",
        [
            {
                "type": "p",
                "text": "本周完成了三件事，其中数据分析部分进展顺利，另外两项因为上游数据延迟略推迟。"
                * 2,
            },
            {"type": "h1", "text": "一、本周进展"},
        ],
    )

    styles = pdf_utils._styles("default")
    assert styles["body"].alignment == TA_JUSTIFY
    assert styles["h1"].alignment == TA_LEFT
    assert pdf_utils._styles("gongwen")["h1"].alignment == TA_LEFT
    # 中文不开 CJK 断行，reportlab 只按空格断词，一整段会被当一个超长单词劈开
    assert styles["body"].wordWrap == "CJK"

    contents = PdfReader(str(out)).pages[0].get_contents()
    data = contents.get_data().decode("latin-1")
    assert re.search(r"[-0-9.]+ Tc", data), "正文没有按字间距铺开，两端对齐等于没设"


def test_read_report_flags_scanned_and_encrypted(tmp_path: Path) -> None:
    out = _make(tmp_path, pages=1)
    report = pdf_utils.read_report(out)
    assert report["pages"] == 1
    assert report["encrypted"] is False
    assert isinstance(report["metadata"], dict)
    assert report["scanned"] is False

    blank = tmp_path / "blank.pdf"
    pdf_utils.make_pdf(blank, "", [], page_numbers=False)
    blank_report = pdf_utils.read_report(blank)
    assert blank_report["pages"] == 1
    assert blank_report["scanned"] is True
    assert blank_report["empty_pages"] == [1]


def test_merge_split_and_rotate(tmp_path: Path) -> None:
    first = _make(tmp_path, pages=2)
    merged = pdf_utils.merge_pdfs([first, first], tmp_path / "merged.pdf")
    assert merged["pages"] == 4
    assert merged["files"] == ["demo.pdf", "demo.pdf"]

    parts = pdf_utils.split_pdf(merged["out"], tmp_path / "split", every=2)
    assert [Path(item).name for item in parts] == ["merged_p1-2.pdf", "merged_p3-4.pdf"]

    one = pdf_utils.split_pdf(merged["out"], tmp_path / "one", ranges=[(2, 3)])
    assert len(one) == 1
    assert len(PdfReader(one[0]).pages) == 2

    rotated = pdf_utils.rotate_pages(merged["out"], tmp_path / "rot.pdf", [1], 90)
    reader = PdfReader(rotated)
    assert reader.pages[0].get("/Rotate") == 90
    assert reader.pages[1].get("/Rotate") in (None, 0)


def test_watermark_keeps_page_count(tmp_path: Path) -> None:
    src = _make(tmp_path, pages=2)
    out = pdf_utils.watermark(src, tmp_path / "wm.pdf", "内部资料")
    assert len(PdfReader(out).pages) == 2


def test_render_markdown_pdf_handles_tables(tmp_path: Path) -> None:
    md = "# 标题\n\n正文一段\n\n| 列A | 列B |\n| --- | --- |\n| 1 | 2 |\n"
    result = pdf_utils.render_markdown_pdf(md, tmp_path / "md.pdf")
    assert result["blocks"]["table"] == 1
    assert len(PdfReader(result["out"]).pages) >= 1


def test_backup_copies_file(tmp_path: Path) -> None:
    src = _make(tmp_path, pages=1)
    copy = pdf_utils.backup(src, tmp_path / "bak")
    assert Path(copy).is_file()
    assert Path(copy).name == "demo.bak.pdf"
    assert Path(copy).read_bytes() == src.read_bytes()


def test_missing_file_raises() -> None:
    with pytest.raises(FileNotFoundError):
        pdf_utils.read_report("不存在的.pdf")


def test_pdf_title_block_is_centered_and_section_headings_are_not(tmp_path: Path) -> None:
    """文首标题块三行居中，小节标题左起——和 docx 那边是同一套规则。

    副标题必须比正文大一档：字号一样只靠居中区分时，看起来像「正文第一段被居中」。
    信息行（姓名 / 学号 / 专业）是落款，不空两格。
    """
    out = tmp_path / "block.pdf"
    pdf_utils.make_pdf(
        out,
        "实验二　光照自适应调光实验报告",
        [
            {"type": "p", "text": "基于 Wokwi 的 ESP32 物联网仿真实验"},
            {"type": "p", "text": "姓名：敬一博　学号：202416320112　专业：智慧能源"},
            {"type": "p", "text": "本实验在 Wokwi 的 ESP32 仿真平台完成，器件均为虚拟。"},
            {"type": "h1", "text": "1 实验设备"},
        ],
    )

    styles = pdf_utils._styles("default")
    assert styles["title"].alignment == TA_CENTER
    assert styles["subtitle"].alignment == TA_CENTER
    assert styles["byline"].alignment == TA_CENTER
    assert styles["subtitle"].fontSize > styles["body"].fontSize
    assert styles["byline"].firstLineIndent == 0
    assert styles["h1"].alignment == TA_LEFT


def test_subtitle_and_byline_recognition() -> None:
    """副标题是「标题下一行短句」，信息行是「字段：值」，两者不能认混。"""
    assert pdf_utils._looks_like_subtitle("基于 Wokwi 的 ESP32 物联网仿真实验")
    # 带句末标点的是正文第一段，判成副标题整段就被居中，比不居中更糟
    assert not pdf_utils._looks_like_subtitle("本实验在 Wokwi 的 ESP32 仿真平台完成，器件均为虚拟。")
    # 信息行交给 byline，不走副标题那一档
    assert not pdf_utils._looks_like_subtitle("姓名：敬一博　学号：202416320112")
    from app.services.doc_render import looks_like_byline

    assert looks_like_byline("姓名：敬一博　学号：202416320112　专业：智慧能源")
    assert looks_like_byline("实验名称：光照自适应调光　实验方式：Wokwi 在线仿真")
    assert not looks_like_byline("结论：本周进度落后，需要增加两个人手")
