"""素材分块 / 检索 / 落地校验（RAG 层）单元测试。

这一层是「降幻觉」的实际承载，三件事各自对应一类失败：

- 分块：块切错，检索再怎么准也只能取回似是而非的上下文；
- 覆盖度：「素材里没有」不能被答成「没有」以外的任何东西——这是最容易被忽略的一档；
- 数字回查：编造的数字是唯一能机器判定的那类幻觉，漏检就等于没做。
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.domain.entities import UploadInfo
from app.domain.rag import (
    MAX_BLOCK_CHARS,
    Index,
    format_passages,
    match_level,
    outline,
    pack_blocks,
    split_blocks,
    unsupported_facts,
)
from app.infra.storage import LocalFileStorage
from app.tools.builtin.file import read_files, search_material
from app.tools.spec import ToolContext

REPORT = """一、经营概况

四季度整体营收 1,240 万元，环比增长 8.3%。增长主要来自华东区新客，占比 41%。

二、关键结论

退款率从 1.8% 降到 1.2%，主要来自售后流程自动化。客服响应时长中位数 42 秒，比上季度快 11 秒。

2.1 库存

库存周转 6.2 次，仍低于目标 7.0 次。华南仓的滞销品占比 12%。

三、下一步

补齐复购口径，避免与 GMV 重复计数。试点区域仓配，先做杭州与成都两个城市。
"""

SOURCES = [{"filename": "2026Q3复盘.docx", "text": REPORT}]


# ---------------------------------------------------------------- 分块


def test_each_section_becomes_its_own_block():
    blocks = split_blocks(SOURCES)
    assert [block.heading for block in blocks] == ["经营概况", "关键结论", "库存", "下一步"]


def test_multi_level_numbering_is_stripped_whole():
    """「2.1 库存」要剥成「库存」；只吃掉 `2.` 会留下「1 库存」这个假章节号。"""
    blocks = split_blocks(SOURCES)
    assert blocks[2].heading == "库存"
    assert not blocks[2].heading.startswith("1")


def test_block_ids_are_continuous():
    """编号同时是引用（[S3]）和补读坐标（block_ids），中间断号会让人翻不到。"""
    blocks = split_blocks(SOURCES)
    assert [block.id for block in blocks] == [f"S{i}" for i in range(1, len(blocks) + 1)]


def test_short_paragraphs_in_one_section_merge():
    text = "一、背景\n\n短句一。\n\n短句二。"
    blocks = split_blocks([{"filename": "a.docx", "text": text}])
    assert len(blocks) == 1
    assert "短句一" in blocks[0].text
    assert "短句二" in blocks[0].text


def test_short_blocks_never_merge_across_sections():
    """跨小节并块会让「库存」里混进「下一步」的内容，检索命中后上下文就是错的。"""
    text = "一、库存\n\n周转 6 次。\n\n二、下一步\n\n补口径。"
    blocks = split_blocks([{"filename": "a.docx", "text": text}])
    assert [block.heading for block in blocks] == ["库存", "下一步"]
    assert "补口径" not in blocks[0].text


def test_overlong_paragraph_is_split_into_bounded_blocks():
    text = "一、正文\n\n" + "本季度进展顺利。" * 400
    blocks = split_blocks([{"filename": "长文.docx", "text": text}])
    assert len(blocks) > 1
    # 允许一点超出（按句切分不会正好卡在 max_chars 上），但不能整段不分
    assert all(block.chars <= MAX_BLOCK_CHARS * 1.2 for block in blocks)


def test_blank_material_produces_no_blocks():
    assert split_blocks([{"filename": "空.docx", "text": "   \n\n "}]) == []
    assert split_blocks([]) == []


# ---------------------------------------------------------------- 检索


def test_search_finds_the_section_that_holds_the_fact():
    index = Index(split_blocks(SOURCES))
    top = index.search("退款率降到多少", 1)[0]
    assert top.block.heading == "关键结论"
    assert "1.2%" in top.block.text


def test_search_follows_a_followup_question_to_another_section():
    index = Index(split_blocks(SOURCES))
    assert index.search("复购口径怎么补", 1)[0].block.heading == "下一步"


def test_missing_topic_is_none_not_a_best_guess():
    index = Index(split_blocks(SOURCES))
    assert match_level(index.search("员工人数有多少", 3)) == "none"


def test_coverage_is_not_diluted_by_bigram_noise():
    """「复购口径」会切出「径补」这类跨词噪声；它不在索引里，不该拉低覆盖度。"""
    index = Index(split_blocks(SOURCES))
    top = index.search("复购口径怎么补", 1)[0]
    assert top.coverage == 1.0


def test_partially_unknown_query_is_not_reported_as_strong():
    """问的事情素材里只写了一半，不能给 strong——那是在替模型担保。"""
    index = Index(split_blocks(SOURCES))
    hits = index.search("营收和员工餐补", 3)
    assert hits, "「营收」确实在素材里，应该能命中一块"
    assert match_level(hits) == "weak"
    assert hits[0].coverage == 1.0
    assert hits[0].support < 0.5


def test_empty_index_never_matches():
    assert Index([]).search("随便问点什么") == []


def test_format_passages_carries_ids_and_filenames():
    index = Index(split_blocks(SOURCES))
    text = format_passages(index.search("退款率", 1), len(index), "strong")
    assert "[S2]" in text
    assert "2026Q3复盘.docx" in text
    assert "检索到 1 段" in text


def test_outline_lists_every_block():
    blocks = split_blocks(SOURCES)
    text = outline(blocks)
    assert all(block.id in text for block in blocks)
    assert "《2026Q3复盘.docx》共 4 块" in text


def test_pack_blocks_stops_at_budget():
    blocks = split_blocks(SOURCES)
    _, used = pack_blocks(blocks, 60)
    assert used == 1


# 真实材料回归集。阈值一改就可能悄悄退化，所以把「该 strong / 该 weak / 该 none」
# 三类各钉几个例子。素材来自一份真实味儿的项目复盘，不是为测试造的短句——
# 短句里词与词挨得紧，bigram 噪声少，测不出真实文档上的分档漂移。
REAL_DOC = """一、项目背景

本项目于 2026 年 3 月启动，目标是把分散在三个业务线的售后流程统一到一套工单系统。
立项时预估覆盖 1200 名一线客服，实际到三季度末接入 980 人，完成率约 82%。

二、进展与问题

2.1 已完成

工单系统已完成全量上线，平均建单时长从 3 分 20 秒降到 48 秒。知识库迁移完成 1.6 万条问答对，
其中 3200 条由业务专家重新标注。质检覆盖率从 5% 提升到 18%，抽检不合格率 2.4%。

2.2 遇到的问题

华南区的网络专线在高峰期出现 4 次中断，每次影响约 300 单。第三方短信通道的到达率
在国庆期间掉到 71%，导致验证码类工单积压 1600 单。客服对新的折叠菜单接受度不高，
调研中 43% 的受访者希望保留旧版入口。

三、成本与收益

系统年化运维成本 86 万元，其中云资源 52 万元、专线 18 万元、人力 16 万元。
按每次工单处理成本从 4.2 元降到 2.8 元测算，年化节省约 310 万元。

四、下一步计划

四季度重点做三件事：补齐华南区双线路冗余，预算 24 万元；把质检模型换成
线上版本，预计不合格率再降 0.8 个百分点；试点语音工单自动归类，先在成都和西安两个职场。

五、风险提示

合规方面需在 12 月前完成个人信息处理的二次评估。若延迟，2027 年一季度的语音工单
试点可能要往后推一个月。
"""

# (问题, 期望档位, 命中的小节)
CASEBOOK = [
    ("客服接入多少人", "strong", "项目背景"),
    ("建单时长降了多少", "strong", "已完成"),
    ("华南区网络中断几次", "strong", "遇到的问题"),
    ("短信到达率多少", "strong", "遇到的问题"),
    ("年化运维成本多少", "strong", "成本与收益"),
    ("四季度要做哪三件事", "strong", "下一步计划"),
    ("质检模型什么时候换", "strong", "下一步计划"),
    # 素材写的是「12 月前」，没写「截止日期」——降一档让人核对，但别判成没有
    ("合规评估的截止时间", "weak", "风险提示"),
    # 概述类提问词少又泛，support 天然低；素材里全都有，绝不能判 none
    ("帮我看看这个项目整体怎么样", "weak", "项目背景"),
    ("这个项目赚了多少钱", "weak", "项目背景"),
    # 素材确实没写，正确答案就是「没提」，不要给一段沾边的
    ("退款率是多少", "none", None),
    ("员工人数有多少", "none", None),
]


def test_real_document_casebook_keeps_its_grades():
    index = Index(split_blocks([{"filename": "售后项目中期复盘.docx", "text": REAL_DOC}]))
    for question, level, heading in CASEBOOK:
        hits = index.search(question, 3)
        assert match_level(hits) == level, f"{question} 的档位变了"
        if heading:
            assert hits[0].block.heading == heading, f"{question} 命中了别的小节"


# ---------------------------------------------------------------- 数字回查


def test_invented_numbers_are_flagged():
    missing = unsupported_facts("退款率降到 1.2%，库存周转 7.8 次，新客占比 55%。", SOURCES)
    assert {item["value"] for item in missing} == {"7.8", "55"}


def test_equivalent_number_forms_are_not_flagged():
    """1,240 与 1240、1.20 与 1.2 是同一个数——误报会把正常交付打回。"""
    assert unsupported_facts("营收 1240 万元，占比 41%。", SOURCES) == []
    assert unsupported_facts("退款率 1.20%，环比 8.30%。", SOURCES) == []


def test_line_numbering_is_not_treated_as_a_fact():
    assert unsupported_facts("1. 关键结论\n2. 下一步", SOURCES) == []


def test_no_material_means_no_verdict():
    """没有素材时无从比对，不能把每个数字都报成编造。"""
    assert unsupported_facts("营收 9999 万元", []) == []


# ---------------------------------------------------------------- 工具层


def _ctx_with(tmp_path: Path, files: dict[str, str]) -> ToolContext:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        artifact_dir=str(tmp_path / "artifacts"),
        upload_dir=str(tmp_path / "uploads"),
    )
    settings.ensure_dirs()
    uploads: list[UploadInfo] = []
    for index, (name, text) in enumerate(files.items()):
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        uploads.append(
            UploadInfo(
                artifact_id=f"art_{index}",
                filename=name,
                path=str(path),
                ext=Path(name).suffix,
                chars=len(text),
                text_path=str(path),
            )
        )
    return ToolContext(
        thread_id="th_1",
        run_id="run_1",
        trace_id="tr_1",
        settings=settings,
        artifacts=None,  # type: ignore[arg-type]
        storage=LocalFileStorage(settings),
        uploads=uploads,
    )


def _ctx(tmp_path: Path, text: str) -> ToolContext:
    return _ctx_with(tmp_path, {"复盘.txt": text})


def test_file_search_returns_cited_passages(tmp_path: Path):
    result = search_material(_ctx(tmp_path, REPORT), "退款率降到多少")
    assert result["match"] == "strong"
    assert "[S2]" in result["_passages"]
    assert result["hits"][0]["heading"] == "关键结论"


def test_file_search_says_none_instead_of_offering_noise(tmp_path: Path):
    """检索不到时宁可不给片段：几段「沾边」的文字比空手回去更容易被当成依据。"""
    result = search_material(_ctx(tmp_path, REPORT), "员工人数")
    assert result["match"] == "none"
    assert result["_passages"] == ""
    assert "不要凭印象补" in result["_summary"]
    # 至少要告诉它素材里有哪些小节，好换个词再查
    assert "经营概况" in result["_summary"]


def test_file_search_reuses_one_index_across_calls(tmp_path: Path):
    ctx = _ctx(tmp_path, REPORT)
    search_material(ctx, "退款率")
    first = ctx.rag_index
    search_material(ctx, "库存周转")
    assert ctx.rag_index is first


def test_search_sees_files_that_were_not_read_last_time(tmp_path: Path):
    """上一轮只读了 A，这次不带 files 检索，不能只在 A 里找还把 B 漏掉。"""
    ctx = _ctx_with(
        tmp_path,
        {
            "进度.txt": "一、进度\n\n本周完成联调。",
            "预算.txt": "一、预算\n\n退款率降到 1.2%。",
        },
    )
    read_files(ctx, files=["进度.txt"])
    result = search_material(ctx, "退款率")
    assert result["match"] != "none"
    assert "预算.txt" in result["_passages"]


def test_file_read_hands_back_an_outline_when_too_long(tmp_path: Path):
    """超长时给目录 + 前若干块 + 「还剩几块」，模型才知道自己没读完。"""
    long_text = "\n\n".join(f"第 {i} 段" + "本季度进展顺利。" * 40 for i in range(300))
    result = read_files(_ctx(tmp_path, long_text))
    assert result["truncated"] is True
    assert result["remaining_blocks"] > 0
    assert "分节目录" in result["_material"]
    assert "file_search" in result["_material"]
    assert result["chars"] > result["injected_blocks"] * 100


def test_file_read_can_fetch_exact_blocks(tmp_path: Path):
    ctx = _ctx(tmp_path, REPORT)
    read_files(ctx)
    picked = read_files(ctx, block_ids=["S2"])
    assert picked["injected_blocks"] == 1
    assert "关键结论" in picked["_material"]
    assert picked["truncated"] is True


def test_file_read_says_so_when_nothing_is_readable(tmp_path: Path):
    """拖进来的是压缩包 / 未知格式：读不到字就直说，别回一句「共 0 字」让模型自己猜。"""
    ctx = _ctx_with(tmp_path, {"投标材料.zip": ""})
    result = read_files(ctx)
    assert result["readable"] == 0
    assert result["chars"] == 0
    assert "投标材料.zip" in result["_summary"]
    assert "没有可读文字" in result["_summary"]
    assert ctx.material_text == ""


def test_full_material_stays_available_for_report_generation(tmp_path: Path):
    """注入给模型的是裁剪版，但 ctx.material_text 必须是全文——产物要靠它抽句子。"""
    ctx = _ctx(tmp_path, REPORT)
    read_files(ctx)
    assert ctx.material_text.count("库存周转") == 1
    assert "三、下一步" in ctx.material_text
