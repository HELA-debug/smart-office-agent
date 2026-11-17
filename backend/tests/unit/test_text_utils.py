"""text_utils 单测：编码识别、Markdown 规范化、表格对齐、md→docx。

编码是这个模块最容易出事的地方：Windows 导出的 txt 常是 GBK/UTF-16，
读错就变乱码、写回就毁文件，所以三种编码都实测一遍。
"""

from __future__ import annotations

from pathlib import Path

import docx
from app.services import text_utils


def test_detect_and_read_encodings(tmp_path: Path) -> None:
    cases = {
        "utf8.txt": ("utf-8", "中文内容"),
        "gbk.txt": ("gb18030", "中文内容"),
        "utf16.txt": ("utf-16", "中文内容"),
    }
    for name, (codec, content) in cases.items():
        path = tmp_path / name
        path.write_text(content, encoding=codec)
        result = text_utils.read_text(path)
        assert result["text"] == content
        assert result["encoding"] in {codec, "utf-8"}


def test_read_text_normalizes_crlf(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes("第一行\r\n第二行\r第三行".encode())
    text = text_utils.read_text(path)["text"]
    assert "\r" not in text
    assert text.count("\n") == 2


def test_write_text_uses_lf(tmp_path: Path) -> None:
    out = tmp_path / "out.txt"
    text_utils.write_text(out, "一行\r\n二行")
    assert out.read_bytes() == "一行\n二行".encode()


def test_heading_tree_marks_skipped_levels() -> None:
    tree = text_utils.heading_tree("# 一级\n\n### 三级\n\n```\n# 代码里的井号\n```\n")
    assert [item["level"] for item in tree] == [1, 3]
    assert tree[1]["skipped"] is True


def test_normalize_markdown_fixes_headings_and_tables() -> None:
    result = text_utils.normalize_markdown("#标题\n\n\n\n| a | b |\n| 1 | 2 |\n")
    assert result["fixed_headings"] == 1
    assert result["fixed_tables"] == 1
    assert "# 标题" in result["text"]
    assert "| --- | --- |" in result["text"]
    assert "\n\n\n" not in result["text"]


def test_md_table_is_valid_markdown() -> None:
    table = text_utils.md_table([["1", "合同A"]], headers=["序号", "名称"])
    lines = table.strip().split("\n")
    assert lines[0].startswith("| 序号")
    assert set(lines[1].replace("|", "").replace(" ", "")) == {"-"}
    assert lines[2].startswith("| 1")


def test_txt_stats_and_wrap() -> None:
    stats = text_utils.txt_stats("你好 world\n\n第二段")
    assert stats["cjk_chars"] == 5
    assert stats["paragraphs"] == 2
    wrapped = text_utils.txt_wrap("这是一段很长的中文文字" * 2, width=10)
    assert max(len(line) for line in wrapped.splitlines()) <= 10


def test_split_by_heading() -> None:
    sections = text_utils.split_by_heading("# A\naaa\n# B\nbbb\n")
    assert [item["title"] for item in sections] == ["A", "B"]
    assert "bbb" in sections[1]["content"]


def test_md_to_docx_keeps_structure(tmp_path: Path) -> None:
    md = (
        "# 周报\n\n## 本周完成\n\n- 完成 A\n- 完成 B\n\n"
        "| 项目 | 进度 |\n| --- | --- |\n| A | 80% |\n\n正文 **重点** 一段。\n"
    )
    result = text_utils.md_to_docx(md, tmp_path / "out.docx", title="周报")
    document = docx.Document(result["out"])
    headings = [p.text for p in document.paragraphs if p.style.name.startswith("Heading")]
    assert "周报" in headings
    assert "本周完成" in headings
    assert len(document.tables) == 1
    assert document.tables[0].cell(1, 0).text == "A"
    assert any(run.bold for p in document.paragraphs for run in p.runs)


def test_md_to_docx_numbered_items_keep_a_single_space(tmp_path: Path) -> None:
    """有序条目：序号写进行首，后面只跟一个空格。

    以前挂 Word 的 List Number 样式，它自带 720 twips 左缩进 + 制表位，序号和正文
    之间空出两三个字（用户 2026-11-09 反馈「间隔太远，很不合理」）。
    """
    document = docx.Document(
        text_utils.md_to_docx("1. 打开电源\n2. 按下复位\n", tmp_path / "list.docx", title="步骤")[
            "out"
        ]
    )
    items = [p for p in document.paragraphs if p.text.startswith("1.")]
    assert items and items[0].text == "1. 打开电源"
    item = items[0]
    assert item.style.name == "Normal"
    # 不再有「左缩进 + 悬挂」那套：位置由正文的首行缩进（两字符）顶着
    assert not item.paragraph_format.left_indent
    assert "w:numPr" not in item._p.xml
    assert "2. 按下复位" in [p.text for p in document.paragraphs]
