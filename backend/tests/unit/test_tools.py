"""工具注册表 / 子智能体 / 技能 / 文档小节抽取 单元测试。"""

from __future__ import annotations

from pathlib import Path

from app.agents.runtime import load_skills
from app.core.config import Settings
from app.domain.entities import Artifact
from app.infra.storage import LocalFileStorage
from app.subagents.registry import REGISTRY as SUBAGENTS
from app.tools.builtin.doc import (
    _build_sections,
    _data_points,
    _split_sections,
    _strip_source_notes,
    doc_title_for,
    generate_report,
)
from app.tools.registry import REGISTRY, build_schema
from app.tools.spec import ToolContext
from docx import Document

BASE_TOOLS = {
    "file.list",
    "file.read",
    "file.search",
    "file.delete",
    "doc.analyze_material",
    "doc.generate_report",
    "code.run_python",
    "todo.write",
    "todo.list",
}

# 高风险工具：执行前需人工审批
HIGH_RISK_TOOLS = {"doc.generate_report", "file.delete", "code.run_python"}


def test_base_tools_registered_with_risk():
    assert set(REGISTRY.names()) >= BASE_TOOLS
    assert REGISTRY.get("doc.generate_report") is not None
    assert REGISTRY.get("doc.generate_report").risk.value == "high"
    assert REGISTRY.get("file.read").risk.value == "low"
    assert REGISTRY.get("file.delete").risk.value == "high"


def test_analyze_material_is_read_only_so_no_approval():
    """素材体检只读、不写盘，不该每次都拦一道审批。"""
    spec = REGISTRY.get("doc.analyze_material")
    assert spec is not None
    assert spec.risk.value == "low"
    assert spec.requires_approval_default is False


def test_high_risk_tools_require_approval_by_default():
    """高风险工具的 requires_approval_default 必须为 True。"""
    for name in HIGH_RISK_TOOLS:
        spec = REGISTRY.get(name)
        assert spec is not None, f"{name} 未注册"
        assert spec.requires_approval_default is True, f"{name} 应默认需要审批"


def test_add_tool_without_touching_core():
    def echo(ctx, text: str, times: int = 1) -> dict:
        return {"text": text * times, "_summary": "已回显"}

    REGISTRY.register("test.echo", "回显文本（扩展点测试）", risk="low")(echo)
    try:
        spec = REGISTRY.get("test.echo")
        assert spec is not None
        properties = spec.schema["properties"]
        assert properties["text"] == {"type": "string"}
        assert properties["times"]["type"] == "integer"
        assert spec.schema["required"] == ["text"]
        assert "ctx" not in properties
    finally:
        REGISTRY.remove("test.echo")
    assert "test.echo" not in REGISTRY.names()


def test_schema_infers_types_from_future_annotations():
    def sample(ctx, text: str, count: int, flag: bool = False) -> dict:
        return {}

    schema = build_schema(sample)
    assert schema["properties"]["count"]["type"] == "integer"
    assert schema["properties"]["flag"]["type"] == "boolean"
    assert schema["required"] == ["text", "count"]


def test_approval_rules_intersect_high_risk():
    assert REGISTRY.approval_tools({"doc.generate_report"}) == ["doc.generate_report"]
    assert REGISTRY.approval_tools({"file.read"}) == []
    assert REGISTRY.approval_tools(set()) == []


def test_subagents_one_impl_two_placeholders():
    names = {spec.name: spec for spec in SUBAGENTS.all()}
    assert names["doc_agent"].status == "implemented"
    assert names["doc_agent"].tools == ["file.read", "doc.generate_report"]
    for name in ("sheet_agent", "research_agent"):
        assert names[name].status == "placeholder"
        assert names[name].tools == []


def test_skills_loaded_with_frontmatter():
    skills = load_skills()
    assert "weekly-report" in skills
    skill = skills["weekly-report"]
    assert skill.enabled is True
    assert "周报" in skill.triggers
    # 骨架改成「结论先行」那一套之后，技能里第一句要交代的就是这句话怎么写
    assert "一句话结论" in skill.content


# ---------- 文档小节抽取 ----------
WEEKLY = """会议记录
时间：2026-10-20 14:00
参会人员：张三、李四
一、本周进展
工作台原型完成三栏布局与 SSE 流式渲染。
Agent 主链路联调通过，覆盖 12 个接口。
二、关键数据
周报生成耗时 1.1 秒，DOCX 平均 37KB。
三、风险与问题
前端在 1024px 以下右栏抽屉有闪烁风险。
四、下周计划
完成真实模型错误降级验证。"""


def sections(text: str, template: str = "weekly") -> dict[str, list[str]]:
    return {
        section["heading"]: section["paragraphs"]
        for section in _build_sections(
            template, text, [{"filename": "会议记录.docx", "text": text}], ""
        )
    }


def test_split_numbering_variants():
    variants = [
        WEEKLY,
        "1. 本周进展\n完成登录联调。\n2. 关键数据\n覆盖 12 个接口。\n3. 风险与问题\n延期 2 天。\n4. 下周计划\n完成压测。",
        "（一）本周进展\n完成登录联调。\n（二）关键数据\n覆盖 12 个接口。\n（三）风险与问题\n延期 2 天。\n（四）下周计划\n完成压测。",
        "## 一、本周进展\n完成登录联调。\n## 二、关键数据\n覆盖 12 个接口。\n## 三、风险与问题\n延期 2 天。\n## 四、下周计划\n完成压测。",
    ]
    for text in variants:
        parts, _preamble = _split_sections(text)
        assert {"progress", "data", "risk", "plan"} <= set(parts)
        assert "完成" in parts["progress"]


def test_weekly_sections_do_not_bleed():
    parsed = sections(WEEKLY)
    progress = parsed["本周进展"]
    plan = parsed["下周计划"]
    data = parsed["关键数据"]
    assert any("工作台原型" in line for line in progress)
    assert not any("完成真实模型错误降级验证" in line for line in progress)
    assert any("完成真实模型错误降级验证" in line for line in plan)
    assert not any("工作台原型" in line for line in plan)
    assert any("37KB" in line for line in data)
    assert not any("时间" in line or "参会" in line for line in data)


def test_summary_uses_first_two_progress_sentences():
    summary = sections(WEEKLY)["摘要"][0]
    assert "工作台原型" in summary
    assert "Agent 主链路" in summary
    assert "真实模型错误降级验证" not in summary
    assert "。；" not in summary


def test_meeting_sections():
    text = (
        "会议纪要\n时间：2026-10-20\n一、议题与讨论\n讨论周报模板与审批流程。\n"
        "二、结论与待办\n下周一评审周报模板。"
    )
    parsed = sections(text, "meeting")
    assert any("周报模板" in line for line in parsed["议题与讨论"])
    assert not any("下周一评审" in line for line in parsed["议题与讨论"])
    assert any("下周一评审" in line for line in parsed["结论与待办"])


def test_no_headings_keeps_global_fallback():
    text = "本周完成登录联调，覆盖 12 个接口。\n风险：支付延期 2 天。\n下周计划完成压测。"
    assert _split_sections(text)[0] == {}
    parsed = sections(text)
    assert any("登录联调" in line for line in parsed["本周进展"])
    assert any("支付延期" in line for line in parsed["风险与问题"])
    assert any("压测" in line for line in parsed["下周计划"])


def test_sections_follow_the_material_not_the_template():
    """素材自己分了小节，就照它的标题与顺序排——不换成模板词。

    以前「二、退款率复盘」会被归成「关键数据」，用户在自己的文档里找不到自己写的那节。
    """
    text = (
        "退款率复盘\n"
        "一、这周做了什么\n把退款率口径从支付时间改成下单时间，覆盖 3 个渠道。\n"
        "二、退款率复盘\n口径切换后一周 1.2%，比原来的 1.5% 低。\n"
        "三、附：联系人\n财务张三负责对账，产品李四负责口径。\n"
    )
    parsed = sections(text)

    assert "这周做了什么" in parsed
    assert "退款率复盘" in parsed
    assert "附：联系人" in parsed  # 词表里没有的中文序号小节也认
    # 模板词不该出现：这些话素材里没有
    assert "本周进展" not in parsed
    assert "关键数据" not in parsed


def test_missing_section_is_not_fabricated():
    """素材没写风险就不出现「风险与问题」，也不写一句「素材里没有」。"""
    text = "一、本周进展\n完成登录联调，覆盖 12 个接口。"
    parsed = sections(text)

    assert "风险与问题" not in parsed
    assert "下周计划" not in parsed
    assert not any("素材里没有" in line for lines in parsed.values() for line in lines)


def test_title_comes_from_the_material_first_line():
    """素材首行是标题就用它；首行是栏目行或通用词时退回「素材名 · 类型」。"""
    from app.tools.builtin.doc import title_from_material

    sources = [{"filename": "素材.docx"}]
    assert title_from_material(
        "summary", sources, "退款率复盘\n一、口径\n改成下单时间。"
    ).startswith("退款率复盘 · ")
    # 首行是栏目行 → 不是标题
    assert title_from_material(
        "meeting", sources, "时间：2026-11-07\n一、议题\n讨论模板。"
    ).startswith("素材 · ")
    # 首行是通用词「工作周报」→ 没有信息量，退回素材名
    assert title_from_material("weekly", sources, "工作周报\n一、进展\n联调完成。").startswith(
        "素材 · "
    )


def test_data_points_skip_headers():
    assert _data_points("时间：2030-01-01 14:00\n参会人员：3 人\n周报耗时 1.1 秒。") == [
        "周报耗时 1.1 秒。"
    ]


def test_data_points_skip_figure_captions():
    """图注里的数字不是「关键数据」，别再出现「图1 杉道晴光」这种条目。"""
    assert _data_points("图1 杉道晴光\n【素材.docx】\n2026 年 10 月完成 3 个需求。") == [
        "2026 年 10 月完成 3 个需求。"
    ]


def test_script_facts_go_into_data_section():
    facts = {
        "totals": {"files": 1, "paragraphs": 7, "chars": 742, "images": 2, "tables": 1},
        "files": [{"figures": ["图1 杉道晴光", "图2 檐下望秋"]}],
    }
    parsed = {
        section["heading"]: section["paragraphs"]
        for section in _build_sections(
            "weekly", WEEKLY, [{"filename": "周报.docx", "text": WEEKLY}], "", facts
        )
    }
    data = parsed["关键数据"]
    assert any("742" in line and "7 段" in line for line in data)
    assert any("内嵌图片 2 张" in line for line in data)
    assert any("图1 杉道晴光" in line for line in data)
    # 真实数据排在前面，正文里的数字点跟在后面
    assert "742" in data[0]


def test_summary_template_uses_original_text_not_defaults():
    essay = "走观秋\n图1 杉道晴光\n秋日午后，我取完快递往回走，路旁的水杉不知什么时候就黄了。阳光从枝桠间漏下来。"
    parsed = {
        section["heading"]: section["paragraphs"]
        for section in _build_sections(
            "summary", essay, [{"filename": "走观秋.docx", "text": essay}], ""
        )
    }
    assert "水杉" in parsed["摘要"][0]
    assert "本周进展" not in parsed
    assert "完成了本周既定任务的梳理与交付" not in "\n".join(
        line for lines in parsed.values() for line in lines
    )


def test_todo_write_empty_plan_is_not_error():
    from types import SimpleNamespace

    ctx = SimpleNamespace(todos=[{"id": "t1", "content": "x", "status": "pending"}])
    result = REGISTRY.get("todo.write").handler(ctx, [])
    assert result["ok"] is True
    assert result["_summary"] == "计划为空，已忽略"
    assert result["todos"] == ctx.todos


# ---------- 产物文件名：同一天多份也得一眼分得清 ----------


class _ArtifactRepo:
    def __init__(self) -> None:
        self.items: list[Artifact] = []

    def add(self, artifact: Artifact) -> Artifact:
        self.items.append(artifact)
        return artifact


def _doc_context(tmp_path: Path, text: str, sources: list[str]) -> ToolContext:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        artifact_dir=str(tmp_path / "artifacts"),
        upload_dir=str(tmp_path / "uploads"),
    )
    settings.ensure_dirs()
    return ToolContext(
        thread_id="th_1",
        run_id="run_1",
        trace_id="tr_1",
        settings=settings,
        artifacts=_ArtifactRepo(),  # type: ignore[arg-type]
        storage=LocalFileStorage(settings),
        material_text=text,
        material_sources=[{"filename": name, "text": text} for name in sources],
    )


ESSAY = "走观秋\n秋日午后，路旁的水杉不知什么时候就黄了。\n图1 杉道晴光"


def test_report_numbering_follows_the_document_type(tmp_path: Path) -> None:
    """标题写着「周报」就按周报排（一、），写着「技术方案」就按方案排（1.1.1）。

    编号是唯一一个「按文档类型换」的维度：判错一档，代价只是编号款式不对，
    字号行距不受影响——所以它敢从标题里猜，猜错了也不至于毁掉整份稿子。
    """
    body = "## 本周概况\n\n正文。\n\n### 采集节点\n\n正文。\n"
    cases = (
        ("W46 周报", ["一、本周概况", "（一）采集节点"]),
        ("支付技术方案", ["1. 本周概况", "1.1 采集节点"]),
        ("会议纪要", ["本周概况", "采集节点"]),
    )
    for index, (title, expected) in enumerate(cases):
        root = tmp_path / f"num{index}"
        root.mkdir(parents=True, exist_ok=True)
        ctx = _doc_context(root, "素材正文", ["素材.docx"])
        result = generate_report(ctx, title=title, body=body, format="docx")
        headings = [
            p.text
            for p in Document(result["path"]).paragraphs
            if p.style.name.startswith("Heading") and p.text.strip()
        ]
        assert headings == expected, title


def test_other_formats_keep_the_material_structure(tmp_path: Path):
    """txt / pptx / xlsx 走的是同一份 sections：素材小节名换了，三种产物一起换。"""
    ctx = _doc_context(tmp_path, REFUND, ["退款率复盘.docx"])
    generate_report(ctx, template="weekly", format="txt")

    path = Path(ctx.artifacts.items[0].path)  # type: ignore[attr-defined]
    text = path.read_text(encoding="utf-8")
    # 纯文本用【】分层，标记来自 text_lexicon
    assert "【这周做了什么】" in text
    assert "【退款率复盘】" in text
    assert "【本周进展】" not in text

    from app.services import pptx_utils

    ctx2 = _doc_context(tmp_path, REFUND, ["退款率复盘.docx"])
    generate_report(ctx2, template="weekly", format="pptx")
    pages = pptx_utils.extract_slides(Path(ctx2.artifacts.items[0].path))  # type: ignore[attr-defined]
    titles = [page["title"] for page in pages]
    assert "这周做了什么" in titles
    assert "本周进展" not in titles


REFUND = (
    "退款率复盘\n"
    "一、这周做了什么\n把退款率口径从支付时间改成下单时间，覆盖 3 个渠道。\n"
    "二、退款率复盘\n口径切换后一周 1.2%，比原来的 1.5% 低。\n"
)


def test_no_material_leaves_a_clean_skeleton(tmp_path: Path):
    """没素材时给干净的空架子，不是每节各写一句「素材里没有…」。"""
    ctx = _doc_context(tmp_path, "", [])
    generate_report(ctx)

    document = Document(ctx.artifacts.items[0].path)  # type: ignore[attr-defined]
    texts = [paragraph.text for paragraph in document.paragraphs]
    assert not any("素材里没有" in text for text in texts)
    # 标题下面一行说明「这是框架、等素材」，比正文里五句「没有」有用
    assert any("待补素材" in text for text in texts)
    assert any("摘要" in text for text in texts)


def test_body_markdown_decides_the_structure(tmp_path: Path):
    """给了 body 就按它排版：标题层级、表格、列表都如实还原，不再套六节骨架。"""
    ctx = _doc_context(tmp_path, ESSAY, ["随笔.docx"])
    body = (
        "## 一句话结论\n这周的活干完了。\n\n"
        "## 进度\n\n| 事项 | 结果 |\n|---|---|\n| 联调 | 完成 |\n\n"
        "## 风险与问题\n1. 接口总数未提供。\n"
    )
    generate_report(ctx, body=body)

    document = Document(ctx.artifacts.items[0].path)  # type: ignore[attr-defined]
    texts = [paragraph.text for paragraph in document.paragraphs]
    assert "一、一句话结论" in texts
    assert "二、进度" in texts
    assert len(document.tables) == 1
    # 骨架里的「本周进展」「关键数据」不该再出现
    assert not any("关键数据" in text for text in texts)


def test_artifact_filename_carries_source_name(tmp_path: Path):
    """文件名以素材名打头：同一天生成两份摘要，靠名字就能分清哪份对哪份。"""
    first = generate_report(_doc_context(tmp_path, ESSAY, ["随笔.docx"]), template="summary")
    second = generate_report(_doc_context(tmp_path, ESSAY, ["周记.docx"]), template="summary")

    assert "随笔" in first["filename"]
    assert "周记" in second["filename"]
    assert first["filename"] != second["filename"]
    # 形如 随笔_文件摘要_2026-10-26.docx：素材名排在最前，
    # 右栏窄、文件名从尾部截断时，区分两份产物的那几个字不会被切掉
    assert first["filename"].split("_")[:2] == ["随笔", "文件摘要"]


def test_source_name_drops_date_tail_and_keeps_brackets_whole(tmp_path: Path):
    """素材名末尾的日期去掉；截断时不把括号切成「（智慧能源」那种半截。"""
    ctx = _doc_context(tmp_path, ESSAY, ["24级软件工程（智慧能源）2026-10-26.docx"])
    result = generate_report(ctx, template="summary")
    artifact = ctx.artifacts.items[0]  # type: ignore[attr-defined]

    assert result["filename"].startswith("24级软件工程（智慧能源）_文件摘要_")
    assert artifact.filename == result["filename"]


def test_doc_title_uses_source_name():
    """文档标题也带素材名，不再是千人一面的「素材摘要（日期）」。"""
    assert doc_title_for("summary", [{"filename": "随笔.docx"}]) == "随笔 · 文件摘要"
    # 没有素材时才退回「类型（日期）」
    assert doc_title_for("summary", []).startswith("文件摘要（")
    assert doc_title_for("weekly", [{"filename": "周报.docx"}]).startswith("周报 · 工作周报（")


def test_artifact_filename_dedupes_with_number(tmp_path: Path):
    """同一份素材同一天再生成一次：第二名用 (2)，不用随机串。"""
    ctx = _doc_context(tmp_path, ESSAY, ["随笔.docx"])
    first = generate_report(ctx, template="summary")
    ctx2 = _doc_context(tmp_path, ESSAY, ["随笔.docx"])
    ctx2.storage = ctx.storage  # 同一个产物目录
    second = generate_report(ctx2, template="summary")

    assert first["filename"] != second["filename"]
    assert "(2).docx" in second["filename"]


def test_artifact_records_sources_for_right_panel(tmp_path: Path):
    """产物 extra 里留素材来源：右栏提示要说明「这份从哪来」。"""
    ctx = _doc_context(tmp_path, ESSAY, ["随笔.docx", "周记.docx"])
    generate_report(ctx, template="summary")
    artifact = ctx.artifacts.items[0]  # type: ignore[attr-defined]

    assert artifact.extra["sources"] == ["随笔.docx", "周记.docx"]
    assert "等2份" in artifact.filename


# ---------- 文件摘要：按结构成文，不再「取前两句」 ----------

ESSAY_FULL = (
    "走观秋\n"
    "照片《杉道晴光》感悟\n"
    "图1 杉道晴光\n"
    "秋日午后，我取完快递往回走，无意间抬头，路旁的水杉不知什么时候就黄了。"
    "阳光从枝桠间漏下来，在路面洒下一片光影。其实不用特意去找，校园的秋天，走着走着就撞见了。\n"
    "照片《檐下望秋》感悟\n"
    "图2 檐下望秋\n"
    "下课铃一响，我无意间瞥见窗外，扇形的窗缝里露出一树金黄的叶子，亮得像一团暖光。"
    "恰逢单人独坐，我随之拿出手机拍摄。我在窗边站了一会儿，只觉得秋天这样，也挺好。"
)


def _summary_sections(text: str, names: list[str] | None = None) -> dict[str, list[str]]:
    sources = [{"filename": name, "text": text} for name in (names or ["走观秋.docx"])]
    return {
        section["heading"]: section["paragraphs"]
        for section in _build_sections("summary", text, sources, "")
    }


def test_summary_covers_every_figure_group_not_just_the_opening():
    """摘要要覆盖全文结构：以前取正文前两句，第二组照片与作者感受整段丢失。"""
    parsed = _summary_sections(ESSAY_FULL)
    overview = parsed["摘要"][0]
    assert "图1 杉道晴光" in overview
    assert "图2 檐下望秋" in overview
    assert "2 组" in overview
    assert "水杉" in overview and "金黄" in overview


def test_summary_points_follow_groups_and_do_not_repeat_the_overview():
    """要点按图注分组，取每组的落点句；同一句不能在摘要与要点里各出现一次。"""
    parsed = _summary_sections(ESSAY_FULL)
    overview = parsed["摘要"][0]
    points = parsed["要点"]
    assert len(points) == 2
    assert points[0].startswith("图1 杉道晴光：")
    assert points[1].startswith("图2 檐下望秋：")
    for point in points:
        body = point.split("：", 1)[1]
        assert body not in overview


def test_summary_has_no_source_citation_section():
    """成稿不再挂「来源引用」：那份出处清单是给写稿人核对的，读者用不到。

    用户 2026-11-09 明确要求去掉；同一份稿子传两次也不再需要「去重引用」的逻辑。
    """
    parsed = _summary_sections(ESSAY_FULL, ["走观秋.docx", "走观秋(2).docx"])
    assert "来源引用" not in parsed
    flat = "".join(text for paragraphs in parsed.values() for text in paragraphs)
    assert "第 1 段" not in flat and "走观秋.docx · " not in flat


def test_summary_structure_counts_deduped_paragraphs():
    """素材构成按去重后的真实结构计数，并说明重复了几份。"""
    parsed = _summary_sections(ESSAY_FULL, ["走观秋.docx", "走观秋(2).docx"])
    line = parsed["素材构成"][0]
    assert "素材 2 份" in line
    assert "1 份内容重复" in line
    assert "正文 2 段" in line
    assert "图注：图1 杉道晴光、图2 檐下望秋" in "".join(parsed["素材构成"])


def test_outline_from_model_overrides_extracted_summary(tmp_path: Path):
    """读过全文的模型给的摘要/要点优先，章节骨架仍由模板决定。"""
    ctx = _doc_context(tmp_path, ESSAY_FULL, ["走观秋.docx"])
    generate_report(
        ctx,
        template="summary",
        outline={"摘要": "这是一份校园秋景摄影随笔。", "要点": ["图1：午后水杉", "图2：窗外金黄"]},
    )
    document = Document(ctx.artifacts.items[0].path)  # type: ignore[attr-defined]
    texts = [paragraph.text for paragraph in document.paragraphs]
    assert "这是一份校园秋景摄影随笔。" in texts
    assert "图1：午后水杉" in texts
    # 成稿里不再有「来源引用」小节（一级标题会被自动编号，所以按包含判断）
    assert not any("来源引用" in text for text in texts)


def test_strip_source_notes_drops_citation_section_and_credit_line():
    """模型写的正文里带「来源引用」小节或「来源：…」落款时，成稿要摘干净。"""
    body = (
        "## 摘要\n\n这是一份校园秋景摄影随笔。\n\n"
        "## 来源引用\n\n走观秋.docx · 第 1 段：秋日午后……\n"
        "走观秋.docx · 第 2 段：下课铃一响……\n\n"
        "## 风险与问题\n\n- 时间戳对不上。\n\n"
        "来源：走观秋.docx（本周）\n"
    )
    cleaned = _strip_source_notes(body)
    assert "来源引用" not in cleaned
    assert "第 1 段" not in cleaned
    assert not cleaned.strip().endswith("）")
    # 正文与后面的小节都还在
    assert "这是一份校园秋景摄影随笔。" in cleaned
    assert "## 风险与问题" in cleaned and "时间戳对不上。" in cleaned


def test_strip_source_notes_drops_numbered_index_section_and_credit():
    """带编号的「关键文件索引」和「依据《x》整理」也要拦（用户 2026-11-10 点名）。"""
    body = (
        "## 一、总览\n\n一次请求走完的链路。\n\n"
        "## 六、关键文件索引\n\n"
        "- services/artifact_service.py：产物预览\n"
        "- infra/parsing.py：文本解析\n\n"
        "## 七、收尾\n\n结论写在这里。\n\n"
        "依据《后端三块核心源码提取.md》整理，代码位置沿用该文件的标注\n"
    )
    cleaned = _strip_source_notes(body)
    assert "关键文件索引" not in cleaned
    assert "artifact_service.py" not in cleaned
    assert "依据《" not in cleaned
    assert "一次请求走完的链路。" in cleaned
    assert "结论写在这里。" in cleaned


def test_strip_source_notes_keeps_sentences_that_mention_sources():
    """正文里顺带提到「来源」的句子不动——只删整节出处与落款行。"""
    body = "这一段的数据来源是车间台账，口径按月初统一。\n来源：车间台账.xlsx（本周）\n"
    cleaned = _strip_source_notes(body)
    assert "数据来源是车间台账" in cleaned
    assert not any(line.startswith("来源：") for line in cleaned.splitlines())


def test_summary_carries_source_photos_into_the_product(tmp_path: Path):
    """源文档里的照片要跟着摘要一起走：否则预览里只剩文字，与原件对不上。"""
    from PIL import Image

    photo = tmp_path / "shot.png"
    Image.new("RGB", (320, 200), (206, 184, 128)).save(photo)

    document = Document()
    document.add_heading("走观秋", level=0)
    document.add_paragraph("照片《杉道晴光》感悟", style="Heading 2")
    document.add_picture(str(photo))
    document.add_paragraph("图1 杉道晴光", style="Caption")
    document.add_paragraph("秋日午后，路旁的水杉不知什么时候就黄了。阳光从枝桠间漏下来。")
    source_path = tmp_path / "走观秋.docx"
    document.save(source_path)

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        artifact_dir=str(tmp_path / "artifacts"),
        upload_dir=str(tmp_path / "uploads"),
    )
    settings.ensure_dirs()
    ctx = ToolContext(
        thread_id="th_1",
        run_id="run_1",
        trace_id="tr_1",
        settings=settings,
        artifacts=_ArtifactRepo(),  # type: ignore[arg-type]
        storage=LocalFileStorage(settings),
        material_text="走观秋\n图1 杉道晴光\n秋日午后，路旁的水杉不知什么时候就黄了。",
        material_sources=[
            {
                "filename": "走观秋.docx",
                "text": "走观秋\n图1 杉道晴光\n水杉黄了。",
                "path": str(source_path),
            }
        ],
    )
    result = generate_report(ctx, template="summary")
    assert "图文对照" in result["sections"]

    produced = Document(ctx.artifacts.items[0].path)  # type: ignore[attr-defined]
    assert len(produced.inline_shapes) == 1
    texts = [paragraph.text for paragraph in produced.paragraphs]
    assert "图1 杉道晴光" in texts


def test_summary_ignores_material_header_lines():
    """file.read 拼进来的「【文件名】」不是文档标题，不能被写成《【…docx】》。"""
    parsed = _summary_sections("【走观秋.docx】\n" + ESSAY_FULL, ["走观秋.docx"])
    assert parsed["摘要"][0].startswith("《走观秋》")
    assert "【" not in parsed["摘要"][0]
