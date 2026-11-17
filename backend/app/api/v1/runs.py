"""运行接口：SSE 主链路、取消、重试、事件回放（Last-Event-ID / ?after=）。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse

from ...core.errors import AppError, ErrorCode
from ...core.events import parse_last_event_id, sse_comment, sse_frame
from ...services.run_service import RunChunk
from ...tools.builtin.doc import OUTPUT_FORMATS
from ..deps import ContainerDep
from .schemas import (
    RunCancelOut,
    RunEnvelope,
    RunEventsOut,
    RunListOut,
    RunRequestIn,
)

router = APIRouter(tags=["runs"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
_SSE_RESPONSE: dict[int | str, dict[str, Any]] = {200: {"content": {"text/event-stream": {}}}}


def _after_param(request: Request) -> int | None:
    header_value = parse_last_event_id(request.headers.get("Last-Event-ID"))
    query_value = request.query_params.get("after")
    if query_value is not None:
        try:
            return max(0, int(query_value))
        except ValueError as exc:
            raise AppError(ErrorCode.BAD_REQUEST, "after 必须是整数") from exc
    return header_value


async def _chunks_to_sse(chunks: AsyncIterator[RunChunk]) -> AsyncIterator[str]:
    try:
        async for chunk in chunks:
            if chunk.comment:
                yield sse_comment(chunk.comment)
            elif chunk.event is not None:
                yield sse_frame(chunk.seq or 0, chunk.event, chunk.data)
    except asyncio.CancelledError:
        raise
    finally:
        aclose = getattr(chunks, "aclose", None)
        if aclose is not None:
            await aclose()


def _sse_response(chunks: AsyncIterator[RunChunk], trace_id: str) -> StreamingResponse:
    return StreamingResponse(
        _chunks_to_sse(chunks),
        media_type="text/event-stream",
        headers={**_SSE_HEADERS, "X-Trace-ID": trace_id},
    )


@router.post(
    "/threads/{thread_id}/runs/stream",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="发起任务（SSE）",
    responses=_SSE_RESPONSE,
)
async def stream_run(
    thread_id: str, body: RunRequestIn, request: Request, container: ContainerDep
) -> StreamingResponse:
    container.threads.get(thread_id)
    if body.mode is not None and body.mode not in ("mock", "real"):
        raise AppError(ErrorCode.BAD_REQUEST, "mode 只能是 mock 或 real")

    if body.output_format is not None and body.output_format.strip().lower() not in OUTPUT_FORMATS:
        supported = " / ".join(sorted(OUTPUT_FORMATS))
        raise AppError(ErrorCode.BAD_REQUEST, f"output_format 仅支持：{supported}")

    if body.run_id:
        run = container.runs.get_run(body.run_id)
        if run.thread_id != thread_id:
            raise AppError(ErrorCode.NOT_FOUND, f"运行不属于该会话：{body.run_id}")
        after = _after_param(request) or 0
        return _sse_response(container.runs.resume(body.run_id, after), request.state.trace_id)

    message = (body.message or "").strip()
    if not message:
        raise AppError(ErrorCode.BAD_REQUEST, "message 不能为空")
    # 门禁必须在开流之前查：start() 是异步生成器，等它抛错时响应头已发出，
    # 用户只会看到连接断掉，连一句「还没配模型」都收不到
    container.runs.ensure_model_ready(body.mode)
    if body.project_id:
        # 先校验项目存在（目录被移走时给明确 404，而不是等运行到一半才失败）
        container.projects.get(body.project_id)
    container.runs.validate_attachments(thread_id, body.attachment_ids)
    return _sse_response(
        container.runs.start(
            thread_id,
            message,
            trace_id=request.state.trace_id,
            mode_override=body.mode,
            output_format=body.output_format,
            project_id=body.project_id,
            project_files=body.project_files,
            approval_mode=body.approval_mode,
            attachment_ids=body.attachment_ids,
            doc_style=body.doc_style,
        ),
        request.state.trace_id,
    )


@router.get("/runs", response_model=RunListOut, summary="运行列表（可按会话/状态过滤）")
async def list_runs(
    request: Request,
    container: ContainerDep,
    thread_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    result = container.runs.list_runs(
        thread_id=thread_id,
        status=status_filter,
        page=page,
        page_size=page_size,
    )
    return {"trace_id": request.state.trace_id, **result}


@router.get("/threads/{thread_id}/runs", response_model=RunListOut, summary="会话运行列表")
async def list_thread_runs(
    thread_id: str,
    request: Request,
    container: ContainerDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    result = container.runs.list_runs(thread_id=thread_id, page=page, page_size=page_size)
    return {"trace_id": request.state.trace_id, **result}


@router.get("/runs/{run_id}", response_model=RunEnvelope, summary="运行详情")
async def get_run(run_id: str, request: Request, container: ContainerDep) -> dict[str, Any]:
    run = container.runs.get_run(run_id)
    return {"trace_id": request.state.trace_id, **container.runs.usage_public(run)}


@router.post(
    "/runs/{run_id}/cancel",
    response_model=RunCancelOut,
    summary="取消运行（中断任务并推送 run.cancelled，重复调用幂等）",
)
async def cancel_run(run_id: str, request: Request, container: ContainerDep) -> dict[str, Any]:
    result = await container.runs.cancel(run_id)
    return {"trace_id": request.state.trace_id, **result}


@router.post(
    "/runs/{run_id}/retry",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="重试运行（同会话同任务消息新建 run，SSE 返回）",
    responses=_SSE_RESPONSE,
)
async def retry_run(run_id: str, request: Request, container: ContainerDep) -> StreamingResponse:
    target = container.runs.retry_message(run_id)
    container.runs.ensure_model_ready()
    return _sse_response(
        container.runs.start(
            target.thread_id,
            target.message,
            trace_id=request.state.trace_id,
            attachment_ids=target.attachment_ids or None,
        ),
        request.state.trace_id,
    )


@router.get("/runs/{run_id}/events", response_model=RunEventsOut, summary="运行事件回放（JSON）")
async def list_run_events(
    run_id: str,
    request: Request,
    container: ContainerDep,
    after: int = Query(default=0, ge=0, description="只返回 seq > after 的事件"),
) -> dict[str, Any]:
    events = container.runs.events_json(run_id, after=after)
    return {"trace_id": request.state.trace_id, "run_id": run_id, "events": events}


@router.get(
    "/runs/{run_id}/events/stream",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="运行事件回放（SSE，支持 Last-Event-ID 断线续传）",
    responses=_SSE_RESPONSE,
)
async def stream_run_events(
    run_id: str, request: Request, container: ContainerDep
) -> StreamingResponse:
    after = _after_param(request) or 0
    container.runs.get_run(run_id)
    return _sse_response(container.runs.resume(run_id, after), request.state.trace_id)
