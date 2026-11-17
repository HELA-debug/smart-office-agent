"""模型管理：登记供应商（Key 只存 env 引用）+ 真实探测。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, status

from ..deps import ContainerDep
from .schemas import (
    ModelBalanceOut,
    ModelCreateIn,
    ModelEnvelope,
    ModelKeyDisconnectOut,
    ModelKeyIn,
    ModelKeyOut,
    ModelListOut,
    ModelTestOut,
)

router = APIRouter(tags=["models"])


@router.get(
    "/models",
    response_model=ModelListOut,
    summary="模型供应商列表（不含明文 Key，只返回引用与探测状态）",
)
async def list_models(request: Request, container: ContainerDep) -> dict[str, Any]:
    return {
        "trace_id": request.state.trace_id,
        "models": container.models.list_models(),
    }


@router.post(
    "/models",
    response_model=ModelEnvelope,
    status_code=status.HTTP_201_CREATED,
    summary="新增/更新模型登记（api_key_ref 只允许 env:NAME）",
)
async def upsert_model(
    body: ModelCreateIn, request: Request, container: ContainerDep
) -> dict[str, Any]:
    model = container.models.upsert_model(body.model_dump())
    return {"trace_id": request.state.trace_id, **model}


@router.put(
    "/models/{model_id}/key",
    response_model=ModelKeyOut,
    summary="保存供应商 Key（明文只落本地 .env，响应仅回显掩码）",
)
async def save_model_key(
    model_id: str, body: ModelKeyIn, request: Request, container: ContainerDep
) -> dict[str, Any]:
    result = container.models.save_key(model_id, body.api_key, body.env_name)
    return {"trace_id": request.state.trace_id, **result}


@router.delete(
    "/models/{model_id}/key",
    response_model=ModelKeyDisconnectOut,
    summary="断开供应商 Key（进程 env、Settings、本地 .env 三处同清，分享/部署前用）",
)
async def disconnect_model_key(
    model_id: str, request: Request, container: ContainerDep
) -> dict[str, Any]:
    result = container.models.disconnect_key(model_id)
    return {"trace_id": request.state.trace_id, **result}


@router.get(
    "/models/{model_id}/balance",
    response_model=ModelBalanceOut,
    summary="查供应商账户余额（对账用：确认本地账单花的是这个账号）",
)
async def model_balance(model_id: str, request: Request, container: ContainerDep) -> dict[str, Any]:
    result = await container.models.balance(model_id)
    return {"trace_id": request.state.trace_id, **result}


@router.post(
    "/models/{model_id}/test",
    response_model=ModelTestOut,
    summary="真实探测模型（失败返回脱敏原因，不泄露 Key）",
)
async def test_model(model_id: str, request: Request, container: ContainerDep) -> dict[str, Any]:
    result = await container.models.test_model(model_id)
    return {"trace_id": request.state.trace_id, **result}
