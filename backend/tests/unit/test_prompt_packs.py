"""提示词包路由：把《Agent 提示词合集》按需求注入本轮 system prompt。

为什么要锁：提示词包一旦路由错，模型会拿「文档排版规范」去做表格清洗，或者把「比对规则」
当成改写指令。这里固定几组典型说法的命中结果，以及注入条数/上限这类边界。
"""

from __future__ import annotations

from app.services.prompt_packs import MAX_PACKS_PER_RUN, PromptPackService, load_packs

service = PromptPackService()


def test_all_seven_packs_are_loaded() -> None:
    ids = {pack.id for pack in load_packs()}
    assert ids == {
        "doc-decision",
        "frontend-review",
        "data-extract",
        "sheet-ops",
        "doc-diff",
        "batch-template",
        "info-digest",
    }
    listed = service.list_packs()
    assert len(listed) == 7
    assert all(item["chars"] > 100 for item in listed)
    # 正文一起返回：界面的「内置规范包」弹窗直接读它，不用再发一次请求
    assert all(len(item["body"]) == item["chars"] for item in listed)
    assert all(item["body"].startswith("#") for item in listed)


def test_routes_by_intent() -> None:
    cases = {
        "把这份材料整理成 600 字周报": "info-digest",
        "把文档排版美化一下，标题改成黑体三号": "doc-decision",
        "帮我清洗这个 excel 表格，按部门分组汇总": "sheet-ops",
        "帮我做一个前端代码评审，按评分表给结论": "frontend-review",
        "比对一下旧版和新版合同，输出差异清单": "doc-diff",
        "按模板批量生成 30 份通知书": "batch-template",
        "从这几份文件里提取字段，整合成一张表": "data-extract",
    }
    for message, expected in cases.items():
        picked = [pack.id for pack in service.select(message)]
        assert expected in picked, f"{message} -> {picked}"


def test_never_injects_more_than_two_packs() -> None:
    message = "把表格里的数据提取出来整理成周报，再和旧版比对差异，最后批量生成文档"
    picked = service.select(message)
    assert 1 <= len(picked) <= MAX_PACKS_PER_RUN


def test_render_wraps_with_header_and_skips_empty_message() -> None:
    assert service.render("   ") == ""

    rendered = service.render("把这份 docx 排版整理一下")
    assert rendered.startswith("# 本轮任务规范")
    assert "## " in rendered
    assert "多方案" in rendered


def test_render_has_char_budget() -> None:
    rendered = service.render("把表格数据提取出来，批量生成文档并比对差异")
    assert len(rendered) < 6000
