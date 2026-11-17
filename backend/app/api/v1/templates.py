"""模板接口：内置 + 自定义模板 CRUD，以及按模板生成 DOCX 产物。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request, status

from ..deps import ContainerDep
from .schemas import TemplateCreateIn, TemplateEnvelope, TemplateListOut, TemplateRenderOut

router = APIRouter(tags=["templates"])


@router.get("/templates", response_model=TemplateListOut, summary="模板列表（内置 + 自定义）")
async def list_templates(request: Request, container: ContainerDep) -> dict[str, Any]:
    return {
        "trace_id": request.state.trace_id,
        "templates": container.templates.list_templates(),
    }


@router.post(
    "/templates",
    response_model=TemplateEnvelope,
    status_code=status.HTTP_201_CREATED,
    summary="新增自定义模板（存 settings 表）",
)
async def create_template(
    body: TemplateCreateIn, request: Request, container: ContainerDep
) -> dict[str, Any]:
    template = container.templates.create_template(
        {
            **body.model_dump(),
            "sections": [section.model_dump() for section in body.sections],
        }
    )
    return {"trace_id": request.state.trace_id, **template}


@router.delete(
    "/templates/{template_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除自定义模板（内置模板不可删）",
)
async def delete_template(template_id: str, container: ContainerDep) -> None:
    container.templates.delete_template(template_id)


@router.post(
    "/templates/{template_id}/render",
    response_model=TemplateRenderOut,
    summary="用模板生成 DOCX 产物（同步返回产物元数据）",
)
async def render_template(
    template_id: str,
    request: Request,
    container: ContainerDep,
    thread_id: str = Query(description="目标会话 ID（使用该会话素材）"),
) -> dict[str, Any]:
    result = container.templates.render(template_id, thread_id)
    return {"trace_id": request.state.trace_id, **result}
