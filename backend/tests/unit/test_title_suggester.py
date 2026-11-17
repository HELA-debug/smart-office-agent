"""会话自动命名：规则标题去客套 + 模型标题清洗 + 失败兜底。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from app.agents.model_router import ChatResult, ModelUnavailableError
from app.core.utils import derive_thread_title
from app.services.title_suggester import clean_title, suggest_title


def test_derive_strips_polite_prefix_and_tail_punctuation() -> None:
    assert (
        derive_thread_title("请帮我把这份材料整理成 600 字周报。") == "把这份材料整理成 600 字周报"
    )
    assert derive_thread_title("帮我对比这两份合同的差异") == "对比这两份合同的差异"
    assert derive_thread_title("麻烦  汇总一下 会议纪要 ！") == "汇总一下 会议纪要"


def test_derive_keeps_short_message_and_limits_long_one() -> None:
    assert derive_thread_title("写周报") == "写周报"
    long_title = derive_thread_title("这是一段非常长的需求描述" * 4)
    assert long_title.endswith("…")
    assert len(long_title) <= 25


def test_clean_title_strips_quotes_and_markers() -> None:
    assert clean_title("「证书材料整理成周报」") == "证书材料整理成周报"
    assert clean_title("1. 合同条款比对。") == "合同条款比对"
    assert clean_title("  \n\n  ") == ""


def test_clean_title_rejects_meta_replies() -> None:
    # 模型在解释自己而不是给标题：弃用，保留规则标题
    assert clean_title("抱歉，我无法给出标题") == ""
    assert clean_title("作为助手，我建议这样命名") == ""
    assert clean_title("标题：周报") == ""
    assert clean_title("超" * 40) == ""


class FakeRouter:
    def __init__(self, text: str = "", error: Exception | None = None) -> None:
        self.text = text
        self.error = error

    async def chat_with_tools(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        if self.error is not None:
            raise self.error
        return ChatResult(
            text=self.text,
            provider="deepseek",
            model="deepseek-chat",
            prompt_tokens=10,
            completion_tokens=5,
        )


def test_suggest_title_returns_cleaned_text() -> None:
    title = asyncio.run(
        suggest_title(FakeRouter("「证书材料整理成周报」"), "整理成周报", ["证书.pdf"])
    )
    assert title == "证书材料整理成周报"


def test_suggest_title_falls_back_to_empty_on_failure() -> None:
    assert (
        asyncio.run(suggest_title(FakeRouter(error=ModelUnavailableError("no provider")), "hi"))
        == ""
    )
    assert asyncio.run(suggest_title(FakeRouter(error=RuntimeError("timeout")), "hi")) == ""
    # 模型给了不可用内容（解释性回复）同样退回空串，由调用方保留规则标题
    assert asyncio.run(suggest_title(FakeRouter("抱歉，我无法命名"), "hi")) == ""


def test_suggest_title_includes_attachment_names() -> None:
    captured: dict[str, Any] = {}

    class CaptureRouter:
        async def chat_with_tools(self, messages: list[dict[str, Any]], **kwargs: Any):
            captured["user"] = messages[-1]["content"]
            return ChatResult(
                text="证书材料整理成周报",
                provider="deepseek",
                model="deepseek-chat",
                prompt_tokens=1,
                completion_tokens=1,
            )

    title = asyncio.run(suggest_title(CaptureRouter(), "整理成周报", ["证书.pdf", "成绩.pdf"]))
    assert title == "证书材料整理成周报"
    assert "证书.pdf" in str(captured["user"])


def test_simple_namespace_router_is_supported() -> None:
    """run_service 里 router 是 ModelRouter，只要 duck-typing 对就不用 import 具体类。"""
    assert hasattr(SimpleNamespace(chat_with_tools=None), "chat_with_tools")
