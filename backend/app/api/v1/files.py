"""素材上传接口：单文件字段 file / 多文件字段 files，扩展名+MIME+magic bytes 校验。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Request, UploadFile, status

from ...services.artifact_service import UploadInput
from ..deps import ContainerDep
from .schemas import DeleteOut, FileListOut, FileRecognizeOut, UploadResultOut

router = APIRouter(tags=["files"])


@router.post(
    "/threads/{thread_id}/files",
    response_model=UploadResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="上传素材（单文件 file / 多文件 files）",
    responses={
        415: {"description": "扩展名 / MIME / magic bytes 校验失败"},
        422: {"description": "文件解析失败或内容为空"},
        413: {"description": "超过 max_upload_mb 限制"},
    },
)
async def upload_files(
    thread_id: str,
    request: Request,
    container: ContainerDep,
    file: UploadFile | None = File(default=None),
    files: list[UploadFile] | None = File(default=None),
) -> dict[str, Any]:
    inputs: list[UploadInput] = []
    candidates = ([file] if file is not None else []) + list(files or [])
    for candidate in candidates:
        if candidate is None or not candidate.filename:
            continue
        inputs.append(
            UploadInput(
                filename=candidate.filename,
                content_type=candidate.content_type,
                data=await candidate.read(),
            )
        )
    results = container.artifacts.upload_many(thread_id, inputs)
    primary = results[0]
    return {
        "trace_id": request.state.trace_id,
        "files": results,
        **primary,
    }


@router.get("/threads/{thread_id}/files", response_model=FileListOut, summary="会话素材列表")
async def list_files(thread_id: str, request: Request, container: ContainerDep) -> dict[str, Any]:
    return {
        "trace_id": request.state.trace_id,
        "thread_id": thread_id,
        "files": container.artifacts.list_files(thread_id),
    }


@router.post(
    "/files/{file_id}/recognize",
    response_model=FileRecognizeOut,
    status_code=status.HTTP_200_OK,
    summary="重试识别（图片 OCR / 音视频转写）",
    responses={400: {"description": "该素材不需要识别，或已经在识别中"}},
)
async def recognize_file(file_id: str, request: Request, container: ContainerDep) -> dict[str, Any]:
    """识别失败后的重试入口：模型没下下来、机器临时忙不过来时，不必删了重传。"""
    result = container.artifacts.retry_recognition(file_id)
    return {"trace_id": request.state.trace_id, **result}


@router.delete(
    "/files/{file_id}",
    response_model=DeleteOut,
    status_code=status.HTTP_200_OK,
    summary="删除素材（软删 + 移入 data/trash）",
)
async def delete_file(file_id: str, request: Request, container: ContainerDep) -> dict[str, Any]:
    result = container.artifacts.delete(file_id)
    return {"trace_id": request.state.trace_id, **result}
