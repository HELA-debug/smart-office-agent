"""扩展点只读接口：工具 / 子智能体（技能见 skills.py，模板见 templates.py）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..deps import ContainerDep
from .schemas import SubagentListOut, ToolListOut

router = APIRouter(tags=["extensions"])


@router.get("/tools", response_model=ToolListOut, summary="已注册工具（含 JSON Schema）")
async def list_tools(request: Request, container: ContainerDep) -> dict[str, Any]:
    return {"trace_id": request.state.trace_id, "tools": container.runtime.tool_list()}


@router.get(
    "/subagents", response_model=SubagentListOut, summary="已注册子智能体（1 实现 + 2 占位）"
)
async def list_subagents(request: Request, container: ContainerDep) -> dict[str, Any]:
    return {
        "trace_id": request.state.trace_id,
        "subagents": container.runtime.subagent_list(),
    }
