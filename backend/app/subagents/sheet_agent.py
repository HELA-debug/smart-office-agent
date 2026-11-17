"""sheet_agent：占位声明（预留表格清洗与汇总）。"""

from __future__ import annotations

from typing import Any

from .spec import subagent

PROMPT = "你是表格专家。读取上传的表格，清洗后按维度汇总，输出可复核的数据表。"


@subagent(
    "sheet_agent",
    "预留：表格清洗与汇总（占位，未实现）",
    PROMPT,
    tools=[],
    status="placeholder",
)
def run(ctx: Any, task: str = "") -> dict[str, Any]:
    return {
        "ok": False,
        "agent": "sheet_agent",
        "error": {"code": "NOT_IMPLEMENTED", "message": "sheet_agent 为占位，V1.0 实现"},
    }
