"""四份词表与四个版式技能：改一处就能改全篇，是这个模块存在的唯一理由。

这里钉三件事：
1. 词表认得模型/用户真的会写的那些说法（「小4」「一倍半」「A4横版」「斑马纹」…）；
2. 每份词表都被对应工具库真正消费（不是死代码）；
3. 四个版式技能都带 frontmatter、都进了技能库，内容不会退化成空壳。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from app.services import doc_lexicon as doc
from app.services import sheet_lexicon as sheet
from app.services import slide_lexicon as slide
from app.services import text_lexicon as text
from app.services import xlsx_utils
from openpyxl import load_workbook

SKILLS = Path(__file__).resolve().parents[2] / "app" / "skills"
CATALOG = Path(__file__).resolve().parents[2] / "app" / "skills_catalog"

LAYOUT_SKILLS = ("doc-layout", "ppt-layout", "sheet-layout", "text-layout")


# ---------------------------------------------------------------- Word 词表
def test_doc_types_cover_the_common_office_documents() -> None:
    """常见文档类型都要在表里：判错类型，整套版式就歪。"""
    for name in (
        "周报",
        "月报",
        "会议纪要",
        "方案",
        "公文",
        "通知",
        "论文",
        "简历",
        "合同",
        "白皮书",
    ):
        assert name in doc.DOC_TYPES, f"{name} 没有版式参数"
    assert len(doc.DOC_TYPES) >= 50


def test_resolve_doc_type_accepts_aliases_and_never_raises() -> None:
    assert doc.resolve_doc_type("述职报告")["table"] == "triple"
    assert doc.resolve_doc_type("weekly") == doc.DOC_TYPES["周报"]
    assert doc.resolve_doc_type("工作周报（第 46 周）") == doc.DOC_TYPES["周报"]
    # 认不出不能抛：判错一个词不该让整份文档生成失败
    assert doc.resolve_doc_type("完全没听过的类型") == doc.DOC_TYPES["周报"]


def test_doc_type_aliases_cover_how_people_actually_say_it() -> None:
    """别名表按「用户怎么称呼这份东西」铺，不按类型名单铺。

    少收一条的代价不是判错，而是**判不出来**——落回默认那套，编号款式跟着不对，
    用户只觉得「它没听懂我说的是周报」。所以这张表要够厚：口语、行业叫法、英文
    都得能落到同一个键上。
    """
    cases = {
        "这周的周报": "周报",
        "本周周报": "周报",
        "weekly report": "周报",
        "月度汇报": "月报",
        "季度汇报": "季报",
        "年度报告": "年报",
        "述职材料": "述职报告",
        "会议纪要整理": "会议纪要",
        "实施方案": "方案",
        "需求说明书": "需求文档",
        "复盘报告": "分析报告",
        "红头文件": "公文",
        "毕业论文": "论文",
        "产品说明书": "说明书",
        "使用手册": "用户手册",
        "投标文件": "标书",
        "求职简历": "简历",
    }
    for phrase, expected in cases.items():
        assert doc.guess_doc_type(phrase) == expected, phrase


def test_slide_and_sheet_aliases_take_the_words_people_use() -> None:
    """演示稿与表格的别名同理：说「扉页」「流水」也要认，不能只认行话。"""
    from app.services import sheet_lexicon, slide_lexicon

    assert slide_lexicon.resolve_layout("扉页") == "cover"
    assert slide_lexicon.resolve_layout("转场") == "section"
    assert slide_lexicon.resolve_layout("KPI") == "data"
    assert slide_lexicon.resolve_layout("封底") == "closing"
    assert slide_lexicon.resolve_theme("蓝白")["bg"] == slide_lexicon.THEMES["商务蓝"]["bg"]

    sheets = {
        "流水": "台账",
        "明细表": "明细",
        "统计表": "汇总",
        "费用报销": "报销",
        "进销存": "库存",
        "考勤表": "考勤",
    }
    for word, expected in sheets.items():
        assert sheet_lexicon.resolve_sheet_type(word) == sheet_lexicon.SHEET_TYPES[expected], word


def test_numbering_schemes_follow_the_document_type() -> None:
    """编号是文体的一部分：周报「一、」、论文「1.1.1」、合同「第一条」、纪要不用编号。"""
    assert doc.resolve_numbering("周报") == "cn"
    assert doc.resolve_numbering("论文") == "decimal"
    assert doc.resolve_numbering("技术方案") == "decimal"
    assert doc.resolve_numbering("合同") == "article"
    assert doc.resolve_numbering("会议纪要") == "none"
    # 公文是国家标准把四层序数写死的那一套，不跟 cn 走
    assert doc.resolve_numbering("公文") == "gb"
    assert doc.resolve_numbering("请示") == "gb"
    # 直接点方案名（含口语说法）也要认
    assert doc.resolve_numbering("层级小数") == "decimal"
    assert doc.resolve_numbering("不编号") == "none"
    assert doc.resolve_numbering("中文序号") == "cn"
    assert doc.resolve_numbering("国标") == "gb"
    # 认不出落回 cn：中文序号在国内办公文档里最不容易出错
    assert doc.resolve_numbering("完全没听过的类型") == "cn"


def test_chinese_schemes_do_not_mix_han_and_arabic_numerals() -> None:
    """中文方案的每一级要么是中文序号、要么不编号——不许中途借阿拉伯数字。

    「一、→（一）→1.→（1）」读起来编号字形一路在跳，像两个人拼的稿子。
    中文没有通行的第三级纯中文序号，所以三级起就不编号（空模板）。
    """
    for scheme in ("cn", "article"):
        for depth, template in enumerate(doc.NUMBERING_SCHEMES[scheme], start=1):
            assert "{n}" not in template and "{dot}" not in template, (scheme, depth)

    # 唯一允许混排的是公文国标（GB/T 9704），并且只到四层
    assert doc.NUMBERING_SCHEMES["gb"][2] == "{n}. "
    assert doc.resolve_numbering("公文") == "gb"


def test_every_doc_type_points_at_a_real_numbering_scheme() -> None:
    for name, row in doc.DOC_TYPES.items():
        assert row["number"] in doc.NUMBERING_SCHEMES, name
    # 五档都有人用；有一档没人用，等于写了张死表
    assert {row["number"] for row in doc.DOC_TYPES.values()} == {
        "cn",
        "decimal",
        "article",
        "none",
        "gb",
    }


def test_guess_doc_type_reads_the_title() -> None:
    """标题里写着「周报」就按周报排，不必让模型显式传 doc_type。"""
    assert doc.guess_doc_type("W46 周报") == "周报"
    assert doc.guess_doc_type("2026 年技术方案（初稿）") == "技术方案"
    # 长键优先：「述职报告」不能被「报告」抢走，否则编号会从 cn 变 decimal
    assert doc.guess_doc_type("第三季度述职报告") == "述职报告"
    # 认不出给空串，让调用方落回默认，不猜
    assert doc.guess_doc_type("退款率复盘") == ""
    assert doc.guess_doc_type("") == ""


def test_fonts_fall_back_to_the_same_family() -> None:
    """写了个系统里没装的字体，退回同族，而不是掉回宋体。"""
    assert doc.resolve_font("楷体_GB2312")[0] == "楷体_GB2312"
    assert doc.resolve_font("华文中宋")[0] == "华文中宋"
    assert doc.resolve_font("微软雅黑 Light") == ("微软雅黑", "Segoe UI")
    assert doc.resolve_font("瞎写的字体") == ("宋体", "Times New Roman")


def test_page_aliases_cover_a4_landscape_and_book_sizes() -> None:
    assert doc.page_spec("A4横版")["width"].cm == pytest.approx(29.7)
    assert doc.page_spec("16开")["height"].cm == pytest.approx(26.0)
    with pytest.raises(KeyError):
        doc.page_spec("不存在的纸")


def test_heading_scales_are_ordered_from_large_to_small() -> None:
    """同一套刻度里，一级标题不能比二级小：层级靠字号差看出来。"""
    for name in doc.HEADING_SCALES:
        sizes = [spec[2] for spec in doc.heading_specs(name)]
        assert sizes == sorted(sizes, reverse=True), f"{name} 的标题刻度是乱的"


def test_table_style_synonyms_include_zebra() -> None:
    assert doc.TABLE_STYLES["斑马纹"] == "zebra"
    assert doc.TABLE_STYLES["全部框线"] == "grid"
    assert doc.TABLE_STYLES["三线表"] == "triple"


# ---------------------------------------------------------------- PPT 词表
def test_slide_sizes_and_layouts() -> None:
    assert slide.slide_size("16:9") == (12192000, 6858000)
    assert slide.slide_size("宽屏") == slide.SLIDE_SIZES["16:9"]
    assert slide.slide_size("没听过") == slide.SLIDE_SIZES["16:9"]
    assert slide.resolve_layout("封面页") == "cover"
    assert slide.resolve_layout("对比") == "two_col"
    assert slide.resolve_layout("没听过") == "bullets"
    # 一页六条是硬约束：十二条要点投到墙上没人读得完
    assert slide.MAX_BULLETS_PER_SLIDE == 6


def test_slide_themes_have_all_four_colors() -> None:
    for name, theme in slide.THEMES.items():
        assert set(theme) == {"bg", "title", "body", "accent"}, f"{name} 缺色值"
    assert slide.resolve_theme("党建")["title"] == slide.THEMES["党政红"]["title"]


def test_pptx_utils_uses_the_slide_lexicon() -> None:
    from app.services import pptx_utils

    assert slide.SLIDE_SIZES["16:9"] == pptx_utils.SLIDE_16_9
    assert pptx_utils.FONT_SIZES["body"] == slide.FONT_SIZES["body"]


def test_write_deck_splits_pages_over_six_bullets(tmp_path: Path) -> None:
    """一页塞十二条要点等于没排版：超过六条自动拆页，而不是截掉内容。"""
    from app.services import pptx_utils

    path = tmp_path / "deck.pptx"
    bullets = [f"要点 {index}" for index in range(9)]
    pptx_utils.write_deck(path, [{"title": "进展", "bullets": bullets}])

    pages = pptx_utils.extract_slides(path)
    assert len(pages) == 2
    assert len(pages[0]["bullets"]) == 6
    assert len(pages[1]["bullets"]) == 3
    assert pages[1]["title"].endswith("（续）")


# ---------------------------------------------------------------- Excel 词表
def test_sheet_formats_follow_the_column_name() -> None:
    assert sheet.format_for("金额（元）") == sheet.NUMBER_FORMATS["金额"]
    assert sheet.format_for("完成率") == sheet.NUMBER_FORMATS["百分比"]
    assert sheet.format_for("下单日期") == sheet.NUMBER_FORMATS["日期"]
    assert sheet.format_for("工号") == sheet.NUMBER_FORMATS["文本"]
    assert sheet.format_for("备注") is None  # 认不出就不设，别乱套


def test_sheet_widths_and_types() -> None:
    assert sheet.width_for("备注") > sheet.width_for("日期")
    assert sheet.resolve_sheet_type("考勤")["freeze"] == "first_col"
    assert sheet.resolve_sheet_type("没听过") == sheet.SHEET_TYPES["台账"]


def test_write_table_infers_formats_and_keeps_leading_zeros(tmp_path: Path) -> None:
    """金额带货币、占比带百分号、00123 不被转成 123——这三处错用户一眼就看见。"""
    path = tmp_path / "t.xlsx"
    xlsx_utils.write_table(
        path,
        [["00123", 12000, 0.125]],
        headers=["编号", "金额", "完成率"],
        sheet_type="台账",
    )
    worksheet = load_workbook(path).active
    assert worksheet["A2"].number_format == "@"
    assert worksheet["B2"].number_format == sheet.NUMBER_FORMATS["金额"]
    assert worksheet["C2"].number_format == sheet.NUMBER_FORMATS["百分比"]
    assert worksheet.column_dimensions["C"].width == sheet.width_for("完成率")


# ---------------------------------------------------------------- 纯文本词表
def test_text_marks_and_widths() -> None:
    assert text.section_mark("方括号") == ("【", "】")
    assert text.bullet_char("圆点") == "·"
    assert text.heading_mark(1) == "一、"
    assert text.heading_mark(3) == "1. "
    assert text.LINE_WIDTH == 76  # ≈ 38 个汉字，最舒服的阅读宽度
    assert text.resolve_text_layout("日志")["width"] == 0  # 日志不折行


# ---------------------------------------------------------------- 版式技能
@pytest.mark.parametrize("slug", LAYOUT_SKILLS)
def test_layout_skills_are_complete(slug: str) -> None:
    """四份版式技能：有 frontmatter、有正文、有自检清单，而且技能库里也有一份。"""
    for root in (SKILLS, CATALOG):
        path = root / slug / "SKILL.md"
        assert path.is_file(), f"{root.name}/{slug} 不存在"
        body = path.read_text(encoding="utf-8")
        assert body.startswith("---"), f"{slug} 缺 frontmatter"
        assert f"name: {slug}" in body
        assert "triggers:" in body
        assert "交付前自检" in body, f"{slug} 少了交付前自检"
        assert len(body) > 1500, f"{slug} 太薄，像是占位"


def test_layout_skills_point_at_the_lexicons() -> None:
    """技能只写规则，词表指向 lexicon——两边各写一套迟早对不上。"""
    assert "doc_lexicon" in (SKILLS / "doc-layout" / "SKILL.md").read_text(encoding="utf-8")
    assert "slide_lexicon" in (SKILLS / "ppt-layout" / "SKILL.md").read_text(encoding="utf-8")
    assert "sheet_lexicon" in (SKILLS / "sheet-layout" / "SKILL.md").read_text(encoding="utf-8")
    assert "text_lexicon" in (SKILLS / "text-layout" / "SKILL.md").read_text(encoding="utf-8")
