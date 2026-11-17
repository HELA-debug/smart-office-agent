"""待办工具：todo.write / todo.list（演示计划能力，低风险）。"""

from __future__ import annotations

from typing import Any

from ..spec import ToolContext, tool

_VALID_STATUS = {"pending", "in_progress", "completed", "cancelled"}


@tool("todo.write", "写入/更新任务计划（todos），返回完整计划列表", risk="low")
def write_todos(ctx: ToolContext, todos: list[dict[str, Any]]) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(todos or []):
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        status = str(item.get("status", "pending"))
        if status not in _VALID_STATUS:
            status = "pending"
        normalized.append(
            {"id": str(item.get("id") or f"t{index + 1}"), "content": content, "status": status}
        )
    if not normalized:
        # 空计划是合法输入（真实模型常先传空 todo），不触发红色失败卡
        return {"todos": ctx.todos, "ok": True, "_summary": "计划为空，已忽略"}
    ctx.todos = normalized
    return {
        "todos": ctx.todos,
        "count": len(ctx.todos),
        "_summary": f"计划已更新（{len(ctx.todos)} 条）",
    }


@tool("todo.list", "读取当前任务计划（todos）", risk="low")
def list_todos(ctx: ToolContext) -> dict[str, Any]:
    done = sum(1 for item in ctx.todos if item.get("status") == "completed")
    return {
        "todos": ctx.todos,
        "count": len(ctx.todos),
        "_summary": f"当前计划 {len(ctx.todos)} 条，已完成 {done} 条",
    }
