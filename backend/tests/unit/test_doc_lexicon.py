"""文档格式词表（services/doc_lexicon）单元测试。

这一层的价值全在「词认得准」：模型写「一点五倍」「小四号」「固定值28磅」这些说法，
解析不出来就等于回复「不支持的格式」，用户看到的是「排版又没做」。
所以断言集中在解析器的宽容度，以及几张表之间不打架（标题永远比正文大）。
"""

from __future__ import annotations

import pytest
from app.services.doc_lexicon import (
    DOC_TYPES,
    FONT_SIZES,
    FONTS,
    HEADING_SCALES,
    PAGES,
    resolve_align,
    resolve_indent,
    resolve_line,
    resolve_size,
)
from docx.shared import Pt


def test_chinese_size_names_map_to_word_points() -> None:
    assert resolve_size("小四") == 12.0
    assert resolve_size("三号") == 16.0
    assert resolve_size("五号") == 10.5
    # 带「号」、带单位、纯数字都要认
    assert resolve_size("小四号") == 12.0
    assert resolve_size("12pt") == 12.0
    assert resolve_size("12磅") == 12.0
    assert resolve_size(10.5) == 10.5


def test_unknown_size_explains_what_to_write() -> None:
    with pytest.raises(KeyError, match="认不出字号"):
        resolve_size("很大")


def test_line_spacing_accepts_colloquial_phrases() -> None:
    assert resolve_line("单倍") == 1.0
    assert resolve_line("一点五倍") == 1.5
    assert resolve_line("1.5 倍行距") == 1.5
    assert resolve_line("双倍") == 2.0
    assert resolve_line(1.25) == 1.25
    # 固定值与倍数是两套：固定 28 磅要落成 Length，不能被当成「28 倍」
    assert resolve_line("固定值28磅") == Pt(28)
    assert resolve_line(Pt(22)) == Pt(22)


def test_indent_is_counted_in_characters_not_points() -> None:
    assert resolve_indent("两字符") == 2.0
    assert resolve_indent("首行缩进2字符") == 2.0
    assert resolve_indent("不缩进") == 0.0
    assert resolve_indent(None) == 2.0


def test_align_accepts_chinese_and_falls_back_safely() -> None:
    assert resolve_align("居中") == "center"
    assert resolve_align("两端对齐") == "justify"
    assert resolve_align("看不懂的词") == "justify"


def test_every_heading_scale_is_larger_than_body_text() -> None:
    """标题比正文还小的稿子，层级只能靠编号猜——表里就不该出现这种组合。"""
    for name, rows in HEADING_SCALES.items():
        assert len(rows) == 4, name
        sizes = [resolve_size(size_name) for _, size_name in rows]
        assert sizes == sorted(sizes, reverse=True), f"{name} 的标题字号不是递减的：{sizes}"
        for font_name, _ in rows:
            assert font_name in FONTS, f"{name} 用了没登记的字体 {font_name}"


def test_doc_types_only_reference_known_presets() -> None:
    for name, spec in DOC_TYPES.items():
        assert spec["scale"] in HEADING_SCALES, name
        assert spec["page"] in PAGES, name
        assert spec["align"] in {"left", "center", "right", "justify"}, name


def test_font_table_pairs_chinese_and_latin_faces() -> None:
    """只写中文名的话，正文里的数字和英文会掉回模板默认字体。"""
    for name, (cn, en) in FONTS.items():
        assert cn and en, name
    assert FONT_SIZES["小四"] == 12.0
