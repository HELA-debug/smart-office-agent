"""用量与审计导出接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse

from ..deps import ContainerDep
from .schemas import AuditOut, UsageOut

router = APIRouter(tags=["usage"])


@router.get("/threads/{thread_id}/audit", response_model=AuditOut, summary="会话审计")
async def audit_thread(thread_id: str, request: Request, container: ContainerDep) -> dict[str, Any]:
    return {"trace_id": request.state.trace_id, **container.runs.audit(thread_id)}


@router.get(
    "/usage/summary",
    response_model=UsageOut,
    summary="用量汇总（按日/供应商/模型聚合，支持 7d/30d）",
)
async def usage_summary(
    request: Request,
    container: ContainerDep,
    range_key: str = Query(default="7d", alias="range", pattern="^(7d|30d|today|all)$"),
    thread_id: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
) -> dict[str, Any]:
    return {
        "trace_id": request.state.trace_id,
        **container.usage.summary(thread_id=thread_id, range_key=range_key, limit=limit),
    }


@router.get(
    "/audit/export",
    response_model=None,
    responses={
        200: {
            "description": "审计导出文件（JSON 或 CSV）",
            "content": {"application/json": {}, "text/csv": {}},
        }
    },
    summary="审计导出（json/csv，返回文件下载）",
)
async def export_audit(
    container: ContainerDep,
    format: str = Query(default="json", pattern="^(json|csv)$"),
    thread_id: str | None = Query(default=None),
) -> Response:
    content, filename, media_type = container.runs.export_audit(fmt=format, thread_id=thread_id)
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
        },
    )
