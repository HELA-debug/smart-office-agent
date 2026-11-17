"""产物接口：分页列表、元数据、下载、预览、软删、重新生成。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from ...core.events import sse_comment, sse_frame
from ...domain.formats import ARTIFACT_TYPE_HINT
from ..deps import ContainerDep
from .schemas import (
    ArtifactBatchDeleteIn,
    ArtifactBatchDeleteOut,
    ArtifactEnvelope,
    ArtifactListOut,
    ArtifactTrashListOut,
    DeleteOut,
)

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts", response_model=ArtifactListOut, summary="产物列表（分页/筛选）")
async def list_artifacts(
    request: Request,
    container: ContainerDep,
    thread_id: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
    type: str | None = Query(default=None, description=ARTIFACT_TYPE_HINT),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    include_uploads: bool = Query(
        default=False, description="是否把上传的素材也列出来（产物中心默认只列生成的产物）"
    ),
) -> dict[str, Any]:
    result = container.artifacts.list_artifacts(
        thread_id=thread_id,
        run_id=run_id,
        type_filter=type,
        page=page,
        page_size=page_size,
        include_uploads=include_uploads,
    )
    return {"trace_id": request.state.trace_id, **result}


@router.get(
    "/artifacts/trash",
    response_model=ArtifactTrashListOut,
    summary="回收站列表（已软删的产物，可恢复 / 彻底删除）",
)
async def list_trash(
    request: Request,
    container: ContainerDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    include_uploads: bool = Query(
        default=False, description="是否把上传素材也算进来（默认只列生成的产物）"
    ),
) -> dict[str, Any]:
    result = container.artifacts.list_trash(
        page=page, page_size=page_size, include_uploads=include_uploads
    )
    return {"trace_id": request.state.trace_id, **result}


@router.post(
    "/artifacts/{artifact_id}/restore",
    response_model=None,
    summary="从回收站恢复（文件挪回原目录）",
)
async def restore_artifact(
    artifact_id: str, request: Request, container: ContainerDep
) -> dict[str, Any]:
    result = container.artifacts.restore(artifact_id)
    return {"trace_id": request.state.trace_id, **result}


@router.delete(
    "/artifacts/{artifact_id}/purge",
    response_model=None,
    summary="彻底删除（清掉回收站文件与记录，不可恢复）",
)
async def purge_artifact(
    artifact_id: str, request: Request, container: ContainerDep
) -> dict[str, Any]:
    result = container.artifacts.purge(artifact_id)
    return {"trace_id": request.state.trace_id, **result}


@router.post(
    "/artifacts/{artifact_id}/open",
    response_model=None,
    summary="用系统默认程序打开（装了 WPS 即用 WPS）",
)
async def open_artifact(
    artifact_id: str, request: Request, container: ContainerDep
) -> dict[str, Any]:
    result = container.artifacts.open_file(artifact_id)
    return {"trace_id": request.state.trace_id, **result}


@router.post(
    "/artifacts/batch-delete",
    response_model=ArtifactBatchDeleteOut,
    status_code=status.HTTP_200_OK,
    summary="批量软删产物（部分成功语义，逐条返回结果）",
)
async def batch_delete_artifacts(
    payload: ArtifactBatchDeleteIn,
    request: Request,
    container: ContainerDep,
) -> dict[str, Any]:
    result = container.artifacts.delete_many(payload.artifact_ids)
    return {"trace_id": request.state.trace_id, **result}


@router.get("/artifacts/{artifact_id}", response_model=ArtifactEnvelope, summary="产物元数据")
async def get_artifact(
    artifact_id: str, request: Request, container: ContainerDep
) -> dict[str, Any]:
    artifact = container.artifacts.get(artifact_id)
    return {"trace_id": request.state.trace_id, **container.artifacts.metadata(artifact)}


@router.get(
    "/artifacts/{artifact_id}/download",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="产物下载（软删后 404）；inline=1 时浏览器内联打开（PDF 预览用）",
)
async def download_artifact(
    artifact_id: str,
    container: ContainerDep,
    inline: bool = Query(
        default=False,
        description="true 时 Content-Disposition 用 inline：PDF 交给浏览器内置阅读器，不当附件下载",
    ),
) -> FileResponse:
    path, filename, media_type = container.artifacts.download_target(artifact_id)
    return FileResponse(
        path=str(path),
        filename=filename,
        media_type=media_type,
        # 默认 attachment 是「下载」该有的行为；但预览 iframe 拉同一个地址时，
        # attachment 会让浏览器直接落盘（点预览变成自动下载），所以预览走 inline。
        content_disposition_type="inline" if inline else "attachment",
    )


@router.get(
    "/artifacts/{artifact_id}/preview",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="产物预览（HTML 片段）",
    responses={200: {"content": {"text/html": {}}}},
)
async def preview_artifact(artifact_id: str, container: ContainerDep) -> HTMLResponse:
    return HTMLResponse(
        content=container.artifacts.preview(artifact_id),
        media_type="text/html; charset=utf-8",
    )


@router.delete(
    "/artifacts/{artifact_id}",
    response_model=DeleteOut,
    status_code=status.HTTP_200_OK,
    summary="软删产物（文件移入 data/trash，下载/预览返回 404）",
)
async def delete_artifact(
    artifact_id: str, request: Request, container: ContainerDep
) -> dict[str, Any]:
    result = container.artifacts.delete(artifact_id)
    return {"trace_id": request.state.trace_id, **result}


@router.post(
    "/artifacts/{artifact_id}/regenerate",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="基于原 run 的任务消息重新生成（SSE 返回新 run）",
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def regenerate_artifact(
    artifact_id: str, request: Request, container: ContainerDep
) -> StreamingResponse:
    artifact = container.artifacts.get(artifact_id)
    target = container.runs.regenerate_source(artifact)
    chunks = container.runs.start(
        target.thread_id,
        target.message,
        trace_id=request.state.trace_id,
        attachment_ids=target.attachment_ids or None,
    )

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk in chunks:
                if chunk.comment:
                    yield sse_comment(chunk.comment)
                elif chunk.event is not None:
                    yield sse_frame(chunk.seq or 0, chunk.event, chunk.data)

        finally:
            aclose = getattr(chunks, "aclose", None)
            if aclose is not None:
                await aclose()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Trace-ID": request.state.trace_id,
        },
    )
