"""项目接口：登记本地文档文件夹、浏览其中的文档、在文件管理器里打开。

设计取舍：
- 路径只接受「已存在的绝对目录」，并且在服务层做重复与越界校验（见 ProjectService）；
- 浏览只返回文件名 / 相对路径 / 大小 / 修改时间，不返回文件内容 —— 内容由 Agent 通过素材读取；
- 打开目录复用存储接口那套 `_open_in_file_manager`，失败返回 opened=false 而不是 500。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, status
from pydantic import BaseModel, ConfigDict, Field

from ..deps import ContainerDep
from .storage import _open_in_file_manager

router = APIRouter(tags=["projects"])


class ProjectCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(max_length=500, description="文件夹绝对路径")
    name: str | None = Field(default=None, max_length=60, description="项目名，缺省用文件夹名")


class ProjectUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, max_length=60)
    pinned: bool | None = None


@router.get("/projects", summary="项目列表（含文件数 / 最近修改 / 目录是否还在）")
async def list_projects(request: Request, container: ContainerDep) -> dict[str, Any]:
    return {"trace_id": request.state.trace_id, "projects": container.projects.list_projects()}


@router.post(
    "/projects",
    status_code=status.HTTP_201_CREATED,
    summary="把本地文件夹添加为项目",
    responses={
        400: {"description": "路径为空 / 不是目录 / 超出项目数量上限"},
        409: {"description": "这个文件夹已经在项目列表里"},
    },
)
async def create_project(
    request: Request, body: ProjectCreateIn, container: ContainerDep
) -> dict[str, Any]:
    project = container.projects.add(body.path, body.name)
    return {"trace_id": request.state.trace_id, "project": project}


@router.patch("/projects/{project_id}", summary="重命名项目 / 置顶")
async def update_project(
    project_id: str, body: ProjectUpdateIn, request: Request, container: ContainerDep
) -> dict[str, Any]:
    project = container.projects.update(project_id, body.name, body.pinned)
    return {"trace_id": request.state.trace_id, "project": project}


@router.delete("/projects/{project_id}", summary="移除项目（只取消登记，不删文件）")
async def delete_project(
    project_id: str, request: Request, container: ContainerDep
) -> dict[str, Any]:
    result = container.projects.remove(project_id)
    return {"trace_id": request.state.trace_id, **result}


@router.get(
    "/projects/{project_id}/files",
    summary="项目内的文档列表（docx/pdf/xlsx/md/txt/pptx，按修改时间倒序）",
    responses={404: {"description": "项目不存在或文件夹已被移动"}},
)
async def list_project_files(
    project_id: str,
    request: Request,
    container: ContainerDep,
    q: str | None = None,
) -> dict[str, Any]:
    files = container.projects.files(project_id, q)
    return {
        "trace_id": request.state.trace_id,
        "project": container.projects.get(project_id),
        "files": files,
    }


@router.post(
    "/projects/{project_id}/reveal",
    summary="在系统文件管理器中打开项目文件夹",
)
async def reveal_project(
    project_id: str, request: Request, container: ContainerDep
) -> dict[str, Any]:
    project = container.projects.get(project_id)
    opened, error = _open_in_file_manager(container.projects.project_path(project_id))
    return {
        "trace_id": request.state.trace_id,
        "project_id": project_id,
        "path": project["path"],
        "opened": opened,
        "error": error,
    }
