"""research_agent：占位声明（预留联网检索与事实核对）。"""

from __future__ import annotations

from typing import Any

from .spec import subagent

PROMPT = "你是检索专家。只引用可核查的来源，区分事实与推断，输出带链接的要点。"


@subagent(
    "research_agent",
    "预留：联网检索与事实核对（占位，未实现）",
    PROMPT,
    tools=[],
    status="placeholder",
)
def run(ctx: Any, task: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "agent": "research_agent",
        "error": {"code": "NOT_IMPLEMENTED", "message": "research_agent 为占位，V1.0 实现"},
    }
