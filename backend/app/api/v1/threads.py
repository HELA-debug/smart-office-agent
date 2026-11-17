"""会话接口：创建/搜索分页列表/详情/重命名/置顶/软删。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, status

from ..deps import ContainerDep
from .schemas import (
    ErrorResponse,
    ThreadBulkDeleteIn,
    ThreadBulkDeleteOut,
    ThreadCreateIn,
    ThreadCreateOut,
    ThreadDetailEnvelope,
    ThreadListOut,
    ThreadReorderIn,
    ThreadReorderOut,
    ThreadUpdateIn,
)

router = APIRouter(tags=["threads"])


@router.post(
    "/threads",
    response_model=ThreadCreateOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建会话",
    responses={
        201: {
            "description": "创建成功",
            "content": {
                "application/json": {
                    "example": {
                        "trace_id": "tr_xxx",
                        "thread_id": "th_xxx",
                        "title": "整理周报",
                        "created_at": "2026-10-23T10:00:00+08:00",
                        "updated_at": "2026-10-23T10:00:00+08:00",
                        "pinned": False,
                        "message_count": 0,
                        "artifact_count": 0,
                    }
                }
            },
        }
    },
)
async def create_thread(
    request: Request, container: ContainerDep, body: ThreadCreateIn | None = None
) -> dict[str, Any]:
    thread = container.threads.create(body.title if body else None)
    return {
        "trace_id": request.state.trace_id,
        "thread_id": thread.id,
        "title": thread.title,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
        "pinned": thread.pinned,
        "message_count": 0,
        "artifact_count": 0,
    }


@router.get(
    "/threads",
    response_model=ThreadListOut,
    summary="会话列表（搜索 + 分页，置顶优先）",
)
async def list_threads(
    request: Request,
    container: ContainerDep,
    q: str | None = Query(default=None, description="按标题或 ID 搜索"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    result = container.threads.list(q=q, page=page, page_size=page_size)
    return {"trace_id": request.state.trace_id, **result}


@router.get("/threads/{thread_id}", response_model=ThreadDetailEnvelope, summary="会话详情")
async def get_thread(thread_id: str, request: Request, container: ContainerDep) -> dict[str, Any]:
    return {"trace_id": request.state.trace_id, **container.threads.detail(thread_id)}


@router.patch(
    "/threads/{thread_id}",
    response_model=ThreadCreateOut,
    summary="重命名 / 置顶",
)
async def update_thread(
    thread_id: str,
    body: ThreadUpdateIn,
    request: Request,
    container: ContainerDep,
) -> dict[str, Any]:
    thread = container.threads.update(thread_id, title=body.title, pinned=body.pinned)
    return {
        "trace_id": request.state.trace_id,
        "thread_id": thread.id,
        "title": thread.title,
        "created_at": thread.created_at,
        "updated_at": thread.updated_at,
        "pinned": thread.pinned,
        "message_count": 0,
        "artifact_count": 0,
    }


@router.delete(
    "/threads/{thread_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="软删会话（列表不再返回）",
)
async def delete_thread(thread_id: str, container: ContainerDep) -> None:
    container.threads.soft_delete(thread_id)


@router.post(
    "/threads/reorder",
    response_model=ThreadReorderOut,
    summary="重排会话顺序（左栏拖动排序）",
)
async def reorder_threads(
    body: ThreadReorderIn,
    request: Request,
    container: ContainerDep,
) -> dict[str, Any]:
    """按传入顺序重写 sort_index。整份列表一起传，重编号后顺序才是确定的。"""
    return {
        "trace_id": request.state.trace_id,
        "reordered": container.threads.reorder(body.thread_ids),
    }


@router.post(
    "/threads/bulk-delete",
    response_model=ThreadBulkDeleteOut,
    summary="批量软删会话（左栏「批量清理」）",
    responses={
        400: {
            "model": ErrorResponse,
            "description": "thread_ids 为空或超过 200 个（参数校验失败）",
        },
    },
)
async def bulk_delete_threads(
    body: ThreadBulkDeleteIn,
    request: Request,
    container: ContainerDep,
) -> dict[str, Any]:
    """一次请求删一批：列表是分页拉的，逐个 DELETE 要发 N 次、失败半途还会留下半成品状态。"""
    return {
        "trace_id": request.state.trace_id,
        "deleted": container.threads.soft_delete_many(body.thread_ids),
    }
