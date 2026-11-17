"""用量与审计导出接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import StreamingResponse

from ...services.provider_usage_service import ProviderUsageError
from ..deps import ContainerDep
from .schemas import (
    AuditOut,
    ProviderTokenIn,
    ProviderTokenOut,
    ProviderUsageOut,
    UsageOut,
)

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
    "/usage/provider",
    response_model=ProviderUsageOut,
    summary="官方控制台用量（对账参考；需先填 userToken）",
)
async def provider_usage(
    request: Request,
    container: ContainerDep,
    provider: str = Query(default="deepseek"),
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    force: bool = Query(default=False, description="跳过 60 秒缓存，强制重取"),
) -> dict[str, Any]:
    """拉官方控制台的真实用量。

    官方这个词这里要打个引号理解：接口是平台网页端自用的私有接口，未对外承诺
    稳定，鉴权用浏览器登录态而不是 API Key。所以失败一律返回 200 + available=false
    + error，让前端安静地退回本地账本，而不是弹一个没人看得懂的 5xx。
    """
    service = container.provider_usage
    status = service.status(provider)
    try:
        data = await service.fetch(provider, year=year, month=month, force=force)
    except ProviderUsageError as exc:
        return {
            "trace_id": request.state.trace_id,
            "provider": provider,
            "available": False,
            "has_token": bool(status.get("has_token")),
            "token_preview": status.get("token_preview", ""),
            "error": exc.public(),
        }
    return {"trace_id": request.state.trace_id, **status, **data}


@router.put(
    "/usage/provider/token",
    response_model=ProviderTokenOut,
    summary="设置官方用量 token（仅存进程内存，重启即失效）",
)
async def set_provider_token(
    payload: ProviderTokenIn,
    container: ContainerDep,
) -> dict[str, Any]:
    try:
        return container.provider_usage.set_token(payload.provider, payload.token)
    except ProviderUsageError as exc:
        return {
            "provider": payload.provider,
            "has_token": False,
            "token_preview": "",
            "error": exc.public(),
        }


@router.delete(
    "/usage/provider/token",
    response_model=ProviderTokenOut,
    summary="清除官方用量 token",
)
async def clear_provider_token(
    container: ContainerDep,
    provider: str = Query(default="deepseek"),
) -> dict[str, Any]:
    return container.provider_usage.clear_token(provider)


@router.get(
    "/usage/balance",
    response_model=None,
    summary="账户余额（走 API Key 的公开接口）",
)
async def account_balance(
    request: Request,
    container: ContainerDep,
    provider: str = Query(default="deepseek"),
) -> dict[str, Any]:
    return {
        "trace_id": request.state.trace_id,
        "provider": provider,
        **await container.provider_usage.balance(provider),
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
