"""设置中心：GET 当前生效值 + 来源；PUT 保存后热更新运行时配置（无需重启）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ..deps import ContainerDep
from .schemas import SettingsOut, SettingsUpdateIn

router = APIRouter(tags=["settings"])


@router.get(
    "/settings",
    response_model=SettingsOut,
    summary="读取设置（含来源 db/env/default 与密钥引用）",
)
async def get_settings(request: Request, container: ContainerDep) -> dict[str, Any]:
    return {"trace_id": request.state.trace_id, **container.settings_service.effective()}


@router.put(
    "/settings",
    response_model=SettingsOut,
    summary="更新设置（保存即热生效）",
    responses={
        400: {"description": "不在白名单或类型不合法"},
        200: {
            "description": "更新后的生效值",
            "content": {
                "application/json": {
                    "example": {
                        "trace_id": "tr_xxx",
                        "model_provider": "mock",
                        "mock_mode": True,
                        "sources": {"model_provider": "db", "approval_rules": "db"},
                    }
                }
            },
        },
    },
)
async def update_settings(
    body: SettingsUpdateIn, request: Request, container: ContainerDep
) -> dict[str, Any]:
    patch = {key: value for key, value in body.model_dump().items() if value is not None}
    effective = container.settings_service.update(patch)
    return {"trace_id": request.state.trace_id, **effective}
