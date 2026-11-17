"""技能草稿单测：模型输出清洗 + 没模型时的本地骨架。

断言重点不是「模型写了什么」，而是「产物一定是一份能导入的 SKILL.md」——
所以最后都把 markdown 丢给真实的 SkillService.import_skill 跑一遍。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.services.skill_drafter import draft_skill
from app.services.skill_service import SkillService

from .test_skills_manage import make_service


class FakeRouter:
    def __init__(self, text: str = "", *, boom: bool = False) -> None:
        self.text = text
        self.boom = boom

    async def chat_with_tools(self, *args, **kwargs):
        if self.boom:
            raise RuntimeError("模拟网络故障")
        return SimpleNamespace(text=self.text, model="fake-model")


def ready_settings() -> SimpleNamespace:
    return SimpleNamespace(real_model_configured=True)


def draft(router: FakeRouter | None, idea: str, taken: set[str] | None = None, **kw) -> dict:
    return asyncio.run(
        draft_skill(router, kw.pop("settings", ready_settings()), idea, taken=taken or set(), **kw)
    )


def import_into(markdown: str, tmp_path: Path) -> list[dict]:
    """用真实导入路径落盘：证明产物确实是合法 SKILL.md。"""
    service = make_service(tmp_path)
    service.import_skill("SKILL.md", markdown.encode("utf-8"))
    return service.list_skills()


MODEL_OUTPUT = """```markdown
---
name: Meeting Minutes
title: 会议纪要小助手
description: 把速记压成结论和待办
triggers: [纪要, 会议记录，待办]
category: 会议协作
icon: minutes
---

# 怎么做

1. 先通读速记，标出每个议题
2. 每个议题写一句结论
3. 待办补齐责任人和时间

# 注意

- 不虚构参会人
```
"""


def test_model_output_is_cleaned_and_importable(tmp_path: Path) -> None:
    result = draft(FakeRouter(MODEL_OUTPUT), "把会议速记整理成纪要")

    # code fence 被剥掉，frontmatter 一定落在第一行
    assert result["markdown"].startswith("---\nname: ")
    assert "```" not in result["markdown"]
    assert result["source"] == "model"
    assert result["model"] == "fake-model"
    assert result["name"] == "meeting-minutes"  # 空格与大小写都被归一
    assert result["title"] == "会议纪要小助手"
    assert result["triggers"] == ["纪要", "会议记录", "待办"]

    skills = import_into(result["markdown"], tmp_path)
    assert [item["name"] for item in skills] == ["meeting-minutes"]
    assert skills[0]["category"] == "会议协作"
    assert skills[0]["icon"] == "minutes"
    assert skills[0]["enabled"] is True


def test_duplicate_name_gets_suffix(tmp_path: Path) -> None:
    result = draft(FakeRouter(MODEL_OUTPUT), "整理会议纪要", taken={"meeting-minutes"})
    assert result["name"] == "meeting-minutes-2"
    import_into(result["markdown"], tmp_path)


def test_missing_fields_are_backfilled(tmp_path: Path) -> None:
    # 模型只给了正文，frontmatter 全缺：仍然要能导入
    result = draft(FakeRouter("# 怎么做\n\n1. 读材料\n2. 写 300 字"), "写一份 300 字周报")
    assert result["source"] == "model"
    assert result["name"] == "写一份-300-字周报"
    assert result["title"]
    assert result["triggers"]

    skills = import_into(result["markdown"], tmp_path)
    assert len(skills) == 1


def test_illegal_icon_is_dropped_not_passed_through(tmp_path: Path) -> None:
    output = MODEL_OUTPUT.replace("icon: minutes", "icon: rocket")
    result = draft(FakeRouter(output), "整理会议纪要")
    assert "icon:" not in result["markdown"]
    import_into(result["markdown"], tmp_path)


def test_no_model_falls_back_to_local_bone(tmp_path: Path) -> None:
    result = draft(
        FakeRouter(MODEL_OUTPUT),
        "帮我做合同条款比对",
        settings=SimpleNamespace(real_model_configured=False),
    )
    assert result["source"] == "local"
    assert result["model"] == ""
    assert "合同条款比对" in result["markdown"]
    assert result["note"]

    skills = import_into(result["markdown"], tmp_path)
    assert len(skills) == 1


def test_model_error_and_empty_reply_both_degrade(tmp_path: Path) -> None:
    for index, router in enumerate((FakeRouter(boom=True), FakeRouter("   "))):
        result = draft(router, "整理发票信息")
        assert result["source"] == "local"
        import_into(result["markdown"], tmp_path / str(index))


def test_overlong_output_is_truncated(tmp_path: Path) -> None:
    output = MODEL_OUTPUT + ("很长的一段废话。" * 2000)
    result = draft(FakeRouter(output), "整理会议纪要")
    assert len(result["markdown"]) <= 8000
    import_into(result["markdown"], tmp_path)


@pytest.mark.parametrize("idea", ["写周报", "把表格按月份汇总", "做一份竞品对比"])
def test_ideas_keep_their_own_wording(idea: str, tmp_path: Path) -> None:
    result = draft(None, idea)
    # 没有 router 也必须能出草稿（前端在演示模式下同样可点）
    assert result["source"] == "local"
    assert idea in result["markdown"]
    service: SkillService = make_service(tmp_path)
    service.import_skill("SKILL.md", result["markdown"].encode("utf-8"))
    assert len(service.list_skills()) == 1
