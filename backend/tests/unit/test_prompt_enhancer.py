"""提示词增强：模型可用时改写，不可用时按规则补全。

这个按钮就摆在输入框上，「点了报错」比「没有这个按钮」更糟，所以两条底线要在测试里钉住：
1. 任何失败（没配模型 / 超时 / 模型回了一句废话）都退回规则版，且 note 说清来源；
2. 规则版只补结构与约束，不替用户编内容。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from app.services.prompt_enhancer import (
    MAX_OUTPUT_CHARS,
    clean_enhanced,
    enhance_prompt,
    rule_based_prompt,
)


class FakeRouter:
    """只实现 enhancer 用到的 chat_with_tools。"""

    def __init__(self, text: str = "", model: str = "deepseek-chat", boom: bool = False):
        self.text = text
        self.model = model
        self.boom = boom
        self.calls: list[dict[str, object]] = []

    async def chat_with_tools(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        if self.boom:
            raise RuntimeError("网络断了")
        return SimpleNamespace(text=self.text, model=self.model)


def settings(real: bool = True) -> SimpleNamespace:
    return SimpleNamespace(real_model_configured=real)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- 本地规则
def test_rule_based_keeps_request_and_available_format():
    text = rule_based_prompt("把这份会议记录整理成周报", "docx")
    assert text.startswith("任务：把这份会议记录整理成周报")
    assert "输出格式：Word 文档（docx）" in text
    assert "不要编造" in text


def test_rule_based_picks_length_from_source():
    assert "约 600 字" in rule_based_prompt("整理成 600 字的周报")
    # 没写篇幅就别替用户拍一个数字
    assert "按内容长短自适应" in rule_based_prompt("整理成周报")


def test_rule_based_without_format_has_no_format_line():
    text = rule_based_prompt("整理成周报", None)
    assert "输出格式：" not in text
    assert "任务：整理成周报" in text


# ---------------------------------------------------------------- 输出清洗
def test_clean_strips_code_fence_and_prefix():
    raw = "```text\n以下是改写后的提示词：\n任务：整理周报\n要求：先结论后依据\n```"
    cleaned = clean_enhanced(raw)
    assert cleaned.startswith("任务：整理周报")
    assert "```" not in cleaned
    assert "以下是改写后的提示词" not in cleaned


def test_clean_strips_wrapping_quotes():
    raw = "「任务：把合同汇总成台账，输出 5 列，只用素材里的信息」"
    assert clean_enhanced(raw) == "任务：把合同汇总成台账，输出 5 列，只用素材里的信息"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "   ",
        "好的",  # 太短
        "抱歉，我无法完成这个改写",  # 在拒绝
        "请提供更详细的材料，我才能帮你改写",  # 在反问
    ],
)
def test_clean_rejects_unusable_output(raw: str):
    assert clean_enhanced(raw) == ""


def test_clean_truncates_long_output():
    cleaned = clean_enhanced("任务：" + "很长的描述" * 400)
    assert len(cleaned) == MAX_OUTPUT_CHARS + 1
    assert cleaned.endswith("…")


# ---------------------------------------------------------------- 两条来源
def test_no_model_falls_back_to_rules_with_note():
    result = run(
        enhance_prompt(FakeRouter(), settings(real=False), "整理成周报", output_format="xlsx")
    )
    assert result["source"] == "rules"
    assert result["model"] == ""
    assert "没有可用的模型" in result["note"]
    assert "Excel 表格（xlsx）" in result["text"]


def test_model_success_returns_model_text():
    router = FakeRouter(text="任务：把会议记录整理成 600 字周报\n要求：先结论后依据，只用素材信息")
    result = run(enhance_prompt(router, settings(), "整理成周报", output_format="docx"))
    assert result["source"] == "model"
    assert result["model"] == "deepseek-chat"
    assert result["note"] == ""
    assert result["text"].startswith("任务：")
    # 格式作为改写提示传给了模型
    user_message = router.calls[0]["messages"][1]["content"]
    assert "期望产物格式：Word 文档（docx）" in str(user_message)


def test_model_failure_falls_back_to_rules():
    router = FakeRouter(boom=True)
    result = run(enhance_prompt(router, settings(), "整理成周报"))
    assert result["source"] == "rules"
    assert "没调通" in result["note"]
    assert result["text"].startswith("任务：整理成周报")


def test_model_echoing_source_falls_back_to_rules():
    """模型原样退回原文等于没增强，不如给结构骨架。"""
    source = "整理成周报"
    result = run(enhance_prompt(FakeRouter(text=source), settings(), source))
    assert result["source"] == "rules"
    assert "不理想" in result["note"]


def test_blank_input_returns_empty_text():
    result = run(enhance_prompt(FakeRouter(), settings(), "   "))
    assert result["text"] == ""
    assert "先写一句需求" in result["note"]
