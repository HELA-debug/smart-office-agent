"""引擎注册表：mock / real（/ deepagents 适配器）按配置选择，事件协议一致。

id 与 name 分工（以前混在一起，出过两个问题）：

- ``id`` 是英文标识（mock / real / deepagents），给 /health、契约和前端映射用，
  ``engine_supported`` 判定与 ``engines`` 列表都只认它；
- ``name`` 只是给人看的中文名，改它不该影响任何判断，也不该被塞进接口返回值。
"""

from __future__ import annotations

from typing import Any

from ..tools.registry import ToolRegistry
from .engine_protocol import AgentEngine
from .mock_engine import MockEngine
from .model_router import ModelRouter
from .real_engine import RealEngine


def build_mock_engine(
    tools: ToolRegistry,
    approval_tools: list[str],
    prompt: str = "",
) -> AgentEngine:
    return MockEngine(tools=tools, approval_tools=approval_tools, prompt=prompt)


def build_real_engine(
    tools: ToolRegistry,
    approval_tools: list[str],
    router: ModelRouter,
    prompt: str = "",
) -> AgentEngine:
    return RealEngine(tools=tools, approval_tools=approval_tools, router=router, prompt=prompt)


def engine_capabilities() -> list[dict[str, Any]]:
    """引擎清单：id 是机器用的键，name / description 只用于展示。"""
    return [
        {
            "id": "mock",
            "name": "模拟引擎",
            "description": "确定性 mock 引擎，断网可跑，事件顺序可复现",
            "status": "implemented",
        },
        {
            "id": "real",
            "name": "真实模型",
            "description": "真实模型 ReAct 引擎（DeepSeek/千问/GLM，工具自主调用 + 审批）",
            "status": "implemented",
        },
        {
            "id": "deepagents",
            "name": "deepagents",
            "description": (
                "deepagents(LangGraph) 适配位：实现 AgentEngine 协议并注册即可接入，"
                "事件协议/工具注册表/审批策略不变（见 ADR-0003）"
            ),
            "status": "planned",
        },
    ]
