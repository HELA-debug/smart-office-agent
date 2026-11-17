"""技能接口：列表 + 启停（启停后运行时提示词立即重建）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Request, UploadFile, status

from ...core.errors import AppError, ErrorCode
from ...services.skill_drafter import draft_skill as draft_skill_doc
from ..deps import ContainerDep
from .schemas import (
    SkillCatalogOut,
    SkillDraftIn,
    SkillDraftOut,
    SkillInstallOut,
    SkillListOut,
    SkillPatchIn,
    SkillPatchOut,
)

router = APIRouter(tags=["skills"])


@router.get("/skills", response_model=SkillListOut, summary="已加载技能与启用状态")
async def list_skills(request: Request, container: ContainerDep) -> dict[str, Any]:
    return {
        "trace_id": request.state.trace_id,
        "skills": container.skills.list_skills(),
        "prompt_chars": container.skills.prompt_chars(),
    }


@router.get(
    "/skills/catalog",
    response_model=SkillCatalogOut,
    summary="技能库：可一键添加的内置技能（未添加的不进提示词）",
)
async def list_skill_catalog(request: Request, container: ContainerDep) -> dict[str, Any]:
    items = container.skills.list_catalog()
    categories = list(dict.fromkeys(item["category"] for item in items if item["category"]))
    return {"trace_id": request.state.trace_id, "skills": items, "categories": categories}


@router.post(
    "/skills/catalog/{skill_id}/install",
    response_model=SkillInstallOut,
    status_code=status.HTTP_201_CREATED,
    summary="从技能库添加技能（复制到 app/skills 并默认启用）",
    responses={404: {"description": "技能库里没有这个技能"}, 409: {"description": "已经添加过"}},
)
async def install_skill_from_catalog(
    skill_id: str, request: Request, container: ContainerDep
) -> dict[str, Any]:
    result = container.skills.install_from_catalog(skill_id)
    return {"trace_id": request.state.trace_id, **result}


@router.patch(
    "/skills/{skill_id}",
    response_model=SkillPatchOut,
    summary="启用/停用技能（立即影响运行时提示词与模板 enabled 状态）",
)
async def patch_skill(
    skill_id: str, body: SkillPatchIn, request: Request, container: ContainerDep
) -> dict[str, Any]:
    result = container.skills.set_enabled(skill_id, body.enabled)
    return {"trace_id": request.state.trace_id, **result}


@router.post(
    "/skills/draft",
    response_model=SkillDraftOut,
    summary="让当前模型把一句话需求写成一张技能便签（没模型时返回本地骨架）",
    responses={400: {"description": "没说清楚要什么"}},
)
async def draft_skill(
    body: SkillDraftIn, request: Request, container: ContainerDep
) -> dict[str, Any]:
    """「先让模型写一版，再让人改」比「从空白模板开始」容易得多。

    产物是一份合法的 SKILL.md，前端拿走后仍然走 /skills/import 落盘，
    所以这里不写任何文件，也不改任何运行期状态。
    """
    idea = body.idea.strip()
    if not idea:
        # "   " 能过 min_length=1，但对模型和本地骨架都是纯噪声：当场拒掉比生成垃圾好
        raise AppError(ErrorCode.BAD_REQUEST, "先用一句话说清这个技能要做什么")
    draft = await draft_skill_doc(
        container.runtime.router,
        container.settings,
        idea,
        taken={item["name"] for item in container.skills.list_skills()},
    )
    return {"trace_id": request.state.trace_id, **draft}


@router.post(
    "/skills/import",
    status_code=status.HTTP_201_CREATED,
    summary="导入技能（上传一个 SKILL.md，导入后立即出现在技能列表里）",
    responses={409: {"description": "已有同名技能"}, 400: {"description": "文件为空或非 UTF-8"}},
)
async def import_skill(
    request: Request, container: ContainerDep, file: UploadFile = File(...)
) -> dict[str, Any]:
    data = await file.read()
    result = container.skills.import_skill(file.filename or "SKILL.md", data)
    return {"trace_id": request.state.trace_id, **result}


@router.delete(
    "/skills/{skill_id}",
    summary="删除技能（目录挪进 app/skills/.trash，可人工捞回）",
)
async def delete_skill(skill_id: str, request: Request, container: ContainerDep) -> dict[str, Any]:
    result = container.skills.delete_skill(skill_id)
    return {"trace_id": request.state.trace_id, **result}


@router.get(
    "/prompt-packs",
    summary="内置提示词包（按需求自动匹配注入本轮 system prompt）",
)
async def list_prompt_packs(request: Request, container: ContainerDep) -> dict[str, Any]:
    return {
        "trace_id": request.state.trace_id,
        "packs": container.prompt_packs.list_packs(),
        "max_per_run": 2,
    }
