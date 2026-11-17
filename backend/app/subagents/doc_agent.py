"""doc_agent：唯一实现的子智能体（读素材 → 按模板成文 → 生成 DOCX）。"""

from __future__ import annotations

from typing import Any

from ..tools.registry import REGISTRY, ToolContext
from .spec import subagent

PROMPT = (
    "你是文档专家。先读取用户上传的素材，按指定模板（weekly/meeting/summary）成文，"
    "必须生成 DOCX；引用材料时标注文件名与段落；不得编造材料中没有的信息。"
)


def _gate(ctx: ToolContext, spec: Any) -> dict[str, Any] | None:
    """子智能体的写权限门：和引擎主链路用同一个 `policy.decide_write`。

    为什么要单独写这一层。引擎的门控在 `_run_single_tool` 里，而子智能体是
    **直接调 handler** 的（它自己有一套工具清单），根本不经过那条路径。
    现在它没被主链路调用，所以不是活漏洞；但只要有人把 `run()` 接进工具表，
    它就会变成「绕过审批与授权的一道侧门」。门装在这里，接线那天不用再想起来。

    没有 reading（不知道用户这一轮到底说了什么）时按不放行处理：宁可让子智能体
    回一句「先说明打算」，也不要凭空写一份用户没要的文件。
    """
    from ..agents.policy import decide_write
    from ..agents.reading import TurnReading

    reading = getattr(ctx, "reading", None) or TurnReading()
    # 原文一定要带上：`decide_write` 靠它查「先别 / 我点头了再 / 算了」这类
    # 确定性否决。没有原文时只剩理解层的结论，而理解层正是可能读错的那一环。
    gate = decide_write(
        spec.risk.value,
        reading,
        message=str(getattr(ctx, "message", "") or ""),
    )
    if gate.allow:
        return None
    return {
        "ok": False,
        "skipped": True,
        "reason": "not_authorized",
        "message": gate.hint,
    }


@subagent(
    "doc_agent",
    "读取素材、按模板成文并生成 DOCX（周报/纪要/摘要）",
    PROMPT,
    tools=["file.read", "doc.generate_report"],
    status="implemented",
)
def run(ctx: ToolContext, task: str = "") -> dict[str, Any]:
    read_tool = REGISTRY.get("file.read")
    doc_tool = REGISTRY.get("doc.generate_report")
    if read_tool is None or doc_tool is None:
        return {"ok": False, "error": {"code": "TOOL_ERROR", "message": "工具未注册"}}
    blocked = _gate(ctx, doc_tool)
    if blocked is not None:
        return {
            "ok": False,
            "agent": "doc_agent",
            "blocked": True,
            "reason": blocked["reason"],
            "summary": blocked["message"],
        }
    read_result = read_tool.handler(ctx)
    title = task.strip()[:60] if task.strip() else ""
    doc_result = doc_tool.handler(ctx, title=title, template="weekly")
    return {
        "ok": True,
        "agent": "doc_agent",
        "tool_results": [read_result, doc_result],
        "artifact_id": doc_result.get("artifact_id"),
        "summary": doc_result.get("_summary", "文档已生成"),
    }
