"""健康检查：返回版本/模式/模型/降级状态/引擎状态/扩展点摘要。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from ...agents.registry import engine_capabilities
from ..deps import ContainerDep
from .schemas import HealthOut

router = APIRouter(tags=["health"])


def _engine_state(container: ContainerDep) -> dict[str, Any]:
    """配置引擎 vs 实际生效引擎（无 Key / 未实现适配器自动降级）。"""
    settings = container.settings
    requested = settings.engine_kind
    # 只认英文 id：name 是中文展示名，拿它当 key 会让 requested（mock/real）永远查不到
    capabilities = {item["id"]: item["status"] for item in engine_capabilities()}
    supported = capabilities.get(requested) == "implemented"
    configured = settings.real_model_configured and not container.runtime.degraded
    # deepagents 适配器尚未实现时由 real 引擎兜底（事件协议一致）
    effective = "mock" if requested == "mock" or not configured else "real"
    # 发送门禁用：现在有没有能用的模型（演示模式不依赖 Key，恒可发）。
    # 以前这个状态只能靠「mode 变成 mock」猜，界面没法区分「用户自己选了演示」
    # 和「没配 Key 被迫降级」，于是没配 Key 也能把消息发出去、跑出本地假数据。
    model_ready = settings.model_ready
    return {
        "engine": requested,
        "engine_effective": effective,
        "engine_supported": supported,
        "engine_reason": _engine_reason(container, requested, effective),
        "model_ready": model_ready,
        "model_hint": ""
        if model_ready
        else "还没有可用的模型：点输入框左侧的「选择模型」挑一家，或到设置页添加 Key；演示模式不受影响",
    }


def _engine_reason(container: ContainerDep, requested: str, effective: str) -> str:
    """实际生效的不是配置的引擎时，用一句人话说清是谁挡住的。

    「设置里写着真实模型、顶栏写着 mock」这种不一致最伤信任：界面上两处各说各话，
    用户只能猜是不是根本没调大模型。原因必须由后端给——只有它知道是开关、缺 Key
    还是探测失败。
    """
    if effective != "mock":
        return ""
    settings = container.settings
    if requested == "mock":
        return "执行引擎选的是「演示模式」：不调用真实模型，也不产生费用"
    if settings.mock_mode:
        return "MOCK_MODE=true 还开着：这个开关会一票否决真实模型，改成 false 或把执行引擎切到「真实模型」"
    provider = settings.configured_provider
    if not settings.provider_api_key(provider):
        return f"没有配置 {provider} 的 API Key（模型 Key 一栏为空）"
    if not settings.provider_base_url(provider):
        return f"{provider} 缺少接口地址（base_url）"
    runtime = container.runtime
    if runtime.degraded and runtime.degraded_reason:
        return runtime.degraded_reason
    return "真实模型探测没通过，暂时用演示模式兜底"


@router.get("/health", response_model=HealthOut, summary="健康检查")
async def health(request: Request, container: ContainerDep) -> dict[str, Any]:
    base = container.runtime.health()
    engine_state = _engine_state(container)
    base["mode"] = engine_state["engine_effective"]
    base["mock"] = engine_state["engine_effective"] == "mock"
    # 识别组件装没装、用的哪个模型：界面据此决定「图片 / 录音」入口亮不亮
    base["media"] = container.artifacts.media.capabilities()
    return {"trace_id": request.state.trace_id, **base, **engine_state}
